"""Tools the local Hermes model can call. Trading tools here are read-only plus agent start/stop;
placing orders by chat goes through Hermes Agent + the MT5 MCP server, which has its own risk guard."""
import ast
import datetime as dt
import json
import operator
import re
from pathlib import Path

import httpx

from . import memory, mt5_service
from .jobs import jobs
from .settings import DATA, load

NOTES = DATA / "notes"
NOTES.mkdir(exist_ok=True)


def _calc(expr: str) -> float:
    ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
           ast.Pow: operator.pow, ast.Mod: operator.mod, ast.USub: operator.neg, ast.UAdd: operator.pos}

    def ev(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in ops:
            return ops[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in ops:
            return ops[type(n.op)](ev(n.operand))
        raise ValueError("only numbers and + - * / ** % are allowed")
    return ev(ast.parse(expr, mode="eval").body)


def _bars_summary(symbol: str, count: int) -> dict:
    d = mt5_service.m1_bars(symbol, min(max(count, 20), 600) + 1)
    bars = d["bars"][:-1]                       # closed bars only
    closes = [b["close"] for b in bars]
    trs = [max(b["high"] - b["low"], abs(b["high"] - p["close"]), abs(b["low"] - p["close"])) for p, b in zip(bars, bars[1:])]
    atr14 = sum(trs[-14:]) / min(14, len(trs)) if trs else 0
    return {"symbol": symbol, "timeframe": "M1", "bars": len(bars), "bid": d["bid"], "ask": d["ask"],
            "spread_points": round((d["ask"] - d["bid"]) / d["point"]),
            "last_close": closes[-1], "high": max(b["high"] for b in bars), "low": min(b["low"] for b in bars),
            "change_pct": round((closes[-1] / closes[0] - 1) * 100, 3), "atr14": round(atr14, d["digits"]),
            "last_10": [{k: b[k] for k in ("time", "open", "high", "low", "close")} for b in bars[-10:]]}


def _web_fetch(url: str) -> str:
    if not load().get("allow_web", True):
        return "web access is turned off in Settings"
    r = httpx.get(url, timeout=15, follow_redirects=True, headers={"User-Agent": "TradingBot/1.0"})
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", r.text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text)[:6000]


def _safe_note_name(title: str) -> Path:
    name = re.sub(r"[^a-zA-Z0-9 _-]", "", title).strip()[:60] or "note"
    return NOTES / f"{name}.md"


def _start_agent(mode: str = "paper") -> str:
    s = load()
    if not mt5_service.model_exists(s["symbol"]):
        return f"No trained model for {s['symbol']} yet. Train one on the Train tab first."
    args = ["-m", "agent.run", "--symbol", s["symbol"], "--threshold", str(s["threshold"]), "--risk", str(s["risk_pct"])]
    if s.get("terminal_path"):
        args += ["--terminal", s["terminal_path"]]
    if mode == "demo":
        args.append("--live")          # agent.run itself refuses real accounts without --allow-real
    jobs.start("agent", args)
    return f"agent started in {mode} mode on {s['symbol']} M1"


def _bot_trades(limit: int = 10) -> dict:
    from .server import bot_trades_payload
    d = bot_trades_payload(limit)
    keep = ("id", "mode", "symbol", "side", "lots", "entry", "sl", "tp", "prob", "status", "open_utc", "exit",
            "exit_reason", "pnl", "r_multiple", "close_utc", "price")
    return {"open": [{k: t.get(k) for k in keep} for t in d["open"]],
            "recent": [{k: t.get(k) for k in keep} for t in d["recent"] if t["status"] == "closed"][:limit],
            "stats": d["stats"]}


TOOLS = {
    "get_account": (lambda: mt5_service.account(), "MT5 account balance, equity, margin, demo/real, connection.", {}),
    "get_positions": (lambda: mt5_service.positions(), "Open MT5 positions.", {}),
    "get_m1_market": (lambda symbol, count=120: _bars_summary(symbol, count),
                      "Summary of recent closed M1 bars for a symbol: price, spread, ATR14, range, last 10 bars.",
                      {"symbol": {"type": "string"}, "count": {"type": "integer", "description": "bars to look back, 20-600"}}),
    "position_size": (lambda symbol, entry, stop, risk_pct=0.5: mt5_service.lots_for_risk(symbol, entry, stop, risk_pct),
                      "Lot size so a stop-out loses risk_pct of equity.",
                      {"symbol": {"type": "string"}, "entry": {"type": "number"}, "stop": {"type": "number"},
                       "risk_pct": {"type": "number"}}),
    "get_bot_trades": (lambda limit=10: _bot_trades(limit),
                       "The trading bot's own trades: open ones (entry, SL, TP, live P/L) and recent closed ones, plus "
                       "win rate / P&L / R stats per mode. Use when the user wants to follow or copy the bot.",
                       {"limit": {"type": "integer", "description": "recent closed trades to include"}}),
    "agent_status": (lambda: {**jobs.status()["agent"], "log_tail": jobs.jobs["agent"].tail(15)},
                     "Whether the M1 trading agent is running, plus its latest log lines.", {}),
    "start_agent": (_start_agent, "Start the M1 trading agent. mode 'paper' (no orders) or 'demo' (orders on a demo account).",
                    {"mode": {"type": "string", "enum": ["paper", "demo"]}}),
    "stop_agent": (lambda: (jobs.stop("agent"), "agent stopped")[1], "Stop the trading agent (server-side SL/TP stay active).", {}),
    "remember": (memory.remember, "Save a fact about the user, their preferences, or lessons learned to long-term memory.",
                 {"text": {"type": "string"}}),
    "recall": (lambda query: {"facts": memory.relevant_facts(query, 8), "past_messages": memory.search_messages(query, 5)},
               "Search long-term memory and past conversations.", {"query": {"type": "string"}}),
    "web_fetch": (_web_fetch, "Fetch a web page and return its text (news, docs, calendars).", {"url": {"type": "string"}}),
    "save_note": (lambda title, text: (_safe_note_name(title).write_text(text, encoding="utf-8"), f"saved note '{title}'")[1],
                  "Save a markdown note to disk (trade plans, checklists, research).",
                  {"title": {"type": "string"}, "text": {"type": "string"}}),
    "list_notes": (lambda: sorted(p.stem for p in NOTES.glob("*.md")), "List saved notes.", {}),
    "read_note": (lambda title: _safe_note_name(title).read_text(encoding="utf-8") if _safe_note_name(title).exists() else "no such note",
                  "Read a saved note.", {"title": {"type": "string"}}),
    "calculate": (lambda expression: _calc(expression), "Evaluate arithmetic, e.g. '10000*0.005/(2.4*100)'.",
                  {"expression": {"type": "string"}}),
    "current_time": (lambda: {"utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                              "local": dt.datetime.now().isoformat(timespec="seconds")}, "Current UTC and local time.", {}),
}

REQUIRED = {"get_m1_market": ["symbol"], "position_size": ["symbol", "entry", "stop"], "remember": ["text"],
            "recall": ["query"], "web_fetch": ["url"], "save_note": ["title", "text"], "read_note": ["title"],
            "calculate": ["expression"]}


def schemas() -> list[dict]:
    return [{"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props, "required": REQUIRED.get(name, [])}}}
        for name, (_, desc, props) in TOOLS.items()]


def call(name: str, args: dict | str | None) -> str:
    if name not in TOOLS:
        return f"unknown tool {name}"
    if isinstance(args, str):
        try:
            args = json.loads(args or "{}")
        except json.JSONDecodeError:
            args = {}
    try:
        result = TOOLS[name][0](**(args or {}))
    except Exception as e:                      # tool errors go back to the model as text
        return f"error: {e}"
    return result if isinstance(result, str) else json.dumps(result, default=str)[:8000]
