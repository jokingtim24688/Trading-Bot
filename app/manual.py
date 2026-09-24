"""Manual trading for the Manual tab: what the MT5 mobile app does.

Quotes, one-click market orders, pending orders (buy/sell limit and stop), SL/TP edits, full, partial and bulk closes
(all / profitable / losing / buys / sells, by owner and symbol), the pending-order list and cancel, and today's closed
deals. Orders placed here use magic 0, so they show as "you" and the bot never touches or counts them. A real-money
account is refused unless the request carries confirm_real (the tab sends it only after you confirm).
"""
import json
import threading
import time
from datetime import datetime, timedelta, timezone

from . import mt5_service as ms
from . import watch
from .settings import load as load_settings

MANUAL_MAGIC = 0
COMMENT = "manual (app)"
OWNERS = {"bot": ms.BOT_MAGIC, "hermes": ms.HERMES_MAGIC}
_notes_lock = threading.Lock()


def _owner(magic: int) -> str:
    return "bot" if magic == ms.BOT_MAGIC else "hermes" if magic == ms.HERMES_MAGIC else "you"


def _info(symbol: str):
    m = ms.mt5
    if not symbol or not m.symbol_select(symbol, True):
        raise ValueError(f"Symbol {symbol} isn't offered by this broker. Check the exact name in Market Watch.")
    i, t = m.symbol_info(symbol), m.symbol_info_tick(symbol)
    if i is None or t is None or not (t.bid or t.ask):
        raise ValueError(f"No prices for {symbol} right now (market closed?).")
    return i, t


def _filling(i):
    m = ms.mt5
    return m.ORDER_FILLING_FOK if i.filling_mode & 1 else (m.ORDER_FILLING_IOC if i.filling_mode & 2 else m.ORDER_FILLING_RETURN)


def _volume(v: float, i) -> float:
    """Round to the symbol's lot step and keep it inside its min/max."""
    step = i.volume_step or 0.01
    v = round(round(float(v) / step) * step, 8)
    return round(min(max(v, i.volume_min), i.volume_max), 8)


def _result(res) -> dict:
    m = ms.mt5
    code = getattr(res, "retcode", None)
    ok = code in (m.TRADE_RETCODE_DONE, m.TRADE_RETCODE_PLACED, m.TRADE_RETCODE_DONE_PARTIAL)
    return {"ok": ok, "retcode": code, "comment": getattr(res, "comment", None) or str(m.last_error())}


def _check_levels(buy: bool, ref: float, sl: float, tp: float, i):
    """SL below / TP above the reference price for a buy (the other way for a sell), and at least the broker's stop
    level away from it. 0 means no SL / TP."""
    gap = (i.trade_stops_level or 0) * i.point
    side = "buy" if buy else "sell"
    if sl:
        if (buy and sl >= ref) or (not buy and sl <= ref):
            raise ValueError(f"The stop loss must be {'below' if buy else 'above'} {ref:.{i.digits}f} for a {side}.")
        if abs(ref - sl) < gap:
            raise ValueError(f"The stop loss must be at least {gap:.{i.digits}f} away (the broker's stop level).")
    if tp:
        if (buy and tp <= ref) or (not buy and tp >= ref):
            raise ValueError(f"The take profit must be {'above' if buy else 'below'} {ref:.{i.digits}f} for a {side}.")
        if abs(tp - ref) < gap:
            raise ValueError(f"The take profit must be at least {gap:.{i.digits}f} away (the broker's stop level).")


# ---------- quotes ----------
_seen: dict[str, tuple[int, float]] = {}      # symbol -> (tick time_msc, local time we first saw that tick)


def _server_offset(tick_time: int) -> float:
    """The broker's clock minus ours, rounded to the half hour (broker offsets are whole or half hours)."""
    return round((tick_time - time.time()) / 1800) * 1800


def tick_age(symbol: str, t) -> float:
    """Seconds since the symbol's last tick, measured on this PC's clock so the broker's time zone can't skew it: from
    the moment we first saw this tick. A tick seen for the first time is aged against the broker's clock."""
    msc = int(getattr(t, "time_msc", 0) or t.time * 1000)
    now = time.time()
    prev = _seen.get(symbol)
    if prev is None or prev[0] != msc:
        first = now - max(0.0, now + _server_offset(t.time) - t.time) if prev is None else now
        _seen[symbol] = prev = (msc, first)
    return round(now - prev[1], 1)


def _market_open(i, t, age: float) -> bool:
    """Closed when the symbol can't be traded, or when there's been no tick for 120 s on a weekend (broker's clock),
    or for 30 min at any time (holidays, maintenance)."""
    m = ms.mt5
    if i.trade_mode == m.SYMBOL_TRADE_MODE_DISABLED:
        return False
    weekend = datetime.fromtimestamp(t.time, timezone.utc).weekday() >= 5
    return not ((weekend and age > 120) or age > 1800)


def quote(symbol: str) -> dict:
    with ms._lock:
        ms._ensure()
        m = ms.mt5
        i, t = _info(symbol)
        term = m.terminal_info()
        return {"symbol": symbol, "bid": t.bid, "ask": t.ask, "digits": i.digits, "point": i.point,
                "volume_min": i.volume_min, "volume_max": i.volume_max, "volume_step": i.volume_step,
                "tick_value": i.trade_tick_value_loss or i.trade_tick_value, "tick_size": i.trade_tick_size,
                "contract_size": i.trade_contract_size, "stops_level": i.trade_stops_level,
                "trade_allowed": bool(term.trade_allowed) and i.trade_mode != m.SYMBOL_TRADE_MODE_DISABLED,
                "day_high": getattr(i, "bidhigh", None) or None, "day_low": getattr(i, "bidlow", None) or None,
                "spread": i.spread, "max_spread": (cap := float(load_settings().get("manual_max_spread", 0) or 0)),
                "spread_ok": not cap or i.spread <= cap, "time": int(t.time), "connected": bool(term.connected),
                "tick_age": (age := tick_age(symbol, t)), "market_open": _market_open(i, t, age)}


def quotes(symbols: list[str]) -> list[dict]:
    out = []
    with ms._lock:
        ms._ensure()
        for s in symbols:
            try:
                i, t = _info(s)
                out.append({"symbol": s, "bid": t.bid, "ask": t.ask, "digits": i.digits, "point": i.point,
                            "spread": i.spread})
            except ValueError as e:
                out.append({"symbol": s, "error": str(e)})
    return out


# ---------- orders ----------
def order(symbol: str, side: str, type: str = "market", volume: float = 0.0, price: float | None = None,
          sl: float | None = None, tp: float | None = None, deviation: int = 20, expiration: str = "gtc",
          confirm_real: bool = False, sl_points: float | None = None, tp_points: float | None = None,
          be_points: float | None = None, trail_points: float | None = None, ignore_spread: bool = False,
          note: str | None = None, tags: list | None = None) -> dict:
    """Place a market or pending order. With sl_points / tp_points (the tab's 80 / 160), SL and TP are that many
    points from the real fill price of a market order (set right after the fill) or from a pending order's price, so
    slippage can't shift them; the sl / tp prices are then only a first guess. Without points, sl / tp are used as
    given. be_points / trail_points override the settings' auto break-even / trailing stop for this order."""
    if side not in ("buy", "sell"):
        raise ValueError("side must be buy or sell")
    if type not in ("market", "limit", "stop"):
        raise ValueError("type must be market, limit or stop")
    sl, tp = float(sl or 0), float(tp or 0)
    with ms._lock:
        ms._ensure()
        m = ms.mt5
        acct = m.account_info()
        if acct.trade_mode != m.ACCOUNT_TRADE_MODE_DEMO and not confirm_real:
            raise ValueError("This is a real-money account. Confirm the order in the app first.")
        i, t = _info(symbol)
        buy = side == "buy"
        vol = _volume(volume or i.volume_min, i)
        gap = (i.trade_stops_level or 0) * i.point
        sgn = 1 if buy else -1
        slp, tpp = float(sl_points or 0), float(tp_points or 0)
        if slp < 0 or tpp < 0:
            raise ValueError("sl_points and tp_points can't be negative.")
        if any(v is not None and float(v) < 0 for v in (be_points, trail_points)):
            raise ValueError("be_points and trail_points can't be negative.")

        def anchor(ref: float) -> tuple[float, float]:
            """SL/TP that many points from ref (below/above for a buy); the given price where no points were sent."""
            return (round(ref - sgn * slp * i.point, i.digits) if slp else sl,
                    round(ref + sgn * tpp * i.point, i.digits) if tpp else tp)

        cap = float(load_settings().get("manual_max_spread", 0) or 0)
        if type == "market" and cap and i.spread > cap and not ignore_spread:
            raise ValueError(f"The spread is {i.spread} points right now (your limit is {cap:g}). Wait for it to "
                             "narrow, or send the order anyway.")
        if type == "market":
            px = t.ask if buy else t.bid
            sl, tp = anchor(px)                                       # first guess; re-anchored to the fill below
            _check_levels(buy, t.bid if buy else t.ask, sl, tp, i)   # MT5 checks a buy's SL/TP against the bid
            req = {"action": m.TRADE_ACTION_DEAL, "type": m.ORDER_TYPE_BUY if buy else m.ORDER_TYPE_SELL,
                   "price": px, "type_filling": _filling(i)}
        else:
            if not price or price <= 0:
                raise ValueError("A pending order needs a price.")
            px = round(float(price), i.digits)
            now = t.ask if buy else t.bid
            if type == "limit" and ((buy and px >= now) or (not buy and px <= now)):
                raise ValueError(f"A {side} limit must be {'below' if buy else 'above'} the current price {now}.")
            if type == "stop" and ((buy and px <= now) or (not buy and px >= now)):
                raise ValueError(f"A {side} stop must be {'above' if buy else 'below'} the current price {now}.")
            if abs(px - now) < gap:
                raise ValueError(f"A pending order must be at least {gap:.{i.digits}f} from the current price.")
            sl, tp = anchor(px)
            _check_levels(buy, px, sl, tp, i)
            otype = {("buy", "limit"): m.ORDER_TYPE_BUY_LIMIT, ("sell", "limit"): m.ORDER_TYPE_SELL_LIMIT,
                     ("buy", "stop"): m.ORDER_TYPE_BUY_STOP, ("sell", "stop"): m.ORDER_TYPE_SELL_STOP}[(side, type)]
            req = {"action": m.TRADE_ACTION_PENDING, "type": otype, "price": px, "type_filling": m.ORDER_FILLING_RETURN,
                   "type_time": m.ORDER_TIME_DAY if expiration == "today" else m.ORDER_TIME_GTC}
        req.update(symbol=symbol, volume=vol, sl=sl, tp=tp, deviation=int(deviation or 20), magic=MANUAL_MAGIC,
                   comment=COMMENT)
        res = m.order_send(req)
        out = _result(res)
        out.update(ticket=getattr(res, "order", None) or None, price=getattr(res, "price", None) or px, volume=vol,
                   sl=sl, tp=tp, anchored=bool(slp or tpp))
        if out["ok"] and type == "market" and (slp or tpp):
            out.update(_anchor_to_fill(res, symbol, buy, anchor, i))
    if out["ok"]:
        watch.on_new_order(out["ticket"], be_points, trail_points)
        if note or tags:
            set_note(out["ticket"], note, tags)
        out["auto"] = watch.rules_state()["tickets"].get(str(out["ticket"]))
    return out


def _anchor_to_fill(res, symbol: str, buy: bool, anchor, i) -> dict:
    """After a market fill: move SL/TP to sl_points / tp_points from the position's real open price. The order
    already went in with SL/TP from the quote, so the trade is never unprotected; if the move is refused (the price
    ran past a level already), those stay and `note` says why."""
    m = ms.mt5
    pos = None
    for _ in range(10):                                           # the position can show a moment after the deal
        tk = getattr(res, "order", 0)
        pos = (m.positions_get(ticket=tk) or [None])[0] if tk else None
        if pos is None and getattr(res, "deal", 0):
            d = m.history_deals_get(ticket=res.deal)
            if d:
                pos = (m.positions_get(ticket=d[0].position_id) or [None])[0]
        if pos is not None:
            break
        time.sleep(0.05)
    if pos is None:
        return {"note": "Filled, but the position wasn't found to re-anchor SL/TP; they stay at the quote's levels."}
    fill = pos.price_open
    sl, tp = anchor(fill)
    out = {"ticket": pos.ticket, "price": fill}
    if sl == pos.sl and tp == pos.tp:
        return {**out, "sl": sl, "tp": tp}
    t = m.symbol_info_tick(symbol)
    try:
        _check_levels(buy, t.bid if buy else t.ask, sl, tp, i)
    except ValueError as e:
        return {**out, "sl": pos.sl, "tp": pos.tp, "note": f"SL/TP kept at the quote's levels: {e}"}
    r = _result(m.order_send({"action": m.TRADE_ACTION_SLTP, "position": pos.ticket, "symbol": symbol,
                              "sl": sl, "tp": tp, "magic": pos.magic}))
    if not r["ok"]:
        return {**out, "sl": pos.sl, "tp": pos.tp,
                "note": f"SL/TP kept at the quote's levels: the broker refused the move ({r['comment']})."}
    return {**out, "sl": sl, "tp": tp}


def _close_one(p, volume: float | None = None) -> dict:
    """Close a position (or part of it). Call with the lock held."""
    m = ms.mt5
    i, t = _info(p.symbol)
    buy = p.type == m.POSITION_TYPE_BUY
    vol = p.volume if not volume else min(p.volume, _volume(volume, i))
    profit = round(p.profit * vol / p.volume, 2) if p.volume else p.profit   # before sending: the part being closed
    res = m.order_send({"action": m.TRADE_ACTION_DEAL, "position": p.ticket, "symbol": p.symbol, "volume": vol,
                        "type": m.ORDER_TYPE_SELL if buy else m.ORDER_TYPE_BUY, "price": t.bid if buy else t.ask,
                        "deviation": 30, "type_filling": _filling(i), "magic": p.magic, "comment": COMMENT})
    r = _result(res)
    r.update(ticket=p.ticket, volume=vol, profit=profit)
    return r


def close(tickets: list[int] | None = None, volume: float | None = None, filter: str = "all", owner: str = "any",
          symbol: str | None = None) -> dict:
    """Close chosen positions, or everything matching the filter (all / profit / loss / buys / sells) for an owner
    (any / you / bot / hermes) and symbol. A volume with one ticket closes part of it (the ½ button)."""
    from agent import ledger
    with ms._lock:
        ms._ensure()
        m = ms.mt5
        allpos = list(m.positions_get() or [])
    if tickets:
        want = {int(x) for x in tickets}
        chosen = [p for p in allpos if p.ticket in want]
        missing = want - {p.ticket for p in chosen}
    else:
        missing = set()
        chosen = [p for p in allpos
                  if (not symbol or p.symbol == symbol)
                  and (owner in ("any", None, "") or _owner(p.magic) == owner)
                  and {"all": True, "profit": p.profit > 0, "loss": p.profit < 0,
                       "buys": p.type == m.POSITION_TYPE_BUY, "sells": p.type == m.POSITION_TYPE_SELL}.get(filter, False)]
    bot = {t["ticket"]: t["id"] for t in ledger.open_trades()}
    for p in chosen:                                     # a bot trade closed here is scored as a manual close
        if p.ticket in bot:
            ledger.set_close_hint(bot[p.ticket], "manual (app)")
    closed, failed = [], [{"ticket": x, "comment": "already closed"} for x in sorted(missing)]
    with ms._lock:
        for p in chosen:
            try:
                r = _close_one(p, volume if volume and len(chosen) == 1 else None)
            except ValueError as e:
                failed.append({"ticket": p.ticket, "comment": str(e)})
                continue
            (closed if r["ok"] else failed).append({"ticket": p.ticket, "profit": r["profit"], "volume": r["volume"]}
                                                   if r["ok"] else {"ticket": p.ticket, "comment": r["comment"]})
    if closed and any(p.ticket in bot for p in chosen):
        time.sleep(0.3)
        try:
            ms.sync_bot_ledger(force=True)
        except Exception:                                # noqa: BLE001 - the next refresh records it anyway
            pass
    return {"closed": closed, "failed": failed}


def modify(ticket: int, sl: float | None = None, tp: float | None = None) -> dict:
    """Move a position's SL/TP (0 removes it). The BE button sends sl = the open price."""
    sl, tp = float(sl or 0), float(tp or 0)
    with ms._lock:
        ms._ensure()
        m = ms.mt5
        pos = m.positions_get(ticket=int(ticket))
        if not pos:
            raise ValueError(f"Position {ticket} is already closed.")
        p = pos[0]
        i, t = _info(p.symbol)
        buy = p.type == m.POSITION_TYPE_BUY
        _check_levels(buy, t.bid if buy else t.ask, sl, tp, i)
        res = m.order_send({"action": m.TRADE_ACTION_SLTP, "position": p.ticket, "symbol": p.symbol,
                            "sl": round(sl, i.digits), "tp": round(tp, i.digits), "magic": p.magic})
        return _result(res)


# ---------- pending orders ----------
def _order_type_name(m, typ) -> str:
    return {m.ORDER_TYPE_BUY_LIMIT: "buy_limit", m.ORDER_TYPE_SELL_LIMIT: "sell_limit",
            m.ORDER_TYPE_BUY_STOP: "buy_stop", m.ORDER_TYPE_SELL_STOP: "sell_stop",
            getattr(m, "ORDER_TYPE_BUY_STOP_LIMIT", -1): "buy_stop_limit",
            getattr(m, "ORDER_TYPE_SELL_STOP_LIMIT", -2): "sell_stop_limit"}.get(typ, str(typ))


def orders() -> list[dict]:
    with ms._lock:
        ms._ensure()
        m = ms.mt5
        return [{"ticket": o.ticket, "symbol": o.symbol, "type": _order_type_name(m, o.type),
                 "volume": o.volume_current, "price": o.price_open, "sl": o.sl, "tp": o.tp,
                 "time_setup": int(o.time_setup), "owner": _owner(o.magic)} for o in (m.orders_get() or [])]


def cancel(tickets: list[int] | None = None, all: bool = False) -> dict:
    with ms._lock:
        ms._ensure()
        m = ms.mt5
        live = {o.ticket: o for o in (m.orders_get() or [])}
        want = list(live) if all else [int(x) for x in (tickets or [])]
        cancelled, failed = [], []
        for tk in want:
            if tk not in live:
                failed.append({"ticket": tk, "comment": "no such pending order"})
                continue
            r = _result(m.order_send({"action": m.TRADE_ACTION_REMOVE, "order": tk}))
            (cancelled.append(tk) if r["ok"] else failed.append({"ticket": tk, "comment": r["comment"]}))
    return {"cancelled": cancelled, "failed": failed}


# ---------- trade notes: why you took a trade ----------
def _notes_path():
    from .settings import DATA
    return DATA / "trade_notes.json"


def _notes() -> dict:
    try:
        return json.loads(_notes_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def notes() -> dict:
    """All notes: {"<ticket>": {note, tags, time}}."""
    return _notes()


def set_note(ticket: int, note: str | None = None, tags: list | None = None) -> dict:
    """Write why you took a trade (and tags like "breakout", "revenge", "news"). Empty note and no tags removes it."""
    ticket = int(ticket)
    note = str(note or "").strip()[:1000]
    tags = sorted({str(t).strip().lower()[:30] for t in (tags or []) if str(t).strip()})[:10]
    with _notes_lock:
        data = _notes()
        if note or tags:
            data[str(ticket)] = {"note": note, "tags": tags, "time": int(time.time())}
        else:
            data.pop(str(ticket), None)
        p = _notes_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        tmp.replace(p)
    return {"ticket": ticket, "note": note, "tags": tags}


# ---------- history ----------
def _closed_levels(m, position_id: int) -> tuple:
    """SL/TP of a closed position: the last ones the watcher saw, else the ones it was opened with, else (0, 0)."""
    lv = watch.levels_for(position_id)
    if lv:
        return lv
    get = getattr(m, "history_orders_get", None)
    for o in (get(position=position_id) or []) if get else []:
        if o.sl or o.tp:
            return o.sl, o.tp
    return 0.0, 0.0


def history(days: float = 1) -> list[dict]:
    """Closed deals over the last `days` days, newest first, with the open price and who opened the trade."""
    now = datetime.now(timezone.utc)
    return history_range(now - timedelta(days=float(days)), now + timedelta(days=1))


def history_range(start: datetime, end: datetime) -> list[dict]:
    """Closed deals between start and end, newest first: open/close price and time, SL/TP, why it closed, owner."""
    with ms._lock:
        ms._ensure()
        m = ms.mt5
        deals = m.history_deals_get(start, end) or []
        outs = [d for d in deals if d.entry in (m.DEAL_ENTRY_OUT, m.DEAL_ENTRY_OUT_BY)]
        reasons = {m.DEAL_REASON_TP: "tp", m.DEAL_REASON_SL: "sl", getattr(m, "DEAL_REASON_SO", -1): "so"}
        rows, tn = [], _notes()
        for d in outs:
            ins = [x for x in (m.history_deals_get(position=d.position_id) or []) if x.entry == m.DEAL_ENTRY_IN]
            first = ins[0] if ins else None
            reason = reasons.get(d.reason, "manual")
            sl, tp = _closed_levels(m, d.position_id)
            if reason == "sl" and not sl:
                sl = d.price
            if reason == "tp" and not tp:
                tp = d.price
            rows.append({"time": int(d.time), "symbol": d.symbol, "ticket": d.position_id,
                         "side": "buy" if d.type == m.DEAL_TYPE_SELL else "sell",    # a sell deal closes a buy
                         "volume": d.volume, "open": first.price if first else None, "close": d.price,
                         "profit": round(d.profit + d.commission + d.swap + getattr(d, "fee", 0.0), 2),
                         "owner": _owner(first.magic if first else d.magic),
                         "open_time": int(first.time) if first else None, "sl": sl, "tp": tp, "reason": reason,
                         "duration_s": int(d.time - first.time) if first else None,
                         "note": tn.get(str(d.position_id), {}).get("note", ""),
                         "tags": tn.get(str(d.position_id), {}).get("tags", [])})
    rows.sort(key=lambda r: r["time"], reverse=True)
    return rows
