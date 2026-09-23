"""The bot learns from its own trades.

Groups closed trades from the ledger by UTC hour, direction, model confidence and exit reason, then:
  1. writes a skill (.claude/skills/m1-bot-lessons/) that Hermes and Claude can read: what works, what doesn't;
  2. writes data/learned_rules.json, which the agent applies as extra entry filters:
       - blocked_hours: UTC hours that lost points over enough trades
       - min_confidence: skip low-confidence buckets that lost points
       - disabled_side: stop buying (or selling) if that side loses while the other side makes money
Rules only form from groups with enough trades (MIN_GROUP), so a few unlucky trades don't block anything.
Points = dollars (stop hits x1.5), same as the score.
"""
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import ledger
from .pro import SETUP_NAMES

ROOT = Path(__file__).resolve().parent.parent
RULES_PATH = ROOT / "data" / "learned_rules.json"
SKILL_DIR = ROOT / ".claude" / "skills" / "m1-bot-lessons"
MIN_TRADES = 50        # no rules until the bot has at least this many closed trades
MIN_GROUP = 20         # a group needs this many trades before it can create a rule
MAX_BLOCKED_HOURS = 8  # never block more than a third of the day
CONF_BUCKETS = [0.0, 0.15, 0.2, 0.25, 0.3, 0.4, 1.01]

_cache = {"mtime": None, "rules": {}}


def _bucket(p):
    if p is None:
        return "unknown"
    for lo, hi in zip(CONF_BUCKETS, CONF_BUCKETS[1:]):
        if lo <= p < hi:
            return f"{lo:.2f}-{min(hi, 1):.2f}"
    return "unknown"


def _group(rows, key):
    g = defaultdict(list)
    for r in rows:
        g[key(r)].append(r)
    out = {}
    for k, rs in g.items():
        score = sum(r["score"] or 0 for r in rs)
        out[k] = {"trades": len(rs), "wins": sum(1 for r in rs if (r["pnl"] or 0) > 0),
                  "win_pct": round(100 * sum(1 for r in rs if (r["pnl"] or 0) > 0) / len(rs), 1),
                  "pnl": round(sum(r["pnl"] or 0 for r in rs), 2), "score": round(score, 2),
                  "avg_score": round(score / len(rs), 2)}
    return dict(sorted(out.items()))


def analyze(modes=("replay", "paper", "demo", "real")) -> dict:
    rows = [r for r in ledger.recent(100_000) if r["status"] == "closed" and r["mode"] in modes]
    hour = lambda r: int((r["open_utc"] or "T00")[11:13] or 0)      # noqa: E731
    return {
        "trades": len(rows),
        "score": round(sum(r["score"] or 0 for r in rows), 2),
        "by_hour": _group(rows, hour),
        "by_side": _group(rows, lambda r: r["side"]),
        "by_confidence": _group(rows, lambda r: _bucket(r["prob"])),
        "by_exit": _group(rows, lambda r: r["exit_reason"] or "unknown"),
        "by_mode": _group(rows, lambda r: r["mode"]),
        "by_setup": _group(rows, lambda r: r.get("setup") or "not recorded"),
    }


def derive_rules(a: dict) -> dict:
    rules = {"blocked_hours": [], "min_confidence": None, "disabled_side": None, "blocked_setups": [], "reasons": []}
    if a["trades"] < MIN_TRADES:
        rules["reasons"].append(f"Only {a['trades']} closed trades; rules start at {MIN_TRADES}.")
        return rules
    bad = [(h, s) for h, s in a["by_hour"].items() if s["trades"] >= MIN_GROUP and s["score"] < 0]
    bad = sorted(bad, key=lambda x: x[1]["score"])[:MAX_BLOCKED_HOURS]
    rules["blocked_hours"] = sorted(h for h, _ in bad)
    for h, s in bad:
        rules["reasons"].append(f"{h:02d}:00 UTC lost {s['score']} points over {s['trades']} trades.")
    # lowest confidence buckets that lost points -> raise the bar above them
    for b, s in a["by_confidence"].items():
        if b == "unknown" or s["trades"] < MIN_GROUP:
            continue
        if s["score"] < 0:
            rules["min_confidence"] = float(b.split("-")[1])
            rules["reasons"].append(f"Confidence {b} lost {s['score']} points over {s['trades']} trades.")
        else:
            break
    # pro setups that keep losing: stop taking them, but never more than half of them, so the bot keeps trading/learning
    groups = {k: s for k, s in a.get("by_setup", {}).items() if k != "not recorded"}
    losers = sorted((k for k, s in groups.items() if s["trades"] >= MIN_GROUP and s["score"] < 0), key=lambda k: groups[k]["score"])
    for k in losers[: len(groups) // 2]:
        rules["blocked_setups"].append(k)
        rules["reasons"].append(f"Setup '{SETUP_NAMES.get(k, k)}' lost {groups[k]['score']} points over {groups[k]['trades']} trades.")
    sides = a["by_side"]
    if {"buy", "sell"} <= sides.keys():
        for bad_side, good_side in (("buy", "sell"), ("sell", "buy")):
            b, g = sides[bad_side], sides[good_side]
            if b["trades"] >= 2 * MIN_GROUP and b["score"] < 0 and g["score"] > 0:
                rules["disabled_side"] = bad_side
                rules["reasons"].append(f"{bad_side.title()}s lost {b['score']} points while {good_side}s made {g['score']}.")
    return rules


def _table(groups: dict, label: str) -> str:
    lines = [f"| {label} | Trades | Win % | P/L $ | Points | Avg pts |", "|---|---|---|---|---|---|"]
    for k, s in groups.items():
        k = f"{k:02d}:00" if isinstance(k, int) else k
        lines.append(f"| {k} | {s['trades']} | {s['win_pct']} | {s['pnl']} | {s['score']} | {s['avg_score']} |")
    return "\n".join(lines)


def write_skill(a: dict, rules: dict, when: str):
    SKILL_DIR.mkdir(parents=True, exist_ok=True)
    (SKILL_DIR / "references").mkdir(exist_ok=True)
    active = []
    if rules["blocked_hours"]:
        active.append("- Skip new entries during these UTC hours: " + ", ".join(f"{h:02d}:00" for h in rules["blocked_hours"]))
    if rules["min_confidence"]:
        active.append(f"- Require model confidence of at least {rules['min_confidence']:.2f}")
    if rules["disabled_side"]:
        active.append(f"- Don't open {rules['disabled_side']} trades")
    if rules.get("blocked_setups"):
        active.append("- Skip these setups: " + ", ".join(SETUP_NAMES.get(k, k) for k in rules["blocked_setups"]))
    body = f"""---
name: m1-bot-lessons
description: What the user's MT5 M1 trading bot has learned from its own trades (paper, demo and real) - which hours, directions and confidence levels made or lost money, and the entry filters it now applies. Use this whenever the user asks how the bot is doing, why it skipped a trade, what it has learned, or whether it is ready to move up to demo or real money.
---

# M1 bot lessons (written by the bot)

Last updated {when} from {a['trades']} closed trades (total {a['score']} points; 1 point = $1, stop-loss hits count 1.5x).

## Rules the bot applies now
{chr(10).join(active) if active else "- None yet. Rules form once groups have enough trades (" + str(MIN_GROUP) + " each, " + str(MIN_TRADES) + " total)."}

Why:
{chr(10).join("- " + r for r in rules["reasons"]) if rules["reasons"] else "- No losing groups with enough trades."}

## By UTC hour
{_table(a['by_hour'], 'Hour')}

## By direction
{_table(a['by_side'], 'Side')}

## By model confidence
{_table(a['by_confidence'], 'Confidence')}

## By pro setup (what a professional trader would call the entry)
{_table({SETUP_NAMES.get(k, k): s for k, s in a.get('by_setup', {}).items()}, 'Setup')}

## By how trades closed
{_table(a['by_exit'], 'Exit')}

## By stage
{_table(a['by_mode'], 'Mode')}

Earlier snapshots: `references/history.md`. Rules file the agent reads: `data/learned_rules.json`.
"""
    (SKILL_DIR / "SKILL.md").write_text(body, encoding="utf-8")
    hist = SKILL_DIR / "references" / "history.md"
    entry = (f"\n## {when}\n- Trades: {a['trades']}, points: {a['score']}\n"
             + "".join(f"- {r}\n" for r in rules["reasons"]))
    with open(hist, "a", encoding="utf-8") as f:
        if hist.stat().st_size == 0:
            f.write("# Learning history\n")
        f.write(entry)


def learn(modes=("replay", "paper", "demo", "real")) -> dict:
    when = datetime.now(timezone.utc).isoformat(timespec="minutes")
    a = analyze(modes)
    rules = derive_rules(a)
    rules.update(generated=when, trades_analyzed=a["trades"])
    RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
    RULES_PATH.write_text(json.dumps(rules, indent=2))
    write_skill(a, rules, when)
    return {"rules": rules, "analysis": a}


def load_rules() -> dict:
    try:
        m = RULES_PATH.stat().st_mtime
    except OSError:
        return {}
    if _cache["mtime"] != m:
        try:
            _cache.update(mtime=m, rules=json.loads(RULES_PATH.read_text()))
        except ValueError:
            _cache.update(mtime=m, rules={})
    return _cache["rules"]


def block_reason(rules: dict, side: str, prob: float, utc_hour: int, setup: str | None = None) -> str | None:
    """Why the learned rules skip this entry, or None to allow it."""
    if not rules:
        return None
    if utc_hour in rules.get("blocked_hours", []):
        return f"learned: {utc_hour:02d}:00 UTC has been losing"
    if rules.get("min_confidence") and prob < rules["min_confidence"]:
        return f"learned: confidence {prob:.2f} below {rules['min_confidence']:.2f}"
    if rules.get("disabled_side") == side:
        return f"learned: {side} trades have been losing"
    if setup and setup in rules.get("blocked_setups", []):
        return f"learned: '{SETUP_NAMES.get(setup, setup)}' entries have been losing"
    return None
