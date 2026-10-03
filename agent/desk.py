"""Main agents and their subagents.

Every MT5 symbol gets a MAIN agent that makes the call. Before any trade goes out it spawns
SUBAGENTS that each check one thing and report back to the main: approve, or veto with a reason. One veto = no trade.
Subagents are plain functions on numbers the main already has, so the whole review takes microseconds and the price
can't move under it. The latest review per asset is kept for the app (GET /api/agents) in data/agents.json.
"""
import json
import threading
import time

from app import settings

_lock = threading.Lock()
MAX_KEEP = 40


def _file():
    return settings.DATA / "agents.json"


def _load() -> dict:
    try:
        return json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def review(venue: str, asset: str, decision: str, prob: float, subagents: list[tuple[str, bool, str]],
           extra: dict | None = None) -> dict:
    """subagents: [(role, ok, says)]. Returns the main's final word and records it."""
    t0 = time.perf_counter()
    vetoes = [(r, s) for r, ok, s in subagents if not ok]
    final = decision if not vetoes or decision in ("PASS", "WAIT") else "PASS"
    out = {"venue": venue, "asset": asset, "decision": decision, "final": final, "prob": round(float(prob), 4),
           "t": time.time(), "subagents": [{"role": r, "verdict": "approve" if ok else "veto", "says": s}
                                            for r, ok, s in subagents],
           "says": (f"{len(subagents)} subagents approve: {decision}." if not vetoes
                    else f"Vetoed by {vetoes[0][0]}: {vetoes[0][1]}"), **(extra or {})}
    out["ms"] = round((time.perf_counter() - t0) * 1000, 3)
    with _lock:
        d = _load()
        d[f"{venue}:{asset}"] = out
        if len(d) > MAX_KEEP:
            for k in sorted(d, key=lambda k: d[k]["t"])[:len(d) - MAX_KEEP]:
                d.pop(k)
        try:
            _file().write_text(json.dumps(d), encoding="utf-8")
        except OSError:
            pass
    return out


def desk() -> dict:
    d = _load()
    rows = sorted(d.values(), key=lambda r: -r["t"])
    return {"mt5": [r for r in rows if r["venue"] == "mt5"]}


# ---------- the MT5 subagents ----------
def mt5_subagents(side: str, prob: float, threshold: float, tp_dist: float | None, sl_dist: float | None,
                  closes, quiz_action: str | None) -> list[tuple[str, bool, str]]:
    subs = []
    margin = prob - threshold
    subs.append(("Confidence", margin >= 0, f"{prob:.0%} vs {threshold:.0%} needed"))
    if tp_dist and sl_dist:
        rr = tp_dist / sl_dist
        subs.append(("Reward/risk", rr >= 1.0, f"{rr:.2f} : 1" + ("" if rr >= 1 else " — the stop is bigger than the target")))
    if closes is not None and len(closes) >= 6:
        mv = float(closes[-1] - closes[-6])
        against = (mv < 0) if side == "buy" else (mv > 0)
        ok = not against or margin >= 0.03
        subs.append(("Momentum", ok, ("last 5 candles agree" if not against else
                                      "last 5 candles go the other way" + (", confidence covers it" if ok else " and confidence is thin"))))
    if quiz_action:
        subs.append(("Quiz agent", True, f"says {quiz_action}" + (" too" if quiz_action == side else " (advisory)")))
    return subs
