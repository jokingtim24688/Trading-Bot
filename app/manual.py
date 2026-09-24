"""Manual trading for the Manual tab: what the MT5 mobile app does.

Quotes, one-click market orders, pending orders (buy/sell limit and stop), SL/TP edits, full, partial and bulk closes
(all / profitable / losing / buys / sells, by owner and symbol), the pending-order list and cancel, and today's closed
deals. Orders placed here use magic 0, so they show as "you" and the bot never touches or counts them. A real-money
account is refused unless the request carries confirm_real (the tab sends it only after you confirm).
"""
import time
from datetime import datetime, timedelta, timezone

from . import mt5_service as ms

MANUAL_MAGIC = 0
COMMENT = "manual (app)"
OWNERS = {"bot": ms.BOT_MAGIC, "hermes": ms.HERMES_MAGIC}


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
                "spread": i.spread, "time": int(t.time)}


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
          confirm_real: bool = False) -> dict:
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
        if type == "market":
            px = t.ask if buy else t.bid
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
            _check_levels(buy, px, sl, tp, i)
            otype = {("buy", "limit"): m.ORDER_TYPE_BUY_LIMIT, ("sell", "limit"): m.ORDER_TYPE_SELL_LIMIT,
                     ("buy", "stop"): m.ORDER_TYPE_BUY_STOP, ("sell", "stop"): m.ORDER_TYPE_SELL_STOP}[(side, type)]
            req = {"action": m.TRADE_ACTION_PENDING, "type": otype, "price": px, "type_filling": m.ORDER_FILLING_RETURN,
                   "type_time": m.ORDER_TIME_DAY if expiration == "today" else m.ORDER_TIME_GTC}
        req.update(symbol=symbol, volume=vol, sl=sl, tp=tp, deviation=int(deviation or 20), magic=MANUAL_MAGIC,
                   comment=COMMENT)
        res = m.order_send(req)
        out = _result(res)
        out.update(ticket=getattr(res, "order", None) or None, price=getattr(res, "price", None) or px, volume=vol)
        return out


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
            ms.sync_bot_ledger()
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


# ---------- history ----------
def history(days: float = 1) -> list[dict]:
    """Closed deals over the last `days` days, newest first, with the open price and who opened the trade."""
    with ms._lock:
        ms._ensure()
        m = ms.mt5
        now = datetime.now(timezone.utc)
        deals = m.history_deals_get(now - timedelta(days=float(days)), now + timedelta(days=1)) or []
        outs = [d for d in deals if d.entry in (m.DEAL_ENTRY_OUT, m.DEAL_ENTRY_OUT_BY)]
        rows = []
        for d in outs:
            ins = [x for x in (m.history_deals_get(position=d.position_id) or []) if x.entry == m.DEAL_ENTRY_IN]
            first = ins[0] if ins else None
            rows.append({"time": int(d.time), "symbol": d.symbol, "ticket": d.position_id,
                         "side": "buy" if d.type == m.DEAL_TYPE_SELL else "sell",    # a sell deal closes a buy
                         "volume": d.volume, "open": first.price if first else None, "close": d.price,
                         "profit": round(d.profit + d.commission + d.swap + getattr(d, "fee", 0.0), 2),
                         "owner": _owner(first.magic if first else d.magic)})
    rows.sort(key=lambda r: r["time"], reverse=True)
    return rows
