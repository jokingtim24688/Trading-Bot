"""A small stand-in for the MetaTrader5 package, for the tests (tests/conftest.py puts it first on the path).

One demo account, one symbol (XAUUSD: bid 2650.00 / ask 2650.25, point 0.01, stops level 50, spread 25), hedging
positions, pending orders and deals. `reset()` puts it back to the start; `trigger(ticket, reason, price)` closes a
position the way the broker does on a stop loss or take profit.
"""
import time as _t
from types import SimpleNamespace as NS
ACCOUNT_TRADE_MODE_DEMO, ACCOUNT_TRADE_MODE_REAL = 0, 2
ACCOUNT_MARGIN_MODE_RETAIL_HEDGING = 2
SYMBOL_TRADE_MODE_DISABLED, SYMBOL_TRADE_MODE_FULL = 0, 4
ORDER_TYPE_BUY, ORDER_TYPE_SELL, ORDER_TYPE_BUY_LIMIT, ORDER_TYPE_SELL_LIMIT, ORDER_TYPE_BUY_STOP, ORDER_TYPE_SELL_STOP = range(6)
POSITION_TYPE_BUY, POSITION_TYPE_SELL = 0, 1
TRADE_ACTION_DEAL, TRADE_ACTION_PENDING, TRADE_ACTION_SLTP, TRADE_ACTION_REMOVE = 1, 5, 6, 8
ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 1, 2
ORDER_TIME_GTC, ORDER_TIME_DAY = 0, 1
TRADE_RETCODE_PLACED, TRADE_RETCODE_DONE, TRADE_RETCODE_DONE_PARTIAL, TRADE_RETCODE_INVALID_STOPS = 10008, 10009, 10010, 10016
DEAL_ENTRY_IN, DEAL_ENTRY_OUT, DEAL_ENTRY_INOUT, DEAL_ENTRY_OUT_BY = 0, 1, 2, 3
DEAL_TYPE_BUY, DEAL_TYPE_SELL = 0, 1
DEAL_REASON_CLIENT, DEAL_REASON_EXPERT, DEAL_REASON_SL, DEAL_REASON_TP = 0, 3, 4, 5
TIMEFRAME_M1 = 1
S = {"trade_mode": ACCOUNT_TRADE_MODE_DEMO, "bid": 2650.00, "ask": 2650.25, "next": 1000, "connected": True}
POS, ORD, DEALS, SENT = {}, {}, [], []


def reset():
    S.update(trade_mode=ACCOUNT_TRADE_MODE_DEMO, bid=2650.00, ask=2650.25, next=1000, connected=True)
    POS.clear(); ORD.clear(); DEALS.clear(); SENT.clear()
def initialize(*a, **k): return True
def terminal_info(): return NS(trade_allowed=True, connected=S["connected"], ping_last=20000)
def last_error(): return (1, "ok")
def account_info(): return NS(login=1, server="Demo", name="t", currency="USD", balance=10000, equity=10000, margin=0,
                              margin_free=10000, margin_level=0, leverage=100, profit=0, trade_mode=S["trade_mode"],
                              margin_mode=ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
def symbol_select(s, on=True): return s == "XAUUSD"
def symbol_info(s):
    return None if s != "XAUUSD" else NS(digits=2, point=0.01, volume_min=0.01, volume_max=100.0, volume_step=0.01,
        trade_tick_value=1.0, trade_tick_value_loss=1.0, trade_tick_size=0.01, trade_contract_size=100.0,
        trade_stops_level=50, trade_mode=SYMBOL_TRADE_MODE_FULL, filling_mode=1, bidhigh=2660.0, bidlow=2640.0, spread=25)
def symbol_info_tick(s): return None if s != "XAUUSD" else NS(bid=S["bid"], ask=S["ask"], time=int(_t.time()))
def _profit(p):
    px = S["bid"] if p.type == 0 else S["ask"]
    return round(((px - p.price_open) if p.type == 0 else (p.price_open - px)) * 100 * p.volume, 2)
def positions_get(ticket=None, symbol=None):
    out = [p for p in POS.values() if (ticket is None or p.ticket == ticket)]
    for p in out: p.profit = _profit(p); p.price_current = S["bid"] if p.type == 0 else S["ask"]
    return tuple(out)
def orders_get(): return tuple(ORD.values())
def _tk():
    S["next"] += 1; return S["next"]
def order_send(r):
    SENT.append(dict(r)); a = r["action"]
    if a == TRADE_ACTION_DEAL and r.get("position"):
        p = POS.get(r["position"])
        if not p: return NS(retcode=10036, comment="position closed", order=0, price=0)
        vol = r["volume"]; pr = _profit(p) * vol / p.volume
        DEALS.append(NS(ticket=_tk(), time=int(_t.time()), symbol=p.symbol, position_id=p.ticket, type=DEAL_TYPE_SELL if p.type == 0 else DEAL_TYPE_BUY,
                        entry=DEAL_ENTRY_OUT, volume=vol, price=r["price"], profit=pr, commission=0.0, swap=0.0, fee=0.0,
                        magic=r.get("magic", 0), reason=DEAL_REASON_EXPERT))
        p.volume = round(p.volume - vol, 8)
        if p.volume <= 1e-9: del POS[p.ticket]
        return NS(retcode=TRADE_RETCODE_DONE, comment="done", order=_tk(), price=r["price"])
    if a == TRADE_ACTION_DEAL:
        tk = _tk(); t = 0 if r["type"] == ORDER_TYPE_BUY else 1
        POS[tk] = NS(ticket=tk, symbol=r["symbol"], type=t, volume=r["volume"], price_open=r["price"], sl=r["sl"], tp=r["tp"],
                     magic=r.get("magic", 0), time=int(_t.time()), profit=0.0, price_current=r["price"])
        DEALS.append(NS(ticket=_tk(), time=int(_t.time()), symbol=r["symbol"], position_id=tk, type=DEAL_TYPE_BUY if t == 0 else DEAL_TYPE_SELL,
                        entry=DEAL_ENTRY_IN, volume=r["volume"], price=r["price"], profit=0.0, commission=0.0, swap=0.0, fee=0.0,
                        magic=r.get("magic", 0), reason=DEAL_REASON_EXPERT))
        return NS(retcode=TRADE_RETCODE_DONE, comment="done", order=tk, price=r["price"])
    if a == TRADE_ACTION_PENDING:
        tk = _tk(); ORD[tk] = NS(ticket=tk, symbol=r["symbol"], type=r["type"], volume_current=r["volume"], price_open=r["price"],
                                 sl=r["sl"], tp=r["tp"], time_setup=int(_t.time()), magic=r.get("magic", 0))
        return NS(retcode=TRADE_RETCODE_PLACED, comment="placed", order=tk, price=r["price"])
    if a == TRADE_ACTION_SLTP:
        p = POS[r["position"]]; p.sl, p.tp = r["sl"], r["tp"]; return NS(retcode=TRADE_RETCODE_DONE, comment="done", order=0, price=0)
    if a == TRADE_ACTION_REMOVE:
        ORD.pop(r["order"], None); return NS(retcode=TRADE_RETCODE_DONE, comment="done", order=r["order"], price=0)
def history_deals_get(*a, position=None):
    return tuple(d for d in DEALS if position is None or d.position_id == position)
def copy_rates_from_pos(*a): return None
def order_calc_margin(*a): return 1000.0
DEAL_REASON_SO, DEAL_REASON_MOBILE, DEAL_REASON_WEB, DEAL_REASON_ROLLOVER, DEAL_REASON_VMARGIN, DEAL_REASON_SPLIT = 6, 1, 2, 7, 8, 9

def history_orders_get(*a, position=None): return ()
def trigger(ticket, reason, price):
    """Close a position the way the broker does on a SL/TP hit."""
    p = POS.pop(ticket); pr = round(((price - p.price_open) if p.type == 0 else (p.price_open - price)) * 100 * p.volume, 2)
    DEALS.append(NS(ticket=_tk(), time=int(_t.time()), symbol=p.symbol, position_id=p.ticket, type=DEAL_TYPE_SELL if p.type == 0 else DEAL_TYPE_BUY,
                    entry=DEAL_ENTRY_OUT, volume=p.volume, price=price, profit=pr, commission=0.0, swap=0.0, fee=0.0,
                    magic=p.magic, reason=reason))
