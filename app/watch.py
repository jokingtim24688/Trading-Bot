"""Background watcher, once a second, inside the app (so it works with the Manual tab closed):

- Trailing stop and auto break-even rules per position (Manual tab). Break-even: once a trade is `be_points` up, its
  stop moves to entry + 2 points. Trailing: the stop follows the price at `trail_points`, only ever tightening. New
  manual orders get the defaults from settings (`manual_be_points`, `manual_trail_points`; 0 = off). Rules live in
  data/manual_auto.json, so they survive an app restart.
- The event feed for alerts (`GET /api/events`): trades opened, TP / SL hits and other closes for every owner (you,
  the bot, Hermes), read from MT5's deal reasons, plus the watcher's own "be" / "trail" stop moves. The last 500 are
  kept in memory.
- The last SL/TP each position had before it closed (data/closed_levels.json), for History replay: MT5 doesn't keep a
  closed position's final SL/TP.
"""
import json
import threading
import time
from collections import deque

from . import mt5_service as ms
from . import notify, telegram
from .settings import DATA, load

RULES_FILE = DATA / "manual_auto.json"
LEVELS_FILE = DATA / "closed_levels.json"
BE_LOCK_POINTS = 2              # break-even puts the stop this many points past entry, so a BE exit isn't a small loss
MAX_EVENTS = 500
MAX_LEVELS = 5000

_state_lock = threading.RLock()
_events: deque = deque(maxlen=MAX_EVENTS)
_next_id = 1
_rules: dict[str, dict] | None = None             # "<ticket>" -> {be_points, trail_points, be_done}
_closed_levels: dict[str, list] | None = None     # "<ticket>" -> [sl, tp] when it closed
_known: dict[int, dict] | None = None             # open positions last second: ticket -> {volume, sl, tp, ...}
_seen_deals: set[int] = set()
_thread: threading.Thread | None = None


def _read(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path, obj):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj), encoding="utf-8")
    tmp.replace(path)


def _rules_map() -> dict:
    global _rules
    if _rules is None:
        _rules = _read(RULES_FILE, {})
    return _rules


def _levels_map() -> dict:
    global _closed_levels
    if _closed_levels is None:
        _closed_levels = _read(LEVELS_FILE, {})
    return _closed_levels


def _owner(magic: int) -> str:
    return "bot" if magic == ms.BOT_MAGIC else "hermes" if magic == ms.HERMES_MAGIC else "you"


# ---------- events ----------
def add_event(kind: str, **fields) -> dict:
    global _next_id
    with _state_lock:
        ev = {"id": _next_id, "time": int(time.time()), "kind": kind, "ticket": None, "symbol": None, "side": None,
              "volume": None, "price": None, "profit": None, "owner": None, **fields}
        _next_id += 1
        _events.append(ev)
    if kind in ("tp", "sl"):
        notify.for_event(ev)                           # Windows pop-up, so you see it with the app minimised
    telegram.for_event(ev)                             # your phone, if Telegram alerts are on
    return ev


def events(since: int | None = None) -> dict:
    """Events newer than `since`. Without `since` (or with an id from before an app restart) only `last_id` comes
    back, so a first poll doesn't replay old alerts."""
    with _state_lock:
        last = _next_id - 1
        if since is None or since > last:
            return {"last_id": last, "events": []}
        return {"last_id": last, "events": [e for e in _events if e["id"] > since]}


# ---------- trailing stop / break-even rules ----------
def defaults() -> dict:
    s = load()
    return {"be_points": float(s.get("manual_be_points", 0) or 0),
            "trail_points": float(s.get("manual_trail_points", 0) or 0)}


def _clean(v) -> float:
    v = float(v or 0)
    if v < 0:
        raise ValueError("be_points and trail_points can't be negative.")
    return v


def on_new_order(ticket: int | None, be_points=None, trail_points=None):
    """Give a new manual order its rule: the settings' defaults unless the order says otherwise. A pending order's
    ticket becomes its position's ticket when it fills, so the rule waits for it."""
    if not ticket:
        return
    d = defaults()
    be = d["be_points"] if be_points is None else _clean(be_points)
    tr = d["trail_points"] if trail_points is None else _clean(trail_points)
    if be or tr:
        with _state_lock:
            _rules_map()[str(int(ticket))] = {"be_points": be, "trail_points": tr, "be_done": False}
            _write(RULES_FILE, _rules_map())


def set_rule(ticket: int, be_points=None, trail_points=None) -> dict:
    """Set, change or clear (both 0) the rule for one open position or pending order. Missing values keep the
    position's current rule."""
    ticket = int(ticket)
    with ms._lock:
        ms._ensure()
        m = ms.mt5
        p = (m.positions_get(ticket=ticket) or [None])[0]
        o = None if p else next((x for x in (m.orders_get() or []) if x.ticket == ticket), None)
    if p is None and o is None:
        raise ValueError(f"Position {ticket} is already closed.")
    magic = (p or o).magic
    with _state_lock:
        rules = _rules_map()
        cur = rules.get(str(ticket), {"be_points": 0.0, "trail_points": 0.0, "be_done": False})
        be = cur["be_points"] if be_points is None else _clean(be_points)
        tr = cur["trail_points"] if trail_points is None else _clean(trail_points)
        if be or tr:
            rules[str(ticket)] = {"be_points": be, "trail_points": tr,
                                  "be_done": cur.get("be_done", False) and be == cur["be_points"]}
        else:
            rules.pop(str(ticket), None)
        _write(RULES_FILE, rules)
    comment = ""
    if magic == ms.BOT_MAGIC:
        comment = "This is the bot's trade: the bot may also move or close it."
    elif magic == ms.HERMES_MAGIC:
        comment = "This is Hermes's trade."
    return {"ok": True, "ticket": ticket, "be_points": be, "trail_points": tr, "comment": comment}


def rules_state() -> dict:
    with _state_lock:
        known = _known or {}
        return {"defaults": defaults(),
                "tickets": {k: {**v, "sl": (known.get(int(k)) or {}).get("sl")} for k, v in _rules_map().items()}}


def _better(buy: bool, new: float, cur: float) -> bool:
    return not cur or (new > cur if buy else new < cur)


def _apply_rule(m, p, rule: dict) -> bool:
    """Move the stop for break-even / trailing when due. Returns True if the rule changed (be_done)."""
    i, t = m.symbol_info(p.symbol), m.symbol_info_tick(p.symbol)
    if i is None or t is None:
        return False
    buy = p.type == m.POSITION_TYPE_BUY
    sgn = 1 if buy else -1
    px = t.bid if buy else t.ask                       # the price the trade would close at
    if not px:
        return False
    gain = sgn * (px - p.price_open) / i.point
    targets = []
    changed = False
    if rule["be_points"] and not rule.get("be_done") and gain >= rule["be_points"]:
        be = round(p.price_open + sgn * BE_LOCK_POINTS * i.point, i.digits)
        if _better(buy, be, p.sl):
            targets.append((be, "be"))
        else:                                          # the stop is already past break-even
            rule["be_done"] = changed = True
    if rule["trail_points"]:
        tr = round(px - sgn * rule["trail_points"] * i.point, i.digits)
        if _better(buy, tr, p.sl):
            targets.append((tr, "trail"))
    if not targets:
        return changed
    new, kind = max(targets, key=lambda x: sgn * x[0])  # the tighter of the two
    gap = (i.trade_stops_level or 0) * i.point
    if sgn * (px - new) < max(gap, i.point):            # too close to the price for the broker
        return changed
    r = m.order_send({"action": m.TRADE_ACTION_SLTP, "position": p.ticket, "symbol": p.symbol,
                      "sl": new, "tp": p.tp, "magic": p.magic})
    if getattr(r, "retcode", None) == m.TRADE_RETCODE_DONE:
        add_event(kind, ticket=p.ticket, symbol=p.symbol, side="buy" if buy else "sell", volume=p.volume, price=new,
                  profit=round(p.profit, 2), owner=_owner(p.magic))
        if kind == "be" or (rule["be_points"] and sgn * (new - p.price_open) >= BE_LOCK_POINTS * i.point):
            rule["be_done"] = True
        return True
    return changed


# ---------- the loop ----------
def _snapshot(p) -> dict:
    return {"volume": p.volume, "sl": p.sl, "tp": p.tp, "symbol": p.symbol, "magic": p.magic,
            "side": "buy" if p.type == 0 else "sell"}


def _close_events(m, ticket: int, info: dict):
    """TP / SL / close events for the position's closing deals we haven't reported yet."""
    reasons = {m.DEAL_REASON_TP: "tp", m.DEAL_REASON_SL: "sl"}
    for d in m.history_deals_get(position=ticket) or []:
        dt = getattr(d, "ticket", None)
        if d.entry not in (m.DEAL_ENTRY_OUT, m.DEAL_ENTRY_OUT_BY) or dt in _seen_deals:
            continue
        _seen_deals.add(dt)
        add_event(reasons.get(d.reason, "close"), ticket=ticket, symbol=d.symbol, side=info["side"], volume=d.volume,
                  price=d.price, profit=round(d.profit + d.commission + d.swap + getattr(d, "fee", 0.0), 2),
                  owner=_owner(info["magic"]))


def tick():
    """One pass: events for opens and closes since the last pass, then the stop rules."""
    global _known
    with ms._lock:
        ms._ensure()
        m = ms.mt5
        now = {p.ticket: p for p in (m.positions_get() or [])}
        with _state_lock:
            first = _known is None
            known = _known or {}
            if not first:
                for tk, p in now.items():
                    if tk not in known:
                        add_event("open", ticket=tk, symbol=p.symbol, side="buy" if p.type == 0 else "sell",
                                  volume=p.volume, price=p.price_open, profit=None, owner=_owner(p.magic))
                gone = False
                for tk, info in known.items():
                    if tk not in now:
                        _close_events(m, tk, info)
                        _levels_map()[str(tk)] = [info["sl"], info["tp"]]
                        gone = True
                        if info["magic"] == ms.BOT_MAGIC:
                            ms.mark_ledger_stale()            # the bot's trade closed: the next sync records it
                    elif now[tk].volume < info["volume"] - 1e-9:     # partial close
                        _close_events(m, tk, info)
                if gone:
                    lv = _levels_map()
                    for k in list(lv)[:-MAX_LEVELS]:
                        del lv[k]
                    _write(LEVELS_FILE, lv)
            rules = _rules_map()
            if rules:
                pending = {o.ticket for o in (m.orders_get() or [])}
                dirty = False
                for k in list(rules):
                    tk = int(k)
                    if tk in now:
                        dirty |= _apply_rule(m, now[tk], rules[k])
                    elif tk not in pending:                   # closed or cancelled: forget it
                        del rules[k]
                        dirty = True
                if dirty:
                    _write(RULES_FILE, rules)
            _known = {tk: _snapshot(p) for tk, p in now.items()}


def levels_for(ticket: int) -> tuple | None:
    """The SL/TP a position had just before it closed (None if the watcher didn't see it)."""
    with _state_lock:
        v = _levels_map().get(str(int(ticket)))
    return tuple(v) if v else None


def _loop():
    while True:
        try:
            tick()
            time.sleep(1)
        except ms.MT5Unavailable:
            time.sleep(10)                             # MT5 closed / not on Windows: check again later
        except Exception as e:                         # noqa: BLE001 - the watcher must keep running
            print(f"(watcher: {type(e).__name__}: {e})", flush=True)
            time.sleep(5)


def start():
    global _thread
    if _thread is None or not _thread.is_alive():
        _thread = threading.Thread(target=_loop, name="watch", daemon=True)
        _thread.start()
