"""The bot learns from its own trades.

Groups closed trades from the ledger by UTC hour, direction, model confidence and exit reason, then:
  1. writes a skill (.claude/skills/m1-bot-lessons/) that Hermes and Claude can read: what works, what doesn't;
  2. writes data/learned_rules.json, which the agent applies as extra entry filters:
       - blocked_hours: UTC hours that lost points over enough trades
       - min_confidence: skip low-confidence buckets that lost points
       - disabled_side: stop buying (or selling) if that side loses while the other side makes money
Rules only form from groups with enough trades (MIN_GROUP), so a few unlucky trades don't block anything.
Points = dollars (stop hits x1.5), same as the score.

It also learns from each mistake as it happens (on_mistake, called by the ledger whenever a trade closes at a loss):
  - the losing trade goes into data/mistakes.json with a one-line lesson, and the lessons skill is rewritten;
  - a short-term caution forms for that setup + direction: the bot needs more confidence there than it had on the
    trades that just lost, for 24 hours or until it wins there again. Floors keep it trading: a caution never asks for
    more confidence than 80% of its recent entries had, and at most half of the setups it trades can be under caution;
  - the next Quiz build turns the losing trade's chart into a practice question (answer: stay out), so the quiz agent
    (the optional second opinion) practises exactly the spots where the bot was wrong.
"""
import json
import time
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
MIN_PASS_SHARE = 0.5   # the confidence rule never blocks more than half of the confidence levels it has traded at
MISTAKES_PATH = ROOT / "data" / "mistakes.json"
MAX_MISTAKES = 2000
CAUTION_HOURS = 24     # a caution lasts this long after its last loss (or until a win in that setup + direction)
CAUTION_STEP = 0.02    # it asks for this much more confidence than the losing trades had
CAUTION_CAP_PCT = 80   # ...but never more than 80% of the bot's recent entries had (so it keeps trading)
RELEARN_EVERY_S = 20   # after a loss, rules and lessons are rewritten at most this often

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
        "prob_median": _quantile([r["prob"] for r in rows if r["prob"] is not None], 50),
    }


def _quantile(vals: list, pct: float):
    if not vals:
        return None
    v = sorted(vals)
    return float(v[min(len(v) - 1, int(len(v) * pct / 100))])


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
    # lowest confidence buckets that lost points -> raise the bar above them, but never so high that it blocks more than
    # half of the confidence levels the bot has traded at, and never from the top bucket (that would block everything)
    cap = a.get("prob_median")
    for b, s in a["by_confidence"].items():
        if b == "unknown" or s["trades"] < MIN_GROUP:
            continue
        hi = float(b.split("-")[1])
        if s["score"] < 0 and hi < 1:
            if cap is not None and hi > cap:
                rules["min_confidence"] = round(cap, 3)
                rules["reasons"].append(f"Confidence {b} lost {s['score']} points over {s['trades']} trades; the bar "
                                        f"stops at {cap:.2f} so at least half of its usual entries still pass.")
                break
            rules["min_confidence"] = hi
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


# ---------------------------------------------------------------- learning from each mistake
_state = {"relearned": 0.0}


def load_mistakes() -> list[dict]:
    try:
        return json.loads(MISTAKES_PATH.read_text())
    except (OSError, ValueError):
        return []


def _setup_label(setup: str | None) -> str:
    return SETUP_NAMES.get(setup, setup) if setup else "no named setup"


def _live_closed(limit: int = 2000) -> list[dict]:
    """Recent closed paper/demo/real trades, newest first (replays are simulations, not the bot's own mistakes)."""
    return [r for r in ledger.recent(limit) if r["status"] == "closed" and r["mode"] != "replay"]


def derive_cautions(now: float | None = None) -> list[dict]:
    """Short-term cautions from recent losses: for each setup + direction whose latest trades lost, the bot needs more
    confidence than it had on those trades, for CAUTION_HOURS after the last loss or until it wins there again."""
    now = now or time.time()
    rows = _live_closed()
    probs = [r["prob"] for r in rows[:200] if r["prob"] is not None]
    cap = _quantile(probs, CAUTION_CAP_PCT)
    if cap is None:
        return []
    by_ctx: dict = defaultdict(list)
    for r in rows:                                       # newest first
        by_ctx[(r["side"], r.get("setup") or "")].append(r)
    week = now - 7 * 86400
    traded = [k for k, rs in by_ctx.items() if _ts(rs[0]["close_utc"]) >= week]
    out = []
    for (side, setup), rs in by_ctx.items():
        streak = []
        for r in rs:
            if (r["pnl"] or 0) >= 0:
                break
            streak.append(r)
        if not streak:
            continue
        last = _ts(streak[0]["close_utc"])
        until = last + CAUTION_HOURS * 3600
        seen = [r["prob"] for r in streak if r["prob"] is not None]
        if until <= now or not seen:
            continue
        need = round(min(cap, max(seen) + CAUTION_STEP), 3)
        if need <= max(seen):                            # the floor leaves no room above the losing trades: don't block
            continue
        out.append({"side": side, "setup": setup or None, "losses": len(streak), "min_prob": need,
                    "until": round(until), "until_utc": datetime.fromtimestamp(until, timezone.utc).isoformat(timespec="minutes"),
                    "why": f"{len(streak)} loss{'es' if len(streak) > 1 else ''} in a row on {side}s of "
                           f"'{_setup_label(setup)}' (confidence {max(seen):.2f} at most)"})
    out.sort(key=lambda c: (-c["losses"], -c["until"]))
    return out[: max(1, len(traded) // 2)]              # never more than half of the setups it trades


def _ts(iso: str | None) -> float:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() if iso else 0.0
    except ValueError:
        return 0.0


def _lesson(t: dict, cautions: list[dict]) -> str:
    how = {"sl": "hit its stop", "early": "was closed early at a loss", "kill": "was closed by the kill switch",
           "stop_out": "was stopped out by the broker"}.get(t.get("exit_reason") or "",
                                                            "was closed by you at a loss" if "manual" in (t.get("exit_reason") or "")
                                                            else "closed at a loss")
    if (t.get("exit_reason") == "sl") and (t.get("r_multiple") or 0) <= -0.9:
        how = "went straight the wrong way and hit its stop"
    same = [r for r in _live_closed(400) if r["side"] == t["side"] and (r.get("setup") or "") == (t.get("setup") or "")][:10]
    lost = sum(1 for r in same if (r["pnl"] or 0) < 0)
    hour = (t.get("open_utc") or "T00:00")[11:16]
    conf = f", confidence {t['prob']:.2f}" if t.get("prob") is not None else ""
    r_txt = f"{t['r_multiple']:+.2f}R, " if t.get("r_multiple") is not None else ""
    text = (f"{t['side'].title()} on '{_setup_label(t.get('setup'))}' at {hour} UTC{conf} {how} ({r_txt}{t['pnl']:+.2f}). "
            f"{lost} of the last {len(same)} {t['side']}s on this setup lost.")
    c = next((c for c in cautions if c["side"] == t["side"] and (c["setup"] or "") == (t.get("setup") or "")), None)
    if c:
        text += f" It now needs confidence of at least {c['min_prob']:.2f} there until {c['until_utc'][5:16].replace('T', ' ')} UTC (or a win)."
    return text


def _write_rules_cautions(cautions: list[dict], lesson: str | None):
    """Put fresh cautions and the latest lesson into the rules file straight away, without redoing the full analysis."""
    rules = dict(load_rules()) if RULES_PATH.exists() else {"blocked_hours": [], "min_confidence": None,
                                                              "disabled_side": None, "blocked_setups": [], "reasons": []}
    rules["cautions"] = cautions
    if lesson:
        rules["latest_lesson"] = lesson
        rules["latest_lesson_utc"] = datetime.now(timezone.utc).isoformat(timespec="minutes")
    rules["mistakes"] = len(load_mistakes())
    RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = RULES_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(rules, indent=2))
    tmp.replace(RULES_PATH)


def on_mistake(trade_id: int) -> dict | None:
    """A trade just closed at a loss: record it with a lesson, update the cautions the entry filter reads at once, and
    rewrite the full rules and lessons skill (at most every RELEARN_EVERY_S seconds)."""
    t = ledger.get(trade_id)
    if not t or (t["pnl"] or 0) >= 0 or t["mode"] == "replay":
        return None
    cautions = derive_cautions()
    lesson = _lesson(t, cautions)
    m = {"id": t["id"], "mode": t["mode"], "symbol": t["symbol"], "side": t["side"], "setup": t.get("setup"),
         "prob": t["prob"], "open_utc": t["open_utc"], "close_utc": t["close_utc"], "open_bar": t["open_bar"],
         "exit_reason": t["exit_reason"], "pnl": t["pnl"], "r": t["r_multiple"], "lesson": lesson}
    mistakes = [x for x in load_mistakes() if x.get("id") != t["id"]] + [m]
    MISTAKES_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = MISTAKES_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(mistakes[-MAX_MISTAKES:], indent=1))
    tmp.replace(MISTAKES_PATH)
    _write_rules_cautions(cautions, lesson)
    if time.time() - _state["relearned"] >= RELEARN_EVERY_S:
        _state["relearned"] = time.time()
        learn()
    return m


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

## Learning from each mistake
Every losing trade teaches it something straight away. It is recorded with a lesson (`data/mistakes.json`), a
short-term caution forms for that setup + direction, and the next Quiz build turns its chart into a practice
question (answer: stay out).

Cautions now:
{chr(10).join(f"- {_setup_label(c['setup'])}, {c['side']}s: needs confidence of at least {c['min_prob']:.2f} until {c['until_utc']} ({c['why']})" for c in rules.get("cautions", [])) or "- None."}

Latest lessons (newest first):
{chr(10).join(f"- {x['close_utc'][:16] if x.get('close_utc') else ''} {x['lesson']}" for x in reversed(load_mistakes()[-10:])) or "- No losing trades yet."}

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
    mistakes = load_mistakes()
    rules.update(generated=when, trades_analyzed=a["trades"], cautions=derive_cautions(), mistakes=len(mistakes),
                 latest_lesson=mistakes[-1]["lesson"] if mistakes else None,
                 latest_lesson_utc=mistakes[-1].get("close_utc") if mistakes else None)
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


def block_reason(rules: dict, side: str, prob: float, utc_hour: int, setup: str | None = None,
                 cautions: bool = True, recent_probs=None) -> str | None:
    """Why the learned rules skip this entry, or None to allow it. Cautions from recent losses apply only live
    (replays pass cautions=False: their clock is history, not now).

    `recent_probs` = the model's own recent readings (live: the last day's). A learned confidence bar is then capped
    at their median (cautions: their 80th percentile), so a bar learned from another model or from replays on a
    different scale can't block every entry: a learned 0.20 against a model that reads 0.05-0.10 never lets
    anything through."""
    if not rules:
        return None
    vals = sorted(float(v) for v in (recent_probs or []))
    cap_min = _quantile(vals, 50) if len(vals) >= 60 else None
    cap_caution = _quantile(vals, 80) if len(vals) >= 60 else None
    if cautions:
        now = time.time()
        for c in rules.get("cautions", []):
            need = min(c["min_prob"], cap_caution) if cap_caution is not None else c["min_prob"]
            if c["side"] == side and (c["setup"] or None) == (setup or None) and c["until"] > now and prob < need:
                return (f"learned from a recent loss: {side}s on '{_setup_label(setup)}' need confidence "
                        f"{need:.2f} until {c['until_utc'][5:16].replace('T', ' ')} UTC ({c['why']})")
    if utc_hour in rules.get("blocked_hours", []):
        return f"learned: {utc_hour:02d}:00 UTC has been losing"
    mc = rules.get("min_confidence")
    if mc and cap_min is not None:
        mc = min(mc, cap_min)
    if mc and prob < mc:
        return f"learned: confidence {prob:.2f} below {mc:.2f}"
    if rules.get("disabled_side") == side:
        return f"learned: {side} trades have been losing"
    if setup and setup in rules.get("blocked_setups", []):
        return f"learned: '{SETUP_NAMES.get(setup, setup)}' entries have been losing"
    return None
