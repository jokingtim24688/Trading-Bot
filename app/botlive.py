"""The Bot tab's full-screen live card: one call with everything it shows, plus the co-pilot / mode / symbol controls.

`GET /api/bot/live` never contains a stop loss. Stops stay in every order and in the ledger (the broker still
enforces them), but the live card shows only side, symbol, entry, take profit and points, as the user asked.

Points: 1 point = 1 unit of account currency (agent/score.py), the same points as the Paper gate. Realized = the
score of the bot's closed trades (stop-loss hits count 1.5x), floating = open trades' live P/L.

Co-pilot: the agent writes its proposal to data/copilot.json and waits; `decide()` writes data/copilot_decision.json,
which the agent reads within a second. The agent owns the proposal file; the app only writes the decision.
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from agent import ledger

from . import manual, mt5_service, settings
from .jobs import jobs

MODES = ("auto", "copilot")
LIVE_MODES = ("paper", "demo", "real")


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def proposal_path() -> Path:
    return settings.DATA / "copilot.json"


def decision_path() -> Path:
    return settings.DATA / "copilot_decision.json"


def _public(p: dict | None) -> dict | None:
    if not p:
        return None
    out = {k: v for k, v in p.items() if k not in ("sl", "_ctx")}
    if out.get("status") == "pending":
        out["seconds_left"] = max(0.0, round(out.get("expires", 0) - time.time(), 1))
    return out


def proposal() -> dict | None:
    """The co-pilot's current proposal (pending), or the last decided one, without its stop loss. None when the
    agent isn't running."""
    if not jobs.jobs["agent"].running:
        return None
    return _public(_read(proposal_path()))


def decide(pid: str, action: str) -> dict:
    if action not in ("approve", "skip"):
        raise ValueError("action must be approve or skip")
    p = proposal()
    if not p or p.get("status") != "pending":
        raise LookupError("There's no co-pilot proposal waiting.")
    if str(p.get("id")) != str(pid):
        raise LookupError("That proposal has already been replaced or decided.")
    if p.get("seconds_left", 0) <= 0:
        raise LookupError("That proposal has run out of time.")
    decision_path().write_text(json.dumps({"id": str(pid), "action": action, "time": time.time()}), encoding="utf-8")
    return {"ok": True, "id": str(pid), "action": action,
            "note": "Sending the order now." if action == "approve" else "Skipped."}


def set_mode(mode: str) -> dict:
    if mode not in MODES:
        raise ValueError("mode must be auto or copilot")
    settings.save({"bot_mode": mode})
    running = jobs.jobs["agent"].running
    return {"ok": True, "bot_mode": mode,
            "note": ("Applies from the next candle (within a minute)." if running else "Applies when the agent starts.")}


def symbols() -> dict:
    """Symbols with a trained model (the switcher's list), and the current one."""
    root = Path(mt5_service.__file__).resolve().parent.parent / "models"
    have = sorted(p.name[:-len("_M1.json")] for p in root.glob("*_M1.json")) if root.exists() else []
    cur = settings.load()["symbol"]
    return {"current": cur, "trained": have,
            "watch": sorted(set(settings.load().get("symbols_watch") or []) | set(have) | {cur})}


def other_symbol_open(old: str) -> int:
    return len([t for t in ledger.open_trades(symbol=old) if t["mode"] in LIVE_MODES])


def points(symbol: str | None = None) -> dict:
    """Realized + floating points of the bot's own trades (paper, demo and real; replays don't count)."""
    rows = [r for r in ledger.recent(1_000_000) if r["mode"] in LIVE_MODES and r["status"] == "closed"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    realized = sum(r.get("score") or 0.0 for r in rows)
    realized_today = sum(r.get("score") or 0.0 for r in rows if (r.get("close_utc") or "")[:10] == today)
    opn = [t for t in ledger.open_trades(symbol=symbol) if t["mode"] in LIVE_MODES]
    try:
        fl = mt5_service.floating_for(opn) if opn else {}
    except Exception:                       # noqa: BLE001 - MT5 closed: no floating figure
        fl = {}
    floating = sum((fl.get(t["id"]) or {}).get("pnl") or 0.0 for t in opn)
    return {"realized": round(realized, 2), "floating": round(floating, 2), "total": round(realized + floating, 2),
            "today": round(realized_today + floating, 2), "closed_trades": len(rows), "open_trades": len(opn)}


def _positions(symbol: str | None) -> list[dict]:
    """The bot's open trades for the card: side, symbol, entry, TP, live points and progress toward TP. No SL."""
    opn = [t for t in ledger.open_trades(symbol=symbol) if t["mode"] in LIVE_MODES]
    try:
        fl = mt5_service.floating_for(opn) if opn else {}
    except Exception:                       # noqa: BLE001
        fl = {}
    out = []
    for t in opn:
        f = fl.get(t["id"]) or {}
        px, entry, tp = f.get("price"), t["entry"], t["tp"]
        prog = None
        if px is not None and tp and tp != entry:
            prog = max(0.0, min(100.0, 100 * (px - entry) / (tp - entry)))
        out.append({"id": t["id"], "ticket": t.get("ticket"), "mode": t["mode"], "symbol": t["symbol"],
                    "side": t["side"], "lots": t["lots"], "entry": entry, "tp": tp, "price": px,
                    "points": f.get("pnl"), "progress_pct": None if prog is None else round(prog, 1),
                    "opened": t.get("open_utc"), "entry_time": t.get("open_bar")})
    return out


def heartbeat(symbol: str, status: dict | None) -> dict:
    """Green / red for the broker (MT5 connected), the AI (agent running and deciding) and the data feed (fresh
    ticks)."""
    hb = {"broker": {"ok": False, "text": "MT5 not reachable"}, "ai": {"ok": False, "text": "agent stopped"},
          "feed": {"ok": False, "text": "no prices"}}
    try:
        q = manual.quote(symbol)
        hb["broker"] = {"ok": bool(q["connected"]), "text": "MT5 connected" if q["connected"] else "MT5 offline"}
        age = q.get("tick_age")
        fresh = age is not None and age < 90
        hb["feed"] = {"ok": fresh and q.get("market_open", True),
                      "text": ("live" if fresh else f"last price {int(age)} s ago" if age is not None else "no prices")
                      + ("" if q.get("market_open", True) else ", market closed"),
                      "price": (q["bid"] + q["ask"]) / 2, "bid": q["bid"], "ask": q["ask"], "digits": q["digits"]}
    except Exception as e:                  # noqa: BLE001 - MT5 closed or symbol missing
        hb["broker"]["text"] = f"MT5: {str(e)[:80]}"
    if jobs.jobs["agent"].running:
        age = None
        if status and status.get("time_utc"):
            try:
                age = time.time() - datetime.fromisoformat(status["time_utc"]).timestamp()
            except ValueError:
                pass
        ok = age is not None and age < 150          # it reports on every closed 1-minute candle
        hb["ai"] = {"ok": ok, "text": "deciding every candle" if ok else "starting" if age is None else
                    f"no decision for {int(age)} s"}
    return hb


def live(status: dict | None) -> dict:
    s = settings.load()
    sym = (status or {}).get("symbol") or s["symbol"]
    st = dict(status) if status else None
    if st and st.get("proposal"):
        st["proposal"] = _public(st["proposal"])
    return {"symbol": sym, "bot_mode": s.get("bot_mode", "auto"), "copilot_seconds": s.get("copilot_seconds", 30),
            "copilot_auto_execute": s.get("copilot_auto_execute", False),
            "display_timezone": s.get("display_timezone", ""), "running": jobs.jobs["agent"].running,
            "status": st, "proposal": proposal(), "heartbeat": heartbeat(sym, status), "points": points(),
            "positions": _positions(None), "server_time": int(time.time())}
