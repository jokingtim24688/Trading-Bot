"""MT5 MCP server: lets Claude read M1 data and manage trades in a running MetaTrader 5 terminal.

Windows only (the MetaTrader5 package talks to a local terminal64.exe).
Safety: order tools refuse real-money accounts unless MT5_MCP_ALLOW_REAL=1, and refuse any order whose
stop-loss risk exceeds MT5_MCP_MAX_RISK_PCT (default 1.0) of equity. Every order requires a stop loss.

Run:    python mcp_server/mt5_mcp.py            (stdio, for Claude Desktop/Code)
        python mcp_server/mt5_mcp.py --http     (http://127.0.0.1:8765/mcp, for Hermes Agent)
Claude Desktop / Claude Code config: see mcp_server/README.md
"""
import json
import os
from typing import Literal

import MetaTrader5 as mt5
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

TF = mt5.TIMEFRAME_M1   # locked to M1
ALLOW_REAL = os.getenv("MT5_MCP_ALLOW_REAL") == "1"
MAX_RISK_PCT = float(os.getenv("MT5_MCP_MAX_RISK_PCT", "1.0"))
MAGIC = int(os.getenv("MT5_MCP_MAGIC", "260924"))
CHAR_LIMIT = 25_000

mcp = FastMCP("mt5_mcp")


def _ensure() -> None:
    if mt5.terminal_info() is None:
        path = os.getenv("MT5_TERMINAL_PATH")
        ok = mt5.initialize(path=path) if path else mt5.initialize()
        if not ok:
            raise RuntimeError(f"Could not connect to MT5 terminal: {mt5.last_error()}. Is terminal64.exe running and logged in?")


def _sym(symbol: str):
    _ensure()
    if not mt5.symbol_select(symbol, True):
        raise ValueError(f"Symbol '{symbol}' not found. Use mt5_search_symbols to find the broker's exact name (e.g. XAUUSD.m, AAPL.US).")
    return mt5.symbol_info(symbol)


def _out(data) -> str:
    s = json.dumps(data, default=str, indent=1)
    return s if len(s) <= CHAR_LIMIT else s[:CHAR_LIMIT] + "\n... truncated; request fewer rows"


def _filling(info) -> int:
    if info.filling_mode & 1:
        return mt5.ORDER_FILLING_FOK
    if info.filling_mode & 2:
        return mt5.ORDER_FILLING_IOC
    return mt5.ORDER_FILLING_RETURN


def _is_demo() -> bool:
    return mt5.account_info().trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO


# ---------------- read-only tools ----------------

@mcp.tool(name="mt5_account_info", annotations={"readOnlyHint": True, "openWorldHint": True})
def mt5_account_info() -> str:
    """Account balance, equity, margin, free margin, leverage, currency, and whether it is demo or real."""
    _ensure()
    a = mt5.account_info()
    return _out({"login": a.login, "server": a.server, "demo": _is_demo(), "currency": a.currency,
                 "balance": a.balance, "equity": a.equity, "margin": a.margin, "margin_free": a.margin_free,
                 "margin_level": a.margin_level, "leverage": a.leverage,
                 "margin_mode": "hedging" if a.margin_mode == mt5.ACCOUNT_MARGIN_MODE_RETAIL_HEDGING else "netting"})


class SearchInput(BaseModel):
    pattern: str = Field(..., description="Wildcard pattern, e.g. '*XAU*', '*.US', '*AAPL*'", min_length=1)
    limit: int = Field(50, ge=1, le=500)


@mcp.tool(name="mt5_search_symbols", annotations={"readOnlyHint": True})
def mt5_search_symbols(params: SearchInput) -> str:
    """Find tradable symbol names on this broker (gold, stocks, indices use broker-specific names)."""
    _ensure()
    syms = mt5.symbols_get(params.pattern) or []
    return _out([{"name": s.name, "path": s.path, "description": s.description} for s in syms[: params.limit]])


class SymbolInput(BaseModel):
    symbol: str = Field(..., description="Exact broker symbol, e.g. 'XAUUSD', 'AAPL.US'")


@mcp.tool(name="mt5_symbol_spec", annotations={"readOnlyHint": True})
def mt5_symbol_spec(params: SymbolInput) -> str:
    """Contract specification: digits, point, contract size, tick size/value, volume limits, stops level, current spread, sessions-related flags."""
    i = _sym(params.symbol)
    return _out({k: getattr(i, k) for k in (
        "name", "description", "digits", "point", "spread", "trade_contract_size", "trade_tick_size",
        "trade_tick_value", "trade_tick_value_loss", "volume_min", "volume_step", "volume_max",
        "trade_stops_level", "trade_freeze_level", "swap_long", "swap_short", "margin_initial",
        "currency_base", "currency_profit", "trade_mode", "filling_mode")})


@mcp.tool(name="mt5_get_tick", annotations={"readOnlyHint": True})
def mt5_get_tick(params: SymbolInput) -> str:
    """Latest bid/ask/spread for a symbol."""
    i = _sym(params.symbol)
    t = mt5.symbol_info_tick(params.symbol)
    return _out({"bid": t.bid, "ask": t.ask, "spread_points": round((t.ask - t.bid) / i.point), "time_server": t.time})


class BarsInput(BaseModel):
    symbol: str = Field(..., description="Exact broker symbol")
    count: int = Field(120, ge=1, le=5000, description="Number of closed M1 bars (most recent last)")


@mcp.tool(name="mt5_get_m1_bars", annotations={"readOnlyHint": True})
def mt5_get_m1_bars(params: BarsInput) -> str:
    """Closed M1 (1-minute) OHLC bars with tick volume and spread. The timeframe is fixed to M1."""
    _sym(params.symbol)
    r = mt5.copy_rates_from_pos(params.symbol, TF, 1, params.count)
    if r is None:
        raise RuntimeError(f"No data: {mt5.last_error()}")
    rows = [{"time_server": int(x["time"]), "o": float(x["open"]), "h": float(x["high"]), "l": float(x["low"]),
             "c": float(x["close"]), "tv": int(x["tick_volume"]), "spr": int(x["spread"])} for x in r]
    return _out({"symbol": params.symbol, "timeframe": "M1", "bars": rows})


@mcp.tool(name="mt5_list_positions", annotations={"readOnlyHint": True})
def mt5_list_positions() -> str:
    """Open positions and pending orders."""
    _ensure()
    pos = [{"ticket": p.ticket, "symbol": p.symbol, "side": "buy" if p.type == 0 else "sell", "volume": p.volume,
            "open": p.price_open, "sl": p.sl, "tp": p.tp, "profit": p.profit, "magic": p.magic}
           for p in (mt5.positions_get() or [])]
    orders = [{"ticket": o.ticket, "symbol": o.symbol, "type": o.type, "volume": o.volume_current,
               "price": o.price_open, "sl": o.sl, "tp": o.tp} for o in (mt5.orders_get() or [])]
    return _out({"positions": pos, "pending_orders": orders})


class SizeInput(BaseModel):
    symbol: str
    entry: float
    stop_loss: float
    risk_pct: float = Field(0.5, gt=0, le=5)


@mcp.tool(name="mt5_position_size", annotations={"readOnlyHint": True})
def mt5_position_size(params: SizeInput) -> str:
    """Lot size so that hitting the stop loses risk_pct of current equity (rounded down to volume_step)."""
    i = _sym(params.symbol)
    eq = mt5.account_info().equity
    tv = i.trade_tick_value_loss or i.trade_tick_value
    loss_per_lot = abs(params.entry - params.stop_loss) / i.trade_tick_size * tv
    raw = eq * params.risk_pct / 100 / loss_per_lot if loss_per_lot else 0
    lots = int(raw / i.volume_step + 1e-9) * i.volume_step
    lots = 0.0 if lots < i.volume_min else min(lots, i.volume_max)
    return _out({"equity": eq, "loss_per_lot": loss_per_lot, "lots": round(lots, 8), "risk_money": loss_per_lot * lots})


# ---------------- trading tools ----------------

class OrderInput(BaseModel):
    symbol: str
    side: Literal["buy", "sell"]
    volume: float = Field(..., gt=0)
    stop_loss: float = Field(..., gt=0, description="Required absolute SL price")
    take_profit: float | None = Field(None, gt=0)
    order_type: Literal["market", "limit", "stop"] = "market"
    price: float | None = Field(None, description="Required for limit/stop orders")
    comment: str = "claude-mcp"


def _guard(i, side, volume, entry, sl):
    if not _is_demo() and not ALLOW_REAL:
        raise PermissionError("Real-money account: trading disabled. Set MT5_MCP_ALLOW_REAL=1 to enable.")
    if (side == "buy" and sl >= entry) or (side == "sell" and sl <= entry):
        raise ValueError("Stop loss is on the wrong side of the entry price.")
    tv = i.trade_tick_value_loss or i.trade_tick_value
    risk = abs(entry - sl) / i.trade_tick_size * tv * volume
    eq = mt5.account_info().equity
    if risk > eq * MAX_RISK_PCT / 100:
        raise ValueError(f"Risk {risk:.2f} exceeds {MAX_RISK_PCT}% of equity ({eq * MAX_RISK_PCT / 100:.2f}). Use mt5_position_size.")
    return risk


@mcp.tool(name="mt5_place_order", annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False})
def mt5_place_order(params: OrderInput) -> str:
    """Place a market, limit, or stop order WITH a stop loss. Refuses real accounts unless enabled and caps risk per trade."""
    i = _sym(params.symbol)
    t = mt5.symbol_info_tick(params.symbol)
    if params.order_type == "market":
        entry = t.ask if params.side == "buy" else t.bid
        action, otype = mt5.TRADE_ACTION_DEAL, (mt5.ORDER_TYPE_BUY if params.side == "buy" else mt5.ORDER_TYPE_SELL)
    else:
        if params.price is None:
            raise ValueError("price is required for limit/stop orders")
        entry = params.price
        action = mt5.TRADE_ACTION_PENDING
        otype = {("buy", "limit"): mt5.ORDER_TYPE_BUY_LIMIT, ("sell", "limit"): mt5.ORDER_TYPE_SELL_LIMIT,
                 ("buy", "stop"): mt5.ORDER_TYPE_BUY_STOP, ("sell", "stop"): mt5.ORDER_TYPE_SELL_STOP}[(params.side, params.order_type)]
    risk = _guard(i, params.side, params.volume, entry, params.stop_loss)
    req = {"action": action, "symbol": params.symbol, "volume": params.volume, "type": otype,
           "price": round(entry, i.digits), "sl": round(params.stop_loss, i.digits),
           "tp": round(params.take_profit, i.digits) if params.take_profit else 0.0,
           "deviation": 20, "magic": MAGIC, "comment": params.comment[:31],
           "type_time": mt5.ORDER_TIME_GTC, "type_filling": _filling(i)}
    res = mt5.order_send(req)
    if res is None:
        raise RuntimeError(f"order_send failed: {mt5.last_error()}")
    return _out({"retcode": res.retcode, "ok": res.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED),
                 "comment": res.comment, "order": res.order, "deal": res.deal, "price": res.price,
                 "volume": res.volume, "risk_money": round(risk, 2)})


class ModifyInput(BaseModel):
    ticket: int
    stop_loss: float = Field(..., gt=0)
    take_profit: float | None = None


@mcp.tool(name="mt5_modify_position", annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True})
def mt5_modify_position(params: ModifyInput) -> str:
    """Change SL/TP on an open position (SL is required; positions are never left without a stop)."""
    _ensure()
    p = mt5.positions_get(ticket=params.ticket)
    if not p:
        raise ValueError(f"No open position {params.ticket}")
    p = p[0]
    res = mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": p.ticket, "symbol": p.symbol,
                          "sl": params.stop_loss, "tp": params.take_profit if params.take_profit is not None else p.tp})
    return _out({"retcode": getattr(res, "retcode", None), "comment": getattr(res, "comment", mt5.last_error())})


class CloseInput(BaseModel):
    ticket: int
    volume: float | None = Field(None, gt=0, description="Partial close volume; omit to close fully")


@mcp.tool(name="mt5_close_position", annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False})
def mt5_close_position(params: CloseInput) -> str:
    """Close (fully or partially) an open position by ticket at market."""
    _ensure()
    p = mt5.positions_get(ticket=params.ticket)
    if not p:
        raise ValueError(f"No open position {params.ticket}")
    p = p[0]
    i = mt5.symbol_info(p.symbol)
    t = mt5.symbol_info_tick(p.symbol)
    buy = p.type == mt5.POSITION_TYPE_BUY
    res = mt5.order_send({"action": mt5.TRADE_ACTION_DEAL, "position": p.ticket, "symbol": p.symbol,
                          "volume": params.volume or p.volume,
                          "type": mt5.ORDER_TYPE_SELL if buy else mt5.ORDER_TYPE_BUY,
                          "price": t.bid if buy else t.ask, "deviation": 30, "magic": MAGIC,
                          "type_filling": _filling(i)})
    return _out({"retcode": getattr(res, "retcode", None), "comment": getattr(res, "comment", mt5.last_error()),
                 "price": getattr(res, "price", None)})


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--http", action="store_true", help="serve over streamable HTTP (for Hermes Agent in WSL) instead of stdio")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    if a.http:
        mcp.settings.host, mcp.settings.port = a.host, a.port
        mcp.run(transport="streamable-http")      # endpoint: http://<host>:<port>/mcp
    else:
        mcp.run()
