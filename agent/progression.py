"""Stage ladder: the bot earns its way from paper money to real money.

    Paper (in the app, no orders) -> Demo (MT5 demo account) -> Real 2 open -> Real 5 open -> Real full

Each stage has a gate: enough closed trades, days, points earned (1 point = $1), profit factor, and a drawdown
limit. Leaving Paper is automatic (Demo is still fake money). Every step into or up within real money needs your
click. If a stage's drawdown passes its limit the bot drops back one stage automatically.
State lives on disk in data/progression.json; trades come from the ledger (data/trades.db).
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from . import ledger

PATH = Path(__file__).resolve().parent.parent / "data" / "progression.json"

STAGES = [
    {"id": "paper", "label": "Paper", "mode": "paper", "max_open": None, "note": "fake money inside the app, live prices"},
    {"id": "demo", "label": "Demo", "mode": "demo", "max_open": None, "note": "real orders on your MT5 demo account"},
    {"id": "real_1", "label": "Real · 2 open", "mode": "real", "max_open": 2, "note": "real money, at most 2 trades at once"},
    {"id": "real_2", "label": "Real · 5 open", "mode": "real", "max_open": 5, "note": "real money, at most 5 trades at once"},
    {"id": "real_3", "label": "Real · full", "mode": "real", "max_open": None, "note": "real money, your full limit"},
]
IDS = [s["id"] for s in STAGES]

# What a stage must show before moving up. score = points = dollars (stop hits x1.5).
DEFAULT_GATES = {
    "paper":  {"min_trades": 100, "min_days": 5,  "min_score": 100, "min_profit_factor": 1.2, "max_drawdown_pct": 5.0},
    "demo":   {"min_trades": 150, "min_days": 10, "min_score": 150, "min_profit_factor": 1.2, "max_drawdown_pct": 5.0},
    "real_1": {"min_trades": 100, "min_days": 10, "min_score": 50,  "min_profit_factor": 1.2, "max_drawdown_pct": 3.0},
    "real_2": {"min_trades": 150, "min_days": 10, "min_score": 100, "min_profit_factor": 1.2, "max_drawdown_pct": 3.0},
    "real_3": {"min_trades": 0,   "min_days": 0,  "min_score": 0,   "min_profit_factor": 0,   "max_drawdown_pct": 3.0},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load() -> dict:
    try:
        return json.loads(PATH.read_text())
    except (OSError, ValueError):
        return {"stage": "paper", "since": _now(), "start_balance": None, "history": []}


def save(state: dict):
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(state, indent=2))


def stage_info(stage_id: str) -> dict:
    return STAGES[IDS.index(stage_id)]


def _stage_trades(state: dict) -> list[dict]:
    mode = stage_info(state["stage"])["mode"]
    rows = [r for r in ledger.recent(100_000, mode) if r["status"] == "closed" and (r["close_utc"] or "") >= state["since"]]
    return sorted(rows, key=lambda r: r["close_utc"] or "")


def evaluate(state: dict, gates: dict | None = None, start_balance: float | None = None) -> dict:
    """Progress of the current stage against its gate."""
    gates = {**DEFAULT_GATES, **(gates or {})}
    g = gates[state["stage"]]
    rows = _stage_trades(state)
    bal0 = state.get("start_balance") or start_balance or 0
    pnl = [r["pnl"] or 0 for r in rows]
    score = sum(r["score"] or 0 for r in rows)
    gross_win = sum(p for p in pnl if p > 0)
    gross_loss = -sum(p for p in pnl if p < 0)
    pf = gross_win / gross_loss if gross_loss else (float("inf") if gross_win else 0.0)
    peak = run = dd = 0.0
    for p in pnl:
        run += p
        peak = max(peak, run)
        dd = max(dd, peak - run)
    dd_pct = 100 * dd / bal0 if bal0 else 0.0
    days = (time.time() - datetime.fromisoformat(state["since"]).timestamp()) / 86400
    checks = [
        {"name": "Closed trades", "value": len(rows), "target": g["min_trades"], "ok": len(rows) >= g["min_trades"]},
        {"name": "Days in stage", "value": round(days, 1), "target": g["min_days"], "ok": days >= g["min_days"]},
        {"name": "Points earned ($)", "value": round(score, 2), "target": g["min_score"], "ok": score >= g["min_score"]},
        {"name": "Profit factor", "value": round(pf, 2) if pf != float("inf") else "∞", "target": g["min_profit_factor"],
         "ok": pf >= g["min_profit_factor"]},
        {"name": "Worst drawdown %", "value": round(dd_pct, 2), "target": g["max_drawdown_pct"], "ok": dd_pct <= g["max_drawdown_pct"],
         "limit": True},
    ]
    idx = IDS.index(state["stage"])
    nxt = STAGES[idx + 1] if idx + 1 < len(STAGES) else None
    return {"stage": stage_info(state["stage"]), "next": nxt, "checks": checks,
            "eligible": bool(nxt) and all(c["ok"] for c in checks),
            "breach": dd_pct > g["max_drawdown_pct"],
            "needs_approval": bool(nxt) and nxt["mode"] == "real",
            "trades": len(rows), "score": round(score, 2), "drawdown_pct": round(dd_pct, 2),
            "since": state["since"], "history": state.get("history", [])[-10:]}


def move(state: dict, to_stage: str, reason: str, start_balance: float | None) -> dict:
    state["history"] = state.get("history", []) + [
        {"time": _now(), "from": state["stage"], "to": to_stage, "reason": reason}]
    state.update(stage=to_stage, since=_now(), start_balance=start_balance)
    save(state)
    return state


def promote(state: dict, reason: str, start_balance: float | None) -> dict:
    i = IDS.index(state["stage"])
    if i + 1 >= len(IDS):
        return state
    return move(state, IDS[i + 1], reason, start_balance)


def demote(state: dict, reason: str, start_balance: float | None) -> dict:
    i = IDS.index(state["stage"])
    if i == 0:
        return move(state, "paper", reason, start_balance)       # paper restarts its count after a breach
    return move(state, IDS[i - 1], reason, start_balance)
