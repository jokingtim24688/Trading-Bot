"""Weak-spot report: what the quiz agent gets stuck on, what those questions have in common, and what might fix it.

    python -m agent.quiz_report

Runs automatically at the end of every quiz run and every 5 minutes while one is going. For every setup (traps
separately) it measures how often the agent answers right in practice, on the exam, how many questions are still
unfinished and which wrong answer it keeps giving. The worst groups become weak spots. For each weak spot it compares
the questions the agent misses with the ones it gets right, on things a trader can read (time of day, volatility, the
H1 trend, stretch from the session average, position in the day's range, round numbers, prior-day levels, year), and
writes the clearest differences as sentences. For every setup with traps it also checks whether anything on the chart
separates the traps from the winners at all; when nothing does, the quiz needs information it doesn't have yet.

Writes:
    data/quiz_report.json                   for the app's Weak spots panel
    data/quiz_report.md                     the report to paste to Claude ("Copy report for Claude")
    .claude/skills/quiz-weak-spots/         a skill: index + one page per weak spot (pages named claude-*.md are
                                            written by Claude from the pasted report and are never touched here)
"""
import re
from datetime import datetime, timezone

import numpy as np

from . import quiz as Q

REPORT_JSON = Q.DATA / "quiz_report.json"
REPORT_MD = Q.DATA / "quiz_report.md"
SKILL_DIR = Q.ROOT / ".claude" / "skills" / "quiz-weak-spots"
MIN_GROUP = 15            # questions a group needs before it can be called a weak spot
TOP = 8                   # weak spots reported
D_PATTERN = 0.35          # effect size that counts as a pattern
D_SEPARATE = 0.25         # below this for every feature, traps and winners look the same on the chart
ACT_NAME = {"buy": "BUY", "sell": "SELL", "wait": "STAY OUT"}

HOUR_WINDOWS = [(0, 10, "before London (00:00-09:59 server)"), (10, 13, "London morning (10:00-12:59 server)"),
                (13, 16, "London afternoon (13:00-15:59 server)"), (16, 19, "New York open (16:00-18:59 server)"),
                (19, 24, "late New York (19:00-23:59 server)")]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# derived, trader-readable measures: key -> (what it measures, text if the missed questions are higher, if lower)
TEXT_DIRECTIONAL = {     # comparative on purpose: the numbers beside each sentence give the actual levels
    "atr_rel": ("volatility (ATR vs its usual)", "in higher volatility", "in quieter markets"),
    "h1": ("H1 structure in the trade's direction", "with more H1 trend support",
           "with less H1 trend support (more against the H1 trend)"),
    "ema200": ("distance from the 200 EMA in the trade's direction (ATRs)",
               "when price is further from the 200 EMA in the trade's direction (more extended)",
               "when price is further against the trade from the 200 EMA (against the bigger trend)"),
    "avg": ("stretch from the session average in the trade's direction (ATRs)",
            "when price has already moved further in the trade's direction from the session average (less room left)",
            "when price sits further against the trade from the session average"),
    "range": ("position in the day's range in the trade's direction (0-1)",
              "closer to the day's extreme in the trade's direction (less room left)",
              "closer to the far side of the day's range"),
    "rsi": ("RSI(14) lean in the trade's direction", "when RSI leans further in the trade's direction",
            "when RSI leans more against the trade"),
    "round": ("distance to a $50 round number (ATRs)", "further from round numbers", "closer to a $50 round number"),
    "pd_level": ("distance to yesterday's high or low (ATRs)", "further from yesterday's high/low",
                 "closer to yesterday's high or low"),
    "spread": ("spread vs candle size", "when the spread is wider for the candles", "when the spread is tighter"),
}
TEXT_NEUTRAL = dict(TEXT_DIRECTIONAL, **{
    "h1": ("H1 trend strength", "in a stronger H1 trend", "in a flatter H1"),
    "ema200": ("distance from the 200 EMA (ATRs)", "further from the 200 EMA", "closer to the 200 EMA"),
    "avg": ("distance from the session average (ATRs)", "further from the session average",
            "closer to the session average"),
    "range": ("distance from the middle of the day's range", "nearer the day's high or low",
              "nearer the middle of the day's range"),
    "rsi": ("RSI(14) distance from 50", "when RSI is more stretched", "when RSI is nearer 50"),
})


# smallest real-world gap worth a sentence, per measure (on top of the effect size)
MIN_GAP = {"atr_rel": 0.1, "h1": 0.3, "ema200": 0.5, "avg": 0.3, "range": 0.08, "rsi": 0.03, "round": 0.3,
           "pd_level": 0.5, "spread": 0.03}
TRAP_ALL = "Traps (all setups)"


def _measures(X, cols, sign, directional):
    """Trader-readable measures per question; `sign` (+1 buy / -1 sell, scalar or per question) turns trend and
    stretch measures into "in the trade's direction"."""
    g = lambda k: X[:, cols[k]].astype(float)          # noqa: E731
    sign = np.broadcast_to(np.asarray(sign, float), (len(X),))
    out = {"atr_rel": g("atr_rel"), "round": np.abs(g("round_big_dist")),
           "pd_level": np.minimum(np.abs(g("pdh_dist")), np.abs(g("pdl_dist"))), "spread": g("spread_atr")}
    if directional:
        out.update(h1=g("h1_structure") * sign, ema200=g("dist_ema200") * sign, avg=g("sess_avg_dist") * sign,
                   range=np.where(sign > 0, g("day_range_pos"), 1 - g("day_range_pos")), rsi=(g("rsi14") - 0.5) * sign)
    else:
        out.update(h1=np.abs(g("h1_structure")), ema200=np.abs(g("dist_ema200")), avg=np.abs(g("sess_avg_dist")),
                   range=np.abs(g("day_range_pos") - 0.5), rsi=np.abs(g("rsi14") - 0.5))
    return out


def _effect(a, b, min_n=8):
    a, b = a[np.isfinite(a)], b[np.isfinite(b)]
    if len(a) < min_n or len(b) < min_n:
        return 0.0, None, None
    sd = np.sqrt((a.var() + b.var()) / 2)
    return (float((a.mean() - b.mean()) / sd) if sd > 1e-9 else 0.0), float(a.mean()), float(b.mean())


def _contrast(meas, hit, other, texts, label_hit="the ones it misses", label_other="the ones it gets right"):
    """Sentences for the measures that differ most between two sets of questions."""
    found = []
    for k, v in meas.items():
        d, ma, mb = _effect(v[hit], v[other])
        if abs(d) >= D_PATTERN and abs(ma - mb) >= MIN_GAP.get(k, 0):
            what, hi, lo = texts[k]
            found.append((abs(d), k, f"{hi if d > 0 else lo} ({what}: {ma:.2f} for {label_hit} vs {mb:.2f} for "
                                     f"{label_other})", d))
    found.sort(reverse=True)
    return found[:3]


def _share_pattern(values, hit, other, names, what):
    """A category (time window, weekday, year) where the missed questions bunch up."""
    if hit.sum() < 8 or other.sum() < 8:
        return None
    best = None
    for key in sorted(set(values[hit])):
        sh, so = np.mean(values[hit] == key), np.mean(values[other] == key)
        lift = sh / max(so, 0.02)
        if sh >= 0.3 and lift >= 1.4 and (best is None or lift > best[0]):
            best = (lift, key, sh, so)
    if not best:
        return None
    lift, key, sh, so = best
    return f"{round(100 * sh)}% of the ones it misses are {what} {names(key)}, vs {round(100 * so)}% of the ones it gets right"


def _slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def make_report(verbose=False):
    quiz = Q._load_json(Q.QUIZ, None)
    if not quiz or not Q.QX.exists() or not Q.PROGRESS.exists():
        return None
    pr = np.load(Q.PROGRESS)
    if str(pr["built"]) != quiz["built"]:
        return None
    qs = quiz["questions"]
    n = len(qs)
    X = np.load(Q.QX)
    cols = {c: k for k, c in enumerate(quiz["features"])}
    right, asked, done = pr["right"], pr["asked"], pr["done"].astype(bool)
    wrong = pr["wrong"] if "wrong" in pr else np.zeros((n, 3), int)
    exam_pick = pr["exam_pick"] if "exam_pick" in pr else np.full(n, -1)
    stuck = pr["stuck"].astype(bool) if "stuck" in pr else (~done & (asked > 0) & (right < 0.3 * np.maximum(asked, 1)))
    ans = np.array([Q.ACTIONS.index(q["answer"]) for q in qs])
    is_prac = np.array([q["set"] == "practice" for q in qs])
    is_exam = ~is_prac
    acc = np.where(asked > 0, right / np.maximum(asked, 1), np.nan)
    hours = np.array([int(q["time"][11:13]) for q in qs])
    years = np.array([int(q["time"][:4]) for q in qs])
    wday = np.array([datetime.strptime(q["time"][:10], "%Y-%m-%d").weekday() for q in qs])
    names = np.array([Q.setup_name(q["setup"], q.get("trap")) for q in qs])
    setups = np.array([q["setup"] for q in qs])
    traps = np.array([bool(q.get("trap")) for q in qs])
    sign_q = np.array([-1.0 if Q.PRO_SETUPS.get(q["setup"], ("buy",))[0] == "sell" else 1.0 for q in qs])

    def members(name):
        return traps.copy() if name == TRAP_ALL else names == name

    groups = []
    for name in sorted(set(names)) + ([TRAP_ALL] if traps.any() else []):
        m = members(name)
        pm, em = m & is_prac, m & is_exam & (exam_pick >= 0)
        if pm.sum() == 0:
            continue
        q0 = qs[int(np.flatnonzero(m)[0])]
        w = wrong[pm].sum(0)
        main_wrong = Q.ACTIONS[int(w.argmax())] if w.sum() else None
        g = {"name": name, "setup": "trap_all" if name == TRAP_ALL else q0["setup"], "trap": bool(q0.get("trap")),
             "answer": q0["answer"],
             "practice": int(pm.sum()), "acc": float(np.nanmean(acc[pm])) if np.isfinite(acc[pm]).any() else None,
             "finished": float(done[pm].mean()), "stuck": int((stuck & pm).sum()),
             "exam": float((exam_pick[em] == ans[em]).mean()) if em.sum() else None, "exam_n": int(em.sum()),
             "main_wrong": main_wrong, "main_wrong_share": float(w.max() / w.sum()) if w.sum() else 0.0}
        a = g["acc"] if g["acc"] is not None else 0.0
        e = g["exam"] if g["exam"] is not None and g["exam_n"] >= 5 else a
        g["score"] = 0.4 * (1 - a) + 0.3 * (1 - e) + 0.3 * (1 - g["finished"])
        groups.append(g)
    big = [g for g in groups if g["practice"] >= MIN_GROUP] or [g for g in groups if g["practice"] >= 5]
    weak = sorted(big, key=lambda g: -g["score"])[:TOP]

    # patterns for each weak spot, and the trap check
    for g in weak:
        m = members(g["name"]) & is_prac & (asked > 0)
        idx = np.flatnonzero(m)
        directional = g["setup"] == "trap_all" or g["setup"] in Q.PRO_SETUPS
        texts = TEXT_DIRECTIONAL if directional else TEXT_NEUTRAL
        meas = _measures(X[idx], cols, sign_q[idx], directional)
        med = np.nanmedian(acc[idx]) if len(idx) else 0
        hit = (~done[idx]) | (acc[idx] < med)
        other = ~hit
        found = _contrast(meas, hit, other, texts)
        pats = [t for _, _, t, _ in found]
        g["pattern_keys"] = [f"{k}:{'higher' if d > 0 else 'lower'}" for _, k, _, d in found]
        windows = np.array([next(k for k, (a, b, _) in enumerate(HOUR_WINDOWS) if a <= h < b) for h in hours[idx]])
        for vals, fn, what in ((windows, lambda k: HOUR_WINDOWS[k][2], "in the"),
                               (wday[idx], lambda d: DAYS[d], "on a"), (years[idx], str, "from")):
            s_ = _share_pattern(vals, hit, other, fn, what)
            if s_:
                pats.append(s_)
                g["pattern_keys"].append({"in the": "time", "on a": "weekday", "from": "year"}[what])
        g["patterns"] = pats
        g["missed_n"], g["right_n"] = int(hit.sum()), int(other.sum())
        worst = idx[np.argsort(acc[idx])][:5]
        g["examples"] = [{"id": int(i) + 1, "time": qs[i]["time"], "right": int(right[i]), "asked": int(asked[i]),
                          "finished": bool(done[i])} for i in worst]
        g["ids"] = [int(i) + 1 for i in idx[~done[idx]]][:2000]
        # traps vs winners of the same setup: can the chart tell them apart at all?
        g["trap_check"] = None
        if directional:
            same = (setups != "wait") if g["setup"] == "trap_all" else (setups == g["setup"])
            win = np.flatnonzero(same & ~traps)
            trp = np.flatnonzero(same & traps)
            if len(win) >= 5 and len(trp) >= 5:
                both = np.concatenate([trp, win])
                mm = _measures(X[both], cols, sign_q[both], True)
                is_t = np.arange(len(both)) < len(trp)
                ds = [abs(_effect(v[is_t], v[~is_t])[0]) for v in mm.values()]
                if max(ds) < D_SEPARATE:
                    g["trap_check"] = (f"Nothing on the chart separates this setup's traps ({len(trp)}) from its winners "
                                       f"({len(win)}): the biggest difference is only {max(ds):.2f} standard deviations. "
                                       "The quiz can't learn these from the chart; it needs information it doesn't have "
                                       "yet (news times, volume, a higher timeframe).")
                else:
                    sep = _contrast(mm, is_t, ~is_t, TEXT_DIRECTIONAL, "traps", "winners")
                    if sep:
                        g["trap_check"] = "Traps differ from winners: they happen more " + "; more ".join(t for _, _, t, _ in sep) + "."
                    else:
                        g["trap_check"] = ("Traps and winners show no clear, sizeable difference on the measures checked "
                                           "here: hard to learn from the chart; more history helps.")
        g["fix"] = _fixes(g)

    pol = Q.load_policy()
    exam = (pol.meta.get("exam") if pol else None) or {}
    summary = {"questions": n, "practice": int(is_prac.sum()), "finished": int(done[is_prac].sum()),
               "stuck": int((stuck & is_prac).sum()), "exam_pct": exam.get("pct"), "exam_right": exam.get("right"),
               "exam_total": exam.get("total"), "built": quiz["built"]}
    report = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "summary": summary,
              "weak": weak, "groups": sorted(groups, key=lambda g: -g["practice"])}
    md = _markdown(report)
    Q._write(REPORT_JSON, report)
    REPORT_MD.write_text(md, encoding="utf-8")
    _write_skill(report)
    if verbose:
        print(md)
    return report


def _fixes(g):
    out = []
    keys = set(g.get("pattern_keys", []))
    directional = g["setup"] != "wait"
    if (g.get("trap_check") or "").startswith("Nothing on the chart"):
        out.append("Treat this setup as a coin flip until the quiz gets more information: rebuild with more history, or "
                   "add an input it lacks (news times, volume, higher timeframe).")
    if directional and ({"h1:lower", "ema200:lower"} & keys):
        out.append("Favour it with the H1 trend: the misses have less trend support.")
    if directional and ({"avg:higher", "range:higher", "ema200:higher"} & keys):
        out.append("Don't chase: the misses come when price has already travelled further in the trade's direction.")
    if "atr_rel:higher" in keys:
        out.append("Be careful in higher volatility (skip or size down).")
    if "atr_rel:lower" in keys:
        out.append("It struggles in quiet markets; the move may lack follow-through there.")
    if "time" in keys:
        out.append("Be careful in the time window named above; consider it a no-trade window for this setup.")
    if "year" in keys:
        out.append("The misses bunch up in one year: the market behaved differently then (a regime change); more "
                   "history from similar years would help.")
    if g.get("exam") is not None and g.get("acc") is not None and g["exam_n"] >= 5 and g["acc"] - g["exam"] > 0.25:
        out.append("It memorised these more than it learned them (practice far above exam): build a bigger quiz.")
    if g["finished"] < 0.9:
        out.append("Work on these questions (Weak spots -> Work on these); it loops until they are finished.")
    if g["main_wrong"] and g["main_wrong_share"] >= 0.7:
        out.append(f"Its mistake is almost always {ACT_NAME[g['main_wrong']]}: the pro answer here is "
                   f"{ACT_NAME[g['answer']]}.")
    return out or ["No clear pattern yet: let it keep looping, or rebuild with more history."]


def _pct(v):
    return "–" if v is None else f"{round(100 * v)}%"


def _markdown(r):
    s = r["summary"]
    lines = [f"# Quiz weak-spot report ({r['generated'][:16].replace('T', ' ')} UTC)", "",
             f"Quiz built {s['built'][:16].replace('T', ' ')}: {s['questions']:,} questions, {s['practice']:,} practice, "
             f"{s['finished']:,} finished, {s['stuck']:,} stuck. Exam: "
             + (f"{s['exam_right']:,}/{s['exam_total']:,} ({s['exam_pct']}%)" if s.get("exam_total") else "not taken yet") + ".",
             "", "## All groups", "", "| Setup | Pro answer | Practice | Right | Finished | Stuck | Exam | Usual mistake |",
             "|---|---|---|---|---|---|---|---|"]
    for g in r["groups"]:
        mw = f"{ACT_NAME[g['main_wrong']]} ({round(100 * g['main_wrong_share'])}%)" if g["main_wrong"] else "–"
        lines.append(f"| {g['name']} | {ACT_NAME[g['answer']]} | {g['practice']} | {_pct(g['acc'])} | {_pct(g['finished'])} | "
                     f"{g['stuck']} | {_pct(g['exam'])} ({g['exam_n']}) | {mw} |")
    lines += ["", "## Weak spots", ""]
    for k, g in enumerate(r["weak"], 1):
        lines += [f"### {k}. {g['name']} (pro answer {ACT_NAME[g['answer']]})",
                  f"Practice right {_pct(g['acc'])}, finished {_pct(g['finished'])}, stuck {g['stuck']}, exam "
                  f"{_pct(g['exam'])} of {g['exam_n']}. Compared {g['missed_n']} it misses with {g['right_n']} it gets right.",
                  "", "What the misses have in common:"]
        lines += [f"- {p}" for p in g["patterns"]] or ["- nothing stands out yet"]
        if g.get("trap_check"):
            lines += ["", f"Trap check: {g['trap_check']}"]
        lines += ["", "Suggested:"] + [f"- {x}" for x in g["fix"]]
        lines += ["", "Examples (hardest): " + ", ".join(f"Q{e['id']} {e['time']} ({e['right']}/{e['asked']})"
                                                         for e in g["examples"]), ""]
    cant = [g["name"] for g in r["weak"] if (g.get("trap_check") or "").startswith("Nothing on the chart")]
    nothing = [g["name"] for g in r["weak"] if not g["patterns"]]
    lines += ["## For Claude", "",
              "Read the weak spots above and write skill pages for what you can figure out "
              "(.claude/skills/quiz-weak-spots/references/claude-<topic>.md), plus any builder or input changes they point to.",
              f"- Can't be told apart on the chart: {', '.join(cant) or 'none'}",
              f"- Weak with no pattern found: {', '.join(nothing) or 'none'}", ""]
    return "\n".join(lines)


def _write_skill(r):
    SKILL_DIR.mkdir(parents=True, exist_ok=True)
    ref = SKILL_DIR / "references"
    ref.mkdir(exist_ok=True)
    keep = set()
    for g in r["weak"]:
        slug = _slug(g["name"])
        keep.add(f"{slug}.md")
        pro = ("A setup appeared but its stop was hit within the hour. Pros skip a setup when the context is wrong: "
               "against the higher-timeframe trend, already stretched, or into a nearby level."
               if g["setup"] == "trap_all" else Q.PRO_SETUPS.get(g["setup"], ("", Q.WAIT_TEXT))[1])
        body = [f"# Weak spot: {g['name']}", "",
                f"Pro answer: **{ACT_NAME[g['answer']]}**. {'This is a trap: the setup appeared but failed within the hour. ' if g['trap'] else ''}"
                f"What pros look for: {pro}", "",
                f"- Practice right {_pct(g['acc'])}, finished {_pct(g['finished'])}, stuck {g['stuck']}",
                f"- Exam (unseen): {_pct(g['exam'])} of {g['exam_n']}",
                f"- Usual mistake: {ACT_NAME[g['main_wrong']] if g['main_wrong'] else '–'}", "", "## What the misses have in common"]
        body += [f"- {p}" for p in g["patterns"]] or ["- nothing stands out yet"]
        if g.get("trap_check"):
            body += ["", "## Traps vs winners", g["trap_check"]]
        body += ["", "## What to do"] + [f"- {x}" for x in g["fix"]]
        body += ["", "## Examples", *[f"- Q{e['id']} ({e['time']} server time): right {e['right']}/{e['asked']}"
                                      + (", finished" if e["finished"] else "") for e in g["examples"]]]
        (ref / f"{slug}.md").write_text("\n".join(body) + "\n", encoding="utf-8")
    for old in ref.glob("*.md"):                   # drop pages for spots that are no longer weak; keep Claude's pages
        if old.name not in keep and not old.name.startswith("claude-"):
            old.unlink()
    claude_pages = sorted(p.name for p in ref.glob("claude-*.md"))
    s = r["summary"]
    rows = [f"| {g['name']} | {ACT_NAME[g['answer']]} | {_pct(g['acc'])} | {_pct(g['exam'])} | "
            f"[{_slug(g['name'])}.md](references/{_slug(g['name'])}.md) |" for g in r["weak"]]
    text = f"""---
name: quiz-weak-spots
description: Where the Trading Bot's quiz agent gets stuck - the setups and situations it keeps getting wrong, what those charts have in common (time of day, volatility, H1 trend, chasing, levels), whether the chart can separate traps from winners, and what to do about each. Rewritten automatically by the quiz; pages named claude-*.md are written by Claude from the pasted report. Use this whenever the user asks why the quiz agent fails, what it is stuck on, which setups or situations to distrust, or how to improve the quiz.
---

# Quiz weak spots (updated {r['generated'][:16].replace('T', ' ')} UTC)

Quiz: {s['practice']:,} practice questions, {s['finished']:,} finished, {s['stuck']:,} stuck; exam {s['exam_pct'] if s.get('exam_pct') is not None else '–'}%.

| Weak spot | Pro answer | Practice right | Exam | Page |
|---|---|---|---|---|
{chr(10).join(rows) if rows else '| none yet | | | | |'}

How to use this:
- Before trusting the quiz agent's "What would you do now?" or second opinion, check whether the live chart matches a
  weak spot's pattern. If it does, treat its answer as a coin flip.
- Each page lists what the missed charts have in common and a suggested fix. "Nothing on the chart separates" means
  the quiz needs new information (news times, volume, higher timeframe), not more training.
- The full report is in data/quiz_report.md; the Quiz tab's "Copy report for Claude" button copies it for pasting.
{('- Notes written by Claude: ' + ', '.join(f'[{p}](references/{p})' for p in claude_pages)) if claude_pages else ''}
"""
    (SKILL_DIR / "SKILL.md").write_text(text, encoding="utf-8")


def main():
    r = make_report(verbose=True)
    if r is None:
        raise SystemExit("No quiz progress yet: build a quiz and run it first (Quiz tab).")


if __name__ == "__main__":
    main()
