"""Thin MT5 layer for the app UI and the local assistant's tools. Falls back to 'offline' when MT5 is unavailable."""
import threading
from pathlib import Path

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

from .settings import load

_lock = threading.Lock()   # the MetaTrader5 package isn't thread-safe


class MT5Unavailable(RuntimeError):
    pass


def _ensure():
    if mt5 is None:
        raise MT5Unavailable("MetaTrader5 package not installed. It only works on Windows (`pip install MetaTrader5`).")
    if mt5.terminal_info() is None:
        path = load().get("terminal_path") or None
        ok = mt5.initialize(path=path) if path else mt5.initialize()
        if not ok:
            raise MT5Unavailable(f"Can't reach the MT5 terminal ({mt5.last_error()[1]}). Open MetaTrader 5 and log in, then retry.")


def account() -> dict:
    with _lock:
        _ensure()
        a = mt5.account_info()
        t = mt5.terminal_info()
        return {"login": a.login, "server": a.server, "name": a.name, "currency": a.currency,
                "balance": a.balance, "equity": a.equity, "margin": a.margin, "margin_free": a.margin_free,
                "margin_level": a.margin_level, "leverage": a.leverage, "profit": a.profit,
                "demo": a.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO,
                "algo_trading": bool(t.trade_allowed), "connected": bool(t.connected), "ping_ms": round(t.ping_last / 1000, 1)}


def positions() -> list[dict]:
    with _lock:
        _ensure()
        return [{"ticket": p.ticket, "symbol": p.symbol, "side": "buy" if p.type == 0 else "sell",
                 "volume": p.volume, "open": p.price_open, "current": p.price_current, "sl": p.sl, "tp": p.tp,
                 "profit": p.profit, "magic": p.magic, "time": p.time} for p in (mt5.positions_get() or [])]


def m1_bars(symbol: str, count: int = 300) -> dict:
    with _lock:
        _ensure()
        if not mt5.symbol_select(symbol, True):
            raise ValueError(f"Symbol {symbol} isn't offered by this broker. Check the exact name in Market Watch (e.g. XAUUSD.m).")
        r = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, count)
        info = mt5.symbol_info(symbol)
        tick = mt5.symbol_info_tick(symbol)
    bars = [{"time": int(x["time"]), "open": float(x["open"]), "high": float(x["high"]),
             "low": float(x["low"]), "close": float(x["close"]), "volume": int(x["tick_volume"]),
             "spread": int(x["spread"])} for x in (r if r is not None else [])]
    return {"symbol": symbol, "timeframe": "M1", "digits": info.digits, "point": info.point,
            "bid": tick.bid, "ask": tick.ask, "bars": bars}


def symbol_spec(symbol: str) -> dict:
    with _lock:
        _ensure()
        mt5.symbol_select(symbol, True)
        i = mt5.symbol_info(symbol)
        if i is None:
            raise ValueError(f"Unknown symbol {symbol}")
        return {"point": i.point, "digits": i.digits, "tick_size": i.trade_tick_size,
                "tick_value": i.trade_tick_value_loss or i.trade_tick_value, "contract_size": i.trade_contract_size,
                "volume_min": i.volume_min, "volume_step": i.volume_step, "volume_max": i.volume_max,
                "stops_level": i.trade_stops_level, "spread": i.spread}


def close_position(ticket: int) -> dict:
    with _lock:
        _ensure()
        p = mt5.positions_get(ticket=ticket)
        if not p:
            raise ValueError(f"Position {ticket} is already closed.")
        p = p[0]
        i, t = mt5.symbol_info(p.symbol), mt5.symbol_info_tick(p.symbol)
        buy = p.type == mt5.POSITION_TYPE_BUY
        filling = mt5.ORDER_FILLING_FOK if i.filling_mode & 1 else (mt5.ORDER_FILLING_IOC if i.filling_mode & 2 else mt5.ORDER_FILLING_RETURN)
        res = mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "position": p.ticket, "symbol": p.symbol,
                              "volume": p.volume, "type": mt5.ORDER_TYPE_SELL if buy else mt5.ORDER_TYPE_BUY,
                              "price": t.bid if buy else t.ask, "deviation": 30, "type_filling": filling})
        return {"retcode": getattr(res, "retcode", None), "comment": getattr(res, "comment", str(mt5.last_error()))}


def close_all(magic: int | None = None) -> list[dict]:
    out = []
    for p in positions():
        if magic is None or p["magic"] == magic:
            out.append({"ticket": p["ticket"], **close_position(p["ticket"])})
    return out


def lots_for_risk(symbol: str, entry: float, stop: float, risk_pct: float) -> dict:
    spec = symbol_spec(symbol)
    eq = account()["equity"]
    loss_per_lot = abs(entry - stop) / spec["tick_size"] * spec["tick_value"]
    raw = eq * risk_pct / 100 / loss_per_lot if loss_per_lot else 0
    lots = int(raw / spec["volume_step"] + 1e-9) * spec["volume_step"]
    lots = 0.0 if lots < spec["volume_min"] else min(lots, spec["volume_max"])
    return {"equity": eq, "lots": round(lots, 8), "loss_per_lot": round(loss_per_lot, 2), "risk_money": round(loss_per_lot * lots, 2)}


def model_exists(symbol: str) -> bool:
    return (Path(__file__).resolve().parent.parent / "models" / f"{symbol}_M1.json").exists()
