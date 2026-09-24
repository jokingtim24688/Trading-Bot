"""Quiz school: the bot answers "what do you do here?" on real gold situations and learns from points (reinforcement learning).

    python -m agent.quiz build --questions 1000   # find the questions in your downloaded M1 history (40 to 10,000)
    python -m agent.quiz train                    # quiz the agent until it gets every question right 5 times in a row

Where the questions come from
    There is no public record of individual professional gold trades, so the quiz is built from real XAUUSD candles:
    moments where a textbook professional setup appeared (agent/pro.py: liquidity sweep, opening-range breakout,
    session-average reclaim, fair value gap, prior-day level test) AND a trade taken the way a pro would take it
    (stop beyond the sweep wick or 1.5 ATR, target 2R) reached its target cleanly: within 3 hours and without first
    going more than 60% of the way to its stop. Those have the answer buy/sell. Clean no-trade spots are mixed in
    (middle of the day's range, no level, no setup, and neither a buy nor a sell would have been a clean trade): the
    answer there is "stay out".
    Questions are at least an hour apart. A question is removed when a near-twin, or 4 of its 5 closest look-alikes,
    has the opposite answer: no one (human or model) could tell them apart from the chart. 75% practice, 25% exam the agent never trains on.

How it learns (reinforcement learning)
    The agent sees what a trader would see at that candle: the model's 49 indicator inputs (including the pro levels)
    plus the chart itself (the last 40 candles and a 90-candle outline, 178 numbers), and picks buy, sell or stay out
    from its policy: a small neural network (227 inputs -> 64 tanh units, growing to 512 if needed -> 3, softmax). Points are its reward and
    its only goal:
        right answer  +10 points
        wrong way     -10 points   (bought a sell, or sold a buy)
        traded when it should have stayed out   -5 points
        stayed out when there was a good trade  -3 points
    After each answer the policy is nudged toward actions that earned more points than it usually earns on that
    question (REINFORCE with a per-question baseline), so a right answer on a question it keeps missing is a big reward. 5% of the time it tries a random answer, so an answer it has written off still gets tried and
    can still earn points; without that, a question it is sure it knows (wrongly) can stay stuck forever.
    A question counts as mastered once it has been answered right 5 times in a row; mastered questions keep coming up
    so it doesn't forget them, and unfinished questions are asked 2 extra times per round. It never gives up on its
    own: when no new question is finished for 100 rounds it asks the stuck ones 7 extra times with 3x bigger learning
    steps, then doubles its network (64 -> 512 units, keeping what it learned), then shakes up the stuck questions and
    loops again, until every question is finished or you press Stop. Then it sits the exam and writes its lessons to
    the quiz-lessons skill. "Continue" picks up the saved agent and progress; "focus" works only on the questions you
    pick (finished ones are left out).

Files: data/quiz.json (questions), data/quiz_x.npy (inputs), data/quiz_bars.npy + data/quiz_times.npy (charts),
models/quiz_policy.json (the trained agent), data/quiz_state.json (live progress for the app).
"""
import argparse
import json
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .features import atr, build_features
from .pro import SETUP_NAMES

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
QUIZ = DATA / "quiz.json"
QX = DATA / "quiz_x.npy"
QBARS = DATA / "quiz_bars.npy"
QTIMES = DATA / "quiz_times.npy"
STATE = DATA / "quiz_state.json"
CONTROL = DATA / "quiz_control.json"
POLICY = ROOT / "models" / "quiz_policy.json"
PROGRESS = DATA / "quiz_progress.npz"

ACTIONS = ("buy", "sell", "wait")
POINTS = {"right": 10, "wrong_way": -10, "traded_should_wait": -5, "missed_trade": -3}
MASTERY = 5                       # correct answers in a row per question
HORIZON = 240                     # candles a quiz trade may take to resolve (4 hours)
CLEAN_MINUTES = 180               # a clean pro winner reaches its target within 3 hours...
CLEAN_MAE = 0.6                   # ...without first going more than 60% of the way to its stop
BEFORE, AFTER = 90, 60            # chart candles before the question and revealed after it
EXPLORE = 0.05                    # share of answers picked at random...
EXPLORE_MAX = 0.5                 # ...rising to half the time on a question it keeps missing
EXTRA = 2                         # unfinished questions are asked this many extra times per round (7 more once stuck)
HIDDEN = 64
MAX_QUESTIONS = 100_000
SESSION = (10, 20)                # server hours pros are active in (London open to late New York)

PRO_SETUPS = {
    "sweep_long": ("buy", "Price ran the stops under the recent low and closed back above it. Pros buy the failed breakdown "
                          "with a stop under the wick."),
    "sweep_short": ("sell", "Price ran the stops above the recent high and closed back below it. Pros sell the failed breakout "
                            "with a stop above the wick."),
    "orb_long": ("buy", "Price broke out above the opening range and held. Pros go with the breakout."),
    "orb_short": ("sell", "Price broke down below the opening range and held. Pros go with the breakdown."),
    "avg_reclaim_long": ("buy", "In an H1 uptrend, price dipped under the session average and reclaimed it. Pros buy the reclaim."),
    "avg_reclaim_short": ("sell", "In an H1 downtrend, price popped over the session average and lost it. Pros sell the rejection."),
    "fvg_bull": ("buy", "A strong push up left a bullish fair value gap with the H1 trend up. Pros buy in the trend direction."),
    "fvg_bear": ("sell", "A strong push down left a bearish fair value gap with the H1 trend down. Pros sell in the trend direction."),
    "pdl_test": ("buy", "Price tested yesterday's low and held it. Pros buy the defended level with a stop under it."),
    "pdh_test": ("sell", "Price tested yesterday's high and was rejected. Pros sell the defended level with a stop above it."),
    "asia_sweep_long": ("buy", "London/New York pushed under the Asian range low, ran the stops there, and came back inside. "
                               "Pros buy the raid of the Asian low."),
    "asia_sweep_short": ("sell", "London/New York pushed over the Asian range high, ran the stops there, and came back inside. "
                                 "Pros sell the raid of the Asian high."),
    "trend_pullback_long": ("buy", "The H1 trend is up and price pulled back under the 20 EMA, then closed back above it. "
                                   "Pros buy the pullback in the trend."),
    "trend_pullback_short": ("sell", "The H1 trend is down and price bounced over the 20 EMA, then closed back below it. "
                                     "Pros sell the bounce in the trend."),
    "pdh_break": ("buy", "Price broke above yesterday's high and held there with the H1 trend up. Pros go with the acceptance "
                         "above the level."),
    "pdl_break": ("sell", "Price broke below yesterday's low and held there with the H1 trend down. Pros go with the acceptance "
                          "below the level."),
    "fade_stretch_long": ("buy", "Price is stretched more than 4 ATR under the session average and just printed a strong "
                                 "up candle. Pros fade the overextension back toward the average."),
    "fade_stretch_short": ("sell", "Price is stretched more than 4 ATR over the session average and just printed a strong "
                                   "down candle. Pros fade the overextension back toward the average."),
}
QUIZ_NAMES = {
    "asia_sweep_long": "Asian low raided", "asia_sweep_short": "Asian high raided",
    "trend_pullback_long": "H1 uptrend pullback", "trend_pullback_short": "H1 downtrend bounce",
    "pdh_break": "Held above prior-day high", "pdl_break": "Held below prior-day low",
    "fade_stretch_long": "Fade stretch below average", "fade_stretch_short": "Fade stretch above average",
}
WAIT_NAME = "No setup (stay out)"
WAIT_TEXT = ("Price is in the middle of the day's range with no key level, sweep or breakout nearby. Pros stay out here: "
             "neither a buy nor a sell with the same stop would have been a clean trade.")
TRAP_SHARE, WAIT_SHARE = 0.15, 0.20       # the rest are clean pro trades
TRAP_MINUTES = 60                          # a trap: the setup's stop was hit within the hour
SPACINGS = (60, 30, 15)                    # minutes between questions; tightens only when more are needed


def setup_name(key: str, trap: bool = False) -> str:
    if key == "wait":
        return WAIT_NAME
    name = QUIZ_NAMES.get(key) or SETUP_NAMES.get(key, key)
    return f"{name} (trap)" if trap else name


def group_name(q: dict) -> str:
    """How results are grouped: by setup, with every trap question in one group."""
    return "Traps (setup failed: stay out)" if q.get("trap") else setup_name(q["setup"])


def explain(q: dict) -> str:
    if q["setup"] == "wait":
        return WAIT_TEXT
    t = q.get("trade")
    if q.get("trap"):
        side = PRO_SETUPS[q["setup"]][0]
        text = (f"This looks like a {setup_name(q['setup'])} {side}, but it failed: a {side} here hit its stop"
                + (f" {t['minutes']} minutes later" if t else " quickly") + ". The lesson: skip it in this context.")
        return text
    text = PRO_SETUPS[q["setup"]][1]
    if t:
        text += (f" Entry {t['entry']:.2f}, stop {t['stop']:.2f}, target {t['target']:.2f} (2R): it reached the target "
                 f"{t['minutes']} minutes later.")
    return text


def _load_json(p: Path, default):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return default


def _write(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj))
    tmp.replace(p)


# ---------------------------------------------------------------- building the questions

def _first(cond: pd.Series) -> pd.Series:
    return cond & ~cond.shift(1, fill_value=False)


def _candidates(f: pd.DataFrame) -> dict[str, np.ndarray]:
    """Candle positions where each pro setup first appears (in session hours), plus quiet no-setup spots."""
    h1 = f["h1_structure"]
    sa = f["sess_avg_dist"]
    gap = f["fvg_net10"].diff()
    pdl, pdh = f["pdl_dist"], f["pdh_dist"]
    alo, ahi = f["asia_lo_dist"], f["asia_hi_dist"]
    e20 = f["dist_ema20"]
    conds = {
        "sweep_long": f["sweep_long"].eq(1) & f["sweep_long"].shift(1).eq(0),
        "sweep_short": f["sweep_short"].eq(1) & f["sweep_short"].shift(1).eq(0),
        "orb_long": _first((f["lon_or_pos"] > 0.2) | (f["ny_or_pos"] > 0.2)),
        "orb_short": _first((f["lon_or_pos"] < -0.2) | (f["ny_or_pos"] < -0.2)),
        "avg_reclaim_long": (sa > 0) & (sa.shift(1) < 0) & (h1 >= 1),
        "avg_reclaim_short": (sa < 0) & (sa.shift(1) > 0) & (h1 <= -1),
        "fvg_bull": (gap >= 1) & (h1 >= 1),
        "fvg_bear": (gap <= -1) & (h1 <= -1),
        "pdl_test": pdl.between(0, 0.4) & (f["body"] > 0.2) & (pdl.shift(3) > 0.8),
        "pdh_test": pdh.between(-0.4, 0) & (f["body"] < -0.2) & (pdh.shift(3) < -0.8),
        "asia_sweep_long": (alo > 0.1) & (alo.shift(1) <= 0.1) & (alo.rolling(15).min() < -0.3),
        "asia_sweep_short": (ahi < -0.1) & (ahi.shift(1) >= -0.1) & (ahi.rolling(15).max() > 0.3),
        "trend_pullback_long": (h1 >= 2) & (e20 > 0) & (e20.shift(1) <= 0) & (f["dist_ema200"] > 0) & (f["body"] > 0),
        "trend_pullback_short": (h1 <= -2) & (e20 < 0) & (e20.shift(1) >= 0) & (f["dist_ema200"] < 0) & (f["body"] < 0),
        "pdh_break": _first(pdh > 0.3) & (h1 >= 1),
        "pdl_break": _first(pdl < -0.3) & (h1 <= -1),
        "fade_stretch_long": (sa < -4) & (f["body"] > 0.5),
        "fade_stretch_short": (sa > 4) & (f["body"] < -0.5),
    }
    hours = f.index.hour
    ok = ((hours >= SESSION[0]) & (hours < SESSION[1])) & f.notna().all(axis=1).to_numpy()
    out = {k: np.flatnonzero(v.fillna(False).to_numpy() & ok) for k, v in conds.items()}
    quiet = ((f["day_range_pos"].between(0.35, 0.65)) & (f["sweep_long"] == 0) & (f["sweep_short"] == 0)
             & (f["lon_or_pos"] == 0) & (f["ny_or_pos"] == 0) & (f["sess_avg_dist"].abs().between(0.5, 2.5))
             & (f["round_big_dist"].abs() > 1) & (f["pdh_dist"].abs() > 2) & (f["pdl_dist"].abs() > 2))
    out["wait"] = np.flatnonzero(quiet.fillna(False).to_numpy() & ok)
    return out


def _outcomes(df_np, idx: np.ndarray, side: str, sd: np.ndarray, spread: np.ndarray):
    """All pro-style trades (target 2R) walked forward together. Returns won, minutes, worst move against (R), stop,
    target and entry arrays."""
    o, h, l, c = df_np
    n = len(c)
    sp = spread[idx]
    entry = c[idx] + sp if side == "buy" else c[idx]
    stop = entry - sd if side == "buy" else entry + sd
    target = entry + 2 * sd if side == "buy" else entry - 2 * sd
    done = np.zeros(len(idx), bool)
    won = np.zeros(len(idx), bool)
    mins = np.full(len(idx), HORIZON)
    mae = np.zeros(len(idx))
    for k in range(1, HORIZON + 1):
        j = np.minimum(idx + k, n - 1)
        act = ~done & (idx + k < n)
        if not act.any():
            break
        if side == "buy":
            adverse = (entry - l[j]) / sd
            hit_s, hit_t = l[j] <= stop, h[j] >= target
        else:
            adverse = (h[j] + sp - entry) / sd
            hit_s, hit_t = h[j] + sp >= stop, l[j] + sp <= target
        mae = np.where(act, np.maximum(mae, adverse), mae)
        ns, nt = act & hit_s, act & hit_t & ~hit_s
        won |= nt
        mins[ns | nt] = k
        done |= ns | nt
    return won, mins, mae, stop, target, entry


def _stop_dist(kind, idx, df_np, a, spread):
    if kind.startswith("sweep") or kind.startswith("asia_sweep"):     # stop just beyond the sweep's wick
        o, h, l, c = df_np
        lo = np.min(np.stack([l[idx - k] for k in range(5)]), 0)
        hi = np.max(np.stack([h[idx - k] for k in range(5)]), 0)
        sd = (c[idx] + spread[idx] - lo) if PRO_SETUPS[kind][0] == "buy" else (hi - c[idx])
        return np.clip(sd + 0.2 * a[idx], 0.8 * a[idx], 3 * a[idx])
    return 1.5 * a[idx]


def _year_balanced(idx: np.ndarray, quality: np.ndarray, years: np.ndarray) -> np.ndarray:
    """Best examples first, but taking turns across years so no single market period dominates."""
    order = np.lexsort((-quality, years))
    by_year = {}
    for i in order:
        by_year.setdefault(years[i], []).append(i)
    out, lists = [], [v for _, v in sorted(by_year.items())]
    for k in range(max((len(v) for v in lists), default=0)):
        out.extend(v[k] for v in lists if k < len(v))
    return idx[np.array(out, int)] if out else idx[:0]


def _neighbours(Xz: np.ndarray, answers: np.ndarray, k: int = 5, twin: float = 3.0, dup: float = 1.0):
    """For every question: the share of its k closest look-alikes with the same answer, whether a near-twin has the
    other answer (a contradiction), and whether a near-copy with the same answer came earlier (a duplicate)."""
    n = len(Xz)
    same_share = np.ones(n)
    contra = np.zeros(n, bool)
    dupe = np.zeros(n, bool)
    Xf = Xz.astype(np.float32)
    sq = (Xf ** 2).sum(1)
    step = max(100, min(1000, 30_000_000 // max(1, n)))
    for s in range(0, n, step):
        blk = Xf[s:s + step]
        d2 = sq[s:s + step, None] + sq[None, :] - 2 * blk @ Xf.T
        rows = np.arange(len(blk))
        d2[rows, rows + s] = np.inf
        diff = answers[s:s + step, None] != answers[None, :]
        contra[s:s + step] = ((d2 < twin * twin) & diff).any(1)
        earlier = np.arange(n)[None, :] < (rows + s)[:, None]
        dupe[s:s + step] = ((d2 < dup * dup) & ~diff & earlier).any(1)
        if n > k:
            nn = np.argpartition(d2, k, axis=1)[:, :k]
            same_share[s:s + step] = (answers[nn] == answers[s:s + step, None]).mean(1)
    return same_share, contra, dupe


def build(symbol: str = "XAUUSD", n_questions: int = 40, exam_share: float = 0.25, point: float = 0.01, seed: int = 7):
    from .history import load_bars
    n_questions = int(min(MAX_QUESTIONS, max(34, n_questions)))
    df = load_bars(symbol)
    print(f"looking for pro setups in {len(df):,} candles ({df.index[0]:%Y-%m-%d} -> {df.index[-1]:%Y-%m-%d})...", flush=True)
    f = build_features(df, point)
    a = atr(df, 14).to_numpy()
    df_np = tuple(df[k].to_numpy() for k in ("open", "high", "low", "close"))
    spread = df["spread"].to_numpy(dtype=float) * point
    years = df.index.year.to_numpy()
    cands = _candidates(f)
    rng = np.random.default_rng(seed)
    usable = lambda v: v[(v >= 3000) & (v + HORIZON < len(df)) & (a[v] > 0)]      # noqa: E731

    # score every candidate at once: clean pro winners, traps (quick failures) and clean stay-out spots
    pools = {}                                            # (kind, answer, trap) -> ordered candle positions
    trades = {}                                           # candle -> trade details for the explanation
    print("checking what happened after every candidate...", flush=True)
    for kind, (side, _) in PRO_SETUPS.items():
        idx = usable(cands[kind])
        if not len(idx):
            continue
        sd = _stop_dist(kind, idx, df_np, a, spread)
        won, mins, mae, stop, target, entry = _outcomes(df_np, idx, side, sd, spread)
        clean = won & (mins <= CLEAN_MINUTES) & (mae <= CLEAN_MAE)
        trap = ~won & (mins <= TRAP_MINUTES)
        for mask, is_trap, quality in ((clean, False, (1 - mae) + (1 - mins / CLEAN_MINUTES)), (trap, True, 1 - mins / TRAP_MINUTES)):
            sel = np.flatnonzero(mask)
            pools[(kind, "wait" if is_trap else side, is_trap)] = _year_balanced(idx[sel], quality[sel], years[idx[sel]])
            for k in sel:
                trades[int(idx[k])] = {"minutes": int(mins[k]), "stop": round(float(stop[k]), 2),
                                       "target": round(float(target[k]), 2), "entry": round(float(entry[k]), 2)}
        print(f"  {setup_name(kind)}: {len(idx):,} seen, {int(clean.sum()):,} clean winners, {int(trap.sum()):,} traps",
              flush=True)
    idx = usable(cands["wait"])
    if len(idx):
        sd = 1.5 * a[idx]
        wb, mb, eb, *_ = _outcomes(df_np, idx, "buy", sd, spread)
        ws, ms, es, *_ = _outcomes(df_np, idx, "sell", sd, spread)
        clean_b = wb & (mb <= CLEAN_MINUTES) & (eb <= CLEAN_MAE)
        clean_s = ws & (ms <= CLEAN_MINUTES) & (es <= CLEAN_MAE)
        sel = np.flatnonzero(~clean_b & ~clean_s)
        pools[("wait", "wait", False)] = _year_balanced(idx[sel], rng.random(len(sel)), years[idx[sel]])
        print(f"  {WAIT_NAME}: {len(idx):,} seen, {len(sel):,} clean stay-out spots", flush=True)
    if not any(len(v) for k, v in pools.items() if k[0] != "wait"):
        raise SystemExit("No pro setups found. Download more history (Train tab) and try again.")

    # plan: 65% clean trades (round-robin over setups), 15% traps, 20% stay-out; spread through the plan
    trade_keys = [k for k in pools if not k[2] and k[0] != "wait" and len(pools[k])]
    trap_keys = [k for k in pools if k[2] and len(pools[k])]
    pos = {k: 0 for k in pools}
    occupied = np.zeros(len(df), bool)
    spacing_at = [0]                                      # which of SPACINGS is in use

    def make_plan(count):
        n_trap, n_wait = round(count * TRAP_SHARE), round(count * WAIT_SHARE)
        plan = ([trade_keys[j % len(trade_keys)] for j in range(count - n_trap - n_wait)]
                + ([trap_keys[j % len(trap_keys)] for j in range(n_trap)] if trap_keys else [])
                + [("wait", "wait", False)] * n_wait)
        return [plan[k] for k in rng.permutation(len(plan))]

    def select(plan):
        """Best-first picks for the plan; spacing tightens only when the history runs out of room."""
        taken = []
        while True:
            spacing, missing = SPACINGS[spacing_at[0]], []
            for key in plan:
                got = None
                for k in [key] + [x for x in pools if x[1] == key[1] and x[2] == key[2] and x != key]:   # same answer
                    arr = pools.get(k, [])
                    while pos[k] < len(arr):
                        i = int(arr[pos[k]])
                        pos[k] += 1
                        if not occupied[max(0, i - spacing + 1):i + spacing].any():
                            got = (i, k)
                            break
                    if got:
                        break
                if got is None:
                    missing.append(key)
                    continue
                i, (kind, answer, is_trap) = got
                occupied[i] = True
                taken.append((i, kind, answer, is_trap))
            if not missing or spacing_at[0] == len(SPACINGS) - 1:
                return taken
            spacing_at[0] += 1
            print(f"  {len(missing):,} more needed: allowing questions {SPACINGS[spacing_at[0]]} minutes apart", flush=True)
            plan = missing
            for k in pos:                                   # re-scan with the tighter spacing
                pos[k] = 0

    picks = select(make_plan(int(n_questions * 1.35) + 20))
    if len(picks) < 10:
        raise SystemExit(f"Only found {len(picks)} usable questions. Download more history and try again.")

    # remove contradictions and near-copies (topping up with fresh candidates when many get dropped), and grade the
    # rest by how much their look-alikes agree
    sample = f.dropna().sample(min(50_000, len(f.dropna())), random_state=seed)
    mean, std = sample.mean().to_numpy(), sample.std().replace(0, 1).to_numpy()
    for attempt in range(4):
        X = f.iloc[[p[0] for p in picks]].to_numpy(dtype=np.float32)
        Xz = np.clip(np.nan_to_num((X - mean) / std), -5, 5)
        answers = np.array([p[2] for p in picks])
        print(f"  comparing {len(picks):,} questions with each other...", flush=True)
        same_share, contra, dupe = _neighbours(Xz, answers)
        bad = contra | dupe | (same_share <= 0.2)
        good = int((~bad).sum())
        if good >= n_questions or attempt == 3:
            break
        rate = good / len(picks)
        more = select(make_plan(int((n_questions - good) / max(rate, 0.3) * 1.2) + 20))
        if not more:
            break
        print(f"  {len(picks) - good:,} dropped so far: adding {len(more):,} fresh candidates to replace them", flush=True)
        picks += more
    print(f"  dropped {int((contra | (same_share <= 0.2)).sum()):,} whose look-alikes have the other answer and "
          f"{int((dupe & ~contra).sum()):,} near-copies", flush=True)
    keep = [k for k in rng.permutation(len(picks)) if not bad[k]][:n_questions]
    difficulty = np.where(same_share >= 0.8, "easy", np.where(same_share >= 0.5, "medium", "hard"))

    n = len(keep)
    n_exam = max(3, round(n * exam_share))
    if n - n_exam < 30 and n >= 33:
        n_exam = n - 30
    bars = np.full((n, BEFORE + AFTER, 4), np.nan, dtype=np.float32)
    times = np.zeros((n, BEFORE + AFTER), dtype=np.int64)
    epoch = ((df.index - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1)).to_numpy()
    ohlc = np.stack(df_np, axis=1).astype(np.float32)
    questions = []
    for qid, k in enumerate(keep):
        i, kind, answer, is_trap = picks[k]
        lo, hi = i - BEFORE + 1, min(len(df), i + AFTER + 1)
        bars[qid, : hi - lo] = ohlc[lo:hi]
        times[qid, : hi - lo] = epoch[lo:hi]
        questions.append({"id": qid + 1, "time": str(df.index[i])[:16], "setup": kind, "answer": answer, "trap": bool(is_trap),
                          "trade": trades.get(i) if kind != "wait" else None, "difficulty": str(difficulty[k]),
                          "set": "exam" if qid >= n - n_exam else "practice"})
    DATA.mkdir(exist_ok=True)
    np.save(QX, X[keep])
    np.save(QBARS, bars)
    np.save(QTIMES, times)
    quiz = {"symbol": symbol, "built": datetime.now(timezone.utc).isoformat(timespec="seconds"), "features": list(f.columns),
            "norm": {"mean": np.round(mean, 6).tolist(), "std": np.round(std, 6).tolist()}, "points": POINTS,
            "mastery": MASTERY, "practice": n - n_exam, "exam": n_exam, "questions": questions}
    _write(QUIZ, quiz)
    by = pd.Series([q["answer"] for q in questions]).value_counts().to_dict()
    lv = pd.Series([q["difficulty"] for q in questions]).value_counts().to_dict()
    traps = sum(q["trap"] for q in questions)
    if n < n_questions:
        print(f"  your history only had room for {n:,} clean questions; download more years (Train tab) for more", flush=True)
    print(f"saved {n:,} questions ({n - n_exam:,} practice, {n_exam:,} exam; answers {by}; {traps:,} traps; "
          f"difficulty {lv}; {len({q['setup'] for q in questions} - {'wait'})} pro setup types)", flush=True)
    return quiz


def question_view(qid: int, quiz: dict | None = None) -> dict:
    """One question with its chart, for the app."""
    quiz = quiz or _load_json(QUIZ, None)
    if not quiz or not 1 <= qid <= len(quiz["questions"]):
        return {}
    q = dict(quiz["questions"][qid - 1])
    b = np.load(QBARS, mmap_mode="r")[qid - 1]
    t = np.load(QTIMES, mmap_mode="r")[qid - 1]
    rows = [{"time": int(tt), "open": round(float(r[0]), 2), "high": round(float(r[1]), 2), "low": round(float(r[2]), 2),
             "close": round(float(r[3]), 2)} for r, tt in zip(b, t) if tt > 0]
    q.update(setup_name=setup_name(q["setup"], q.get("trap")), explanation=explain(q), bars=rows[:BEFORE], after=rows[BEFORE:])
    return q


# ---------------------------------------------------------------- the agent (policy) and its reward

def points_for(action: str, answer: str) -> tuple[int, str]:
    if action == answer:
        return POINTS["right"], "right"
    if answer == "wait":
        return POINTS["traded_should_wait"], "should have stayed out"
    if action == "wait":
        return POINTS["missed_trade"], "missed a good trade"
    return POINTS["wrong_way"], "wrong way"


CHART_BARS = 40                   # candles the agent sees in full (open/high/low/close)
CHART_LONG = 18                   # plus every 5th close over the last 90 candles for context
CHART_DIM = 4 * CHART_BARS + CHART_LONG
MAX_HIDDEN = 512


def chart_features(ohlc) -> np.ndarray:
    """The chart itself as inputs: the last 40 candles and a 90-candle outline, in ATRs from the current close.
    Two questions whose indicator readings match almost never have the same candles, so this is what lets the agent
    tell look-alikes apart."""
    a = np.asarray(ohlc, float)
    a = a[~np.isnan(a).any(1)][-90:]
    if len(a) < CHART_BARS + 14:
        return np.zeros(CHART_DIM)
    atr = max(float(np.mean(a[-14:, 1] - a[-14:, 2])), 1e-6)
    ref = a[-1, 3]
    last = (a[-CHART_BARS:] - ref) / atr
    outline = (a[::-1, 3][::5][:CHART_LONG][::-1] - ref) / atr
    outline = np.pad(outline, (CHART_LONG - len(outline), 0))
    return np.clip(np.concatenate([last.T.ravel(), outline]) / 5, -3, 3)


class QuizPolicy:
    """Small neural network: indicator inputs + the chart -> 64..512 tanh units -> buy/sell/stay out.
    Its objective is the points it earns: nothing else."""

    def __init__(self, features, mean, std, params=None, meta=None, seed=1, chart=CHART_DIM):
        self.features = list(features)
        self.mean, self.std = np.asarray(mean, float), np.asarray(std, float)
        self.chart = chart
        d = len(self.features) + chart
        if params is None:
            r = np.random.default_rng(seed)
            params = {"W1": r.normal(0, np.sqrt(1 / d), (HIDDEN, d)), "b1": np.zeros(HIDDEN),
                      "W2": np.zeros((3, HIDDEN)), "b2": np.zeros(3)}
        self.p = {k: np.asarray(v, float) for k, v in params.items()}
        self.meta = meta or {}
        self.rng = np.random.default_rng(seed + 1)

    @property
    def hidden(self) -> int:
        return len(self.p["b1"]) if "b1" in self.p else 0

    def x(self, raw, ohlc=None) -> np.ndarray:
        v = np.asarray([np.nan if r is None else r for r in raw], float)
        z = np.clip(np.nan_to_num((v - self.mean) / self.std), -5, 5)
        if not self.chart:
            return z
        return np.concatenate([z, chart_features(ohlc) if ohlc is not None else np.zeros(self.chart)])

    def forward(self, x):
        if "W1" not in self.p:                            # agents saved before the network upgrade
            s, h = self.p["W"] @ x[: self.p["W"].shape[1]] + self.p["b"], None
        else:
            h = np.tanh(self.p["W1"] @ x + self.p["b1"])
            s = self.p["W2"] @ h + self.p["b2"]
        s = np.clip(s, -30, 30)
        e = np.exp(s - s.max())
        return e / e.sum(), h

    def probs(self, x) -> np.ndarray:
        return self.forward(x)[0]

    def learn(self, x, a: int, advantage: float, lr: float):
        """REINFORCE: raise the log-probability of the answer in proportion to how many more points it earned."""
        p, h = self.forward(x)
        gs = -p
        gs[a] += 1
        gs *= advantage
        gh = (self.p["W2"].T @ gs) * (1 - h * h)
        self.p["W2"] += lr * np.outer(gs, h)
        self.p["b2"] += lr * gs
        self.p["W1"] += lr * np.outer(gh, x)
        self.p["b1"] += lr * gh

    def probs_batch(self, Xb):
        """Answer probabilities for many questions at once (rows), plus the hidden activations."""
        if "W1" not in self.p:
            S, H = Xb[:, : self.p["W"].shape[1]] @ self.p["W"].T + self.p["b"], None
        else:
            H = np.tanh(Xb @ self.p["W1"].T + self.p["b1"])
            S = H @ self.p["W2"].T + self.p["b2"]
        S = np.clip(S, -30, 30)
        S = S - S.max(1, keepdims=True)
        E = np.exp(S)
        return E / E.sum(1, keepdims=True), H

    def learn_batch(self, Xb, a, advantage, lr: float):
        """REINFORCE for a batch: one matrix step equal to the per-question steps summed."""
        P, H = self.probs_batch(Xb)
        G = -P
        G[np.arange(len(a)), a] += 1
        G *= advantage[:, None]
        GH = (G @ self.p["W2"]) * (1 - H * H)
        self.p["W2"] += lr * G.T @ H
        self.p["b2"] += lr * G.sum(0)
        self.p["W1"] += lr * GH.T @ Xb
        self.p["b1"] += lr * GH.sum(0)

    def grow(self) -> bool:
        """Double the hidden units (keeping everything learned) so there is room for the questions it can't fit."""
        H, d = self.p["W1"].shape
        if H >= MAX_HIDDEN:
            return False
        self.p["W1"] = np.vstack([self.p["W1"], self.rng.normal(0, np.sqrt(1 / d), (H, d))])
        self.p["b1"] = np.concatenate([self.p["b1"], np.zeros(H)])
        self.p["W2"] = np.hstack([self.p["W2"], np.zeros((3, H))])
        return True

    def answer_row(self, row: dict, ohlc=None) -> dict:
        p = self.probs(self.x([row.get(k) for k in self.features], ohlc))
        return {"action": ACTIONS[int(p.argmax())], "probs": {a: round(float(v), 3) for a, v in zip(ACTIONS, p)}}

    def save(self, path: Path = POLICY):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"features": self.features, "mean": self.mean.tolist(), "std": self.std.tolist(),
                                    "chart": self.chart, "params": {k: np.round(v, 6).tolist() for k, v in self.p.items()},
                                    "meta": self.meta}))

    @classmethod
    def load(cls, path: Path = POLICY):
        d = json.loads(path.read_text())
        params = d.get("params") or {"W": d["W"], "b": d["b"]}
        return cls(d["features"], d["mean"], d["std"], params, d.get("meta"), chart=d.get("chart", 0))


def load_policy():
    try:
        return QuizPolicy.load()
    except (OSError, ValueError, KeyError):
        return None


def read_control() -> dict:
    return _load_json(CONTROL, {"speed": 0, "stop": False})


def _save_progress(built, streak, right, asked, done_q, expect, last_right, wrong=None, exam_pick=None, stuck=None):
    extra = {k: v for k, v in (("wrong", wrong), ("exam_pick", exam_pick), ("stuck", stuck)) if v is not None}
    np.savez(PROGRESS, streak=streak, right=right, asked=asked, done=done_q, expect=expect, last_right=last_right,
             built=np.array(built), **extra)


def quiz_inputs(quiz: dict, pol: QuizPolicy) -> np.ndarray:
    """Every question's inputs: its indicator readings plus its chart."""
    Z = np.clip(np.nan_to_num((np.load(QX).astype(float) - pol.mean) / pol.std), -5, 5)
    if not pol.chart:
        return Z
    bars = np.load(QBARS, mmap_mode="r")
    C = np.stack([chart_features(bars[k, :BEFORE]) for k in range(len(Z))])
    return np.hstack([Z, C])


STALL_ROUNDS = 100                # rounds without a newly finished question before it changes tactics
BATCH = 64                        # questions answered per step at full speed (one matrix step, much faster)
MEMORY_EVERY = 10                 # rounds between silent memory checks of finished questions
REFRESH_SHARE = 1.0              # silent refresher: finished questions mixed into each learning step (never asked,
                                  # no points, not shown) so training on new ones doesn't overwrite them
PTS = np.array([[POINTS["right"] if a == b else (POINTS["traded_should_wait"] if b == 2 else
                 POINTS["missed_trade"] if a == 2 else POINTS["wrong_way"]) for b in range(3)] for a in range(3)])
CURRICULUM_SHARE = 0.9            # hard questions join once this share of the easy and medium ones is finished...
CURRICULUM_ROUNDS = 60            # ...or after this many rounds, whichever comes first
STUCK_AFTER = 30                  # rounds since its last right answer before a question counts as stuck


def train(max_rounds: int = 0, lr: float = 0.01, seed: int = 1, resume: bool = False, focus: list[int] | None = None,
          refresh: bool = True):
    """Loops until every question in play is finished or you press Stop (max_rounds > 0 caps it, for tests)."""
    quiz = _load_json(QUIZ, None)
    if not quiz or not QX.exists():
        raise SystemExit("No quiz yet (or it was built by an older version). Build it (Quiz tab -> Build quiz).")
    qs = quiz["questions"]
    ans = np.array([ACTIONS.index(q["answer"]) for q in qs])
    prac = np.array([k for k, q in enumerate(qs) if q["set"] == "practice"])
    exam = np.array([k for k, q in enumerate(qs) if q["set"] == "exam"])
    pol = QuizPolicy(quiz["features"], quiz["norm"]["mean"], quiz["norm"]["std"], seed=seed)
    old = load_policy() if (resume or focus) else None
    if (old is not None and old.meta.get("quiz_built") == quiz["built"] and "W1" in old.p
            and old.p["W1"].shape[1] == len(pol.features) + pol.chart):
        pol.p = old.p
        print(f"continuing with the saved quiz agent ({pol.hidden} units)", flush=True)
    elif resume or focus:
        print("no saved agent that sees the chart for this quiz yet: starting fresh (finished questions stay finished)",
              flush=True)
    print("loading every question's chart as inputs...", flush=True)
    X = quiz_inputs(quiz, pol)
    rng = np.random.default_rng(seed)
    n = len(qs)
    streak, right, asked = np.zeros(n, int), np.zeros(n, int), np.zeros(n, int)
    done_q = np.zeros(n, bool)                           # reached 5 right in a row at least once
    misses = np.zeros(n, int)                            # wrong answers in a row
    expect = np.zeros(n)                                 # points it usually earns on each question
    last_right = np.zeros(n, int)                        # round of its last right answer
    wrong = np.zeros((n, 3), int)                        # which wrong answers it gave (for the weak-spot report)
    exam_pick = np.full(n, -1)                           # its exam answers (-1: not an exam question)
    if (resume or focus) and PROGRESS.exists():
        pr = np.load(PROGRESS)
        if str(pr["built"]) == quiz["built"] and len(pr["streak"]) == n:
            streak, right, asked, done_q, expect = (pr[k].copy() for k in ("streak", "right", "asked", "done", "expect"))
            if "wrong" in pr and pr["wrong"].shape == wrong.shape:
                wrong = pr["wrong"].copy()
    pool = prac
    held_back = prac[:0]                                  # hard questions waiting for the curriculum
    if not focus:
        diff = np.array([q.get("difficulty", "easy") for q in qs])
        hard = prac[(diff[prac] == "hard") & ~done_q[prac]]
        if 0 < len(hard) < len(prac):
            held_back, pool = hard, prac[~np.isin(prac, hard)]
            print(f"curriculum: starting with the {len(pool):,} easy and medium questions; the {len(hard):,} hard ones "
                  f"join once {round(CURRICULUM_SHARE * 100)}% of those are finished (or after {CURRICULUM_ROUNDS} rounds)",
                  flush=True)
    if focus:
        want_ids = {int(v) - 1 for v in focus}
        pool = np.array([i for i in prac if i in want_ids and not done_q[i]], dtype=int)
        if not len(pool):
            raise SystemExit("All of the chosen questions are already finished.")
        print(f"focus: working only on {len(pool)} chosen question(s): "
              + ", ".join(f"Q{i + 1}" for i in pool[:20]) + (" ..." if len(pool) > 20 else ""), flush=True)
    points, n_asked = 0, 0
    per_round, recent = [], deque(maxlen=1000)
    mistake = None
    best_mastered, best_round = int(done_q[pool].sum()), 0
    level = 0
    note = f"easy and medium first; {len(held_back):,} hard questions join later" if len(held_back) else ""
    started, last_write, last_saved = time.time(), 0.0, time.time()
    ctl, ctl_read, due = read_control(), time.time(), time.time()
    prev = load_policy()
    exam_history = (prev.meta.get("exam_history", []) if prev and prev.meta.get("quiz_built") == quiz["built"] else [])
    print(f"quiz: {len(prac):,} practice questions, {len(exam):,} exam questions, {X.shape[1]} inputs each "
          f"(indicators + the chart). Points are the reward: right {POINTS['right']:+d}, wrong way "
          f"{POINTS['wrong_way']:+d}, traded when it should stay out {POINTS['traded_should_wait']:+d}, missed a good "
          f"trade {POINTS['missed_trade']:+d}. It loops until every question is right {MASTERY} times in a row; "
          "finished questions are never asked again (a silent memory check puts back any it forgets).", flush=True)

    def stuck_mask(rnd):
        return ~done_q & (asked > 0) & (rnd - last_right >= STUCK_AFTER)

    def hardest(k=12):
        idx = pool[(asked[pool] > 0) & ~done_q[pool]]
        if not len(idx):
            return []
        worst = idx[np.lexsort((streak[idx], right[idx] / asked[idx]))[:k]]
        return [{"id": int(i) + 1, "setup_name": setup_name(qs[i]["setup"], qs[i].get("trap")), "answer": qs[i]["answer"],
                 "right": int(right[i]), "asked": int(asked[i]), "streak": int(streak[i])} for i in worst]

    def state(rnd, done=False, stopped=False, exam_result=None, reason="", current=None):
        stk = stuck_mask(rnd)
        _write(STATE, {
            "running": not done, "done": done, "stopped": stopped, "reason": reason, "note": note, "round": rnd,
            "asked": n_asked, "points": points, "mastered": int(done_q[prac].sum()), "practice": len(prac),
            "exam_size": len(exam), "mastery": MASTERY, "focus": [int(i) + 1 for i in pool] if focus else None,
            "streaks": "".join("u" if s_ else str(MASTERY if d else min(v, MASTERY))
                               for v, d, s_ in zip(streak[prac], done_q[prac], stk[prac])),
            "current": current, "stuck": int(stk[prac].sum()), "hidden": pol.hidden, "inputs": int(X.shape[1]),
            "recent_pct": round(100 * sum(recent) / len(recent), 1) if recent else None,
            "points_by_round": per_round[-300:], "max_round_points": POINTS["right"] * len(pool),
            "speed": ctl.get("speed", 0), "elapsed": round(time.time() - started),
            "rate": round(n_asked / max(1e-6, time.time() - started)),
            "mistake": mistake, "hardest": hardest(), "exam": exam_result, "exam_history": exam_history[-20:],
            "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")})

    def save_all(meta):
        pol.meta = dict(meta, exam_history=exam_history[-50:])
        pol.save()
        _save_progress(quiz["built"], streak, right, asked, done_q, expect, last_right, wrong, exam_pick,
                       stuck_mask(rnd))

    def report():
        try:                                             # the weak-spot report never gets in the way of training
            from .quiz_report import make_report
            make_report()
        except Exception as e:                           # noqa: BLE001
            print(f"(weak-spot report skipped: {e})", flush=True)

    def memory_check():
        """Silent check of every finished practice question (no learning, no points): any it now gets wrong goes back
        on the board as unfinished. This is how finished questions stay honest without being revisited."""
        fin = prac[done_q[prac]]
        if not len(fin):
            return 0
        best = np.concatenate([pol.probs_batch(X[fin[s:s + 4096]])[0].argmax(1) for s in range(0, len(fin), 4096)])
        lost = fin[best != ans[fin]]
        if len(lost):
            done_q[lost] = False
            streak[lost] = 0
            misses[lost] = 0
            last_right[lost] = rnd
        return len(lost)

    rnd, stopped, reason = 0, False, ""
    last_report = time.time()
    while not max_rounds or rnd < max_rounds:
        rnd += 1
        round_points = 0
        todo = pool[~done_q[pool]]                       # never revisit: only unfinished questions are asked
        fin = prac[done_q[prac]]                         # finished ones, for the silent refresher
        stk = pool[stuck_mask(rnd)[pool]]
        order = rng.permutation(np.concatenate([todo] * (1 + EXTRA) + ([stk] * 6 if level >= 1 else [])))
        s0 = 0
        while s0 < len(order):
            if time.time() - ctl_read > 0.2:
                ctl, ctl_read = read_control(), time.time()
                if ctl.get("stop"):
                    stopped = True
                    break
            speed = float(ctl.get("speed", 0))
            size = BATCH if speed <= 0 else max(1, min(BATCH, int(speed // 20)))
            bi = order[s0:s0 + size]
            s0 += size
            bi = bi[~done_q[bi]]                         # finished earlier in this round: skip
            if len(bi) > 1:
                _, first = np.unique(bi, return_index=True)
                bi = bi[np.sort(first)]
            if not len(bi):
                continue
            Xb = X[bi]
            P, _ = pol.probs_batch(Xb)
            a = np.minimum((rng.random(len(bi))[:, None] > P.cumsum(1)).sum(1), 2)
            explore = rng.random(len(bi)) < np.minimum(EXPLORE_MAX, EXPLORE + 0.01 * misses[bi])  # stuck: try more
            a[explore] = rng.integers(3, size=int(explore.sum()))
            pts = PTS[a, ans[bi]]
            boost = np.where((level >= 1) & (rnd - last_right[bi] >= STUCK_AFTER), 3.0, 1.0)
            adv = (pts - expect[bi]) / 10.0 * boost      # the reward: more points than usual -> more of that
            if refresh and len(fin):                     # silent refresher: keep finished answers from being overwritten
                r = fin[rng.integers(len(fin), size=max(1, int(len(bi) * REFRESH_SHARE)))]
                pol.learn_batch(np.vstack([Xb, X[r]]), np.concatenate([a, ans[r]]),
                                np.concatenate([adv, np.full(len(r), 1.0)]), lr)
            else:
                pol.learn_batch(Xb, a, adv, lr)
            expect[bi] += 0.3 * (pts - expect[bi])
            points += int(pts.sum())
            round_points += int(pts.sum())
            n_asked += len(bi)
            asked[bi] += 1
            ok = a == ans[bi]
            recent.extend(ok.tolist())
            misses[bi] = np.where(ok, 0, misses[bi] + 1)
            streak[bi] = np.where(ok, streak[bi] + 1, 0)
            right[bi] += ok
            last_right[bi[ok]] = rnd
            # finished = right 5 times in a row AND its best answer is right (not 5 lucky guesses)
            done_q[bi[ok & (streak[bi] >= MASTERY) & (P.argmax(1) == ans[bi])]] = True
            if (~ok).any():
                wrong[bi[~ok], a[~ok]] += 1
                j = int(np.flatnonzero(~ok)[-1])
                mistake = {"id": int(bi[j]) + 1, "action": ACTIONS[a[j]], "points": int(pts[j]),
                           "verdict": points_for(ACTIONS[a[j]], qs[bi[j]]["answer"])[1],
                           "probs": {k: round(float(v), 3) for k, v in zip(ACTIONS, P[j])}, "at": n_asked}
            now = time.time()
            if now - last_write > 0.25:
                if now - last_saved > 20:                # keep progress if the app is closed mid-quiz
                    save_all({"quiz_built": quiz["built"], "partial": True})
                    last_saved = now
                    if now - last_report > 300:          # refresh the weak-spot report every 5 minutes
                        report()
                        last_report = time.time()
                if mistake and "bars" not in mistake:
                    mistake.update(question_view(mistake["id"], quiz))
                live = bi[~done_q[bi]]                   # the question it is on right now (baby blue on the board)
                state(rnd, current=int(live[-1]) + 1 if len(live) else None)
                last_write = now
            if speed > 0:
                due = max(due, now - 0.5) + len(bi) / speed
                if due - now > 0.003:
                    time.sleep(due - now)
        if stopped:
            reason = "stopped from the app"
            break
        per_round.append(round_points)
        if rnd % MEMORY_EVERY == 0:
            lost = memory_check()
            if lost:
                note = f"memory check: {lost:,} finished question(s) forgotten, back on the board"
                print(note, flush=True)
        mastered = int(done_q[pool].sum())
        if mastered > best_mastered:
            best_mastered, best_round = mastered, rnd
        if rnd % 10 == 0 or mastered == len(pool):
            print(f"round {rnd}: {int(done_q[prac].sum()):,}/{len(prac):,} finished ({MASTERY} right in a row), "
                  f"{round_points:+,d} points this round, {points:+,d} total" + (f" | {note}" if note else ""), flush=True)
        if len(held_back) and (done_q[pool].mean() >= CURRICULUM_SHARE or rnd >= CURRICULUM_ROUNDS):
            pool = np.concatenate([pool, held_back])       # curriculum: now the hard ones
            note = f"added the {len(held_back):,} hard questions"
            held_back = held_back[:0]
            best_mastered, best_round = int(done_q[pool].sum()), rnd
            print(note, flush=True)
        if done_q[pool].all():
            lost = memory_check()                        # before calling it done, make sure nothing was forgotten
            if not lost:
                reason = "every chosen question finished" if focus else "every practice question finished"
                break
            note = f"memory check: {lost:,} finished question(s) forgotten, back on the board"
            print(note, flush=True)
            best_mastered = int(done_q[pool].sum())
        # stuck? change tactics and keep looping (it never gives up on its own)
        stall = rnd - best_round
        if stall >= STALL_ROUNDS and level == 0:
            level, best_round = 1, rnd
            note = (f"stuck on {len(pool[~done_q[pool]])}: asking them 7 extra times a round with 3x bigger learning steps")
            print(note, flush=True)
        elif stall >= STALL_ROUNDS:
            best_round = rnd
            if pol.grow():
                note = f"still stuck: grew its brain to {pol.hidden} units (everything learned is kept)"
            else:
                left = pool[~done_q[pool]]
                expect[left] = POINTS["wrong_way"]          # a right answer there now counts as a big surprise
                note = (f"at full size ({pol.hidden} units): {len(left)} questions keep conflicting with others; "
                        "looping on them with a fresh look")
            print(note, flush=True)
    else:
        reason = f"reached {max_rounds} rounds"

    lost = memory_check()                                # the board shows what it really still knows
    if lost:
        print(f"memory check: {lost:,} finished question(s) forgotten; Continue will retrain them", flush=True)
    exam_result = None
    if len(exam):
        pe = np.concatenate([pol.probs_batch(X[exam[s:s + 4096]])[0].argmax(1) for s in range(0, len(exam), 4096)])
        exam_pick[exam] = pe
        ok = pe == ans[exam]
        pts = int(PTS[pe, ans[exam]].sum())
        by = {}
        for i, good in zip(exam, ok):
            r_, t_ = by.get(group_name(qs[i]), (0, 0))
            by[group_name(qs[i])] = (r_ + int(good), t_ + 1)
        exam_result = {"right": int(ok.sum()), "total": int(len(exam)), "pct": round(100 * ok.mean(), 1), "points": pts,
                       "by_setup": {k: list(v) for k, v in sorted(by.items())}}
        exam_history.append({"pct": exam_result["pct"], "time": datetime.now(timezone.utc).isoformat(timespec="minutes"),
                             "focus": bool(focus), "rounds": rnd})
    mastered = int(done_q[prac].sum())
    save_all({"trained": datetime.now(timezone.utc).isoformat(timespec="seconds"), "rounds": rnd, "asked": n_asked,
              "points": points, "mastered": mastered, "practice": len(prac), "exam": exam_result,
              "quiz_built": quiz["built"], "reason": reason, "hidden": pol.hidden, "inputs": int(X.shape[1]),
              "forgotten_at_end": int(lost)})
    state(rnd, done=True, stopped=stopped, exam_result=exam_result, reason=reason)
    report()
    try:
        write_lessons(quiz, prac, done_q, right, asked, stuck_mask(rnd), exam_result, pol, rnd, points)
    except OSError:
        pass
    print(f"\nfinished after {rnd} rounds ({reason}), {n_asked:,} answers, {points:+,d} points. "
          f"Finished {mastered:,}/{len(prac):,}.", flush=True)
    if exam_result:
        print(f"exam (never-seen questions): {exam_result['right']:,}/{exam_result['total']:,} right "
              f"({exam_result['pct']}%, guessing would be ~33%), {exam_result['points']:+,d} points", flush=True)
        if len(exam_history) > 1 and exam_result["pct"] < exam_history[-2]["pct"] - 5:
            print(f"warning: the exam fell from {exam_history[-2]['pct']}% to {exam_result['pct']}%: likely forgetting "
                  "after narrow training (Work on these / picked). Continue lets the memory check repair it.", flush=True)
    print("saved the quiz agent to models/quiz_policy.json, its lessons to .claude/skills/quiz-lessons/ and the "
          "weak-spot report to data/quiz_report.md (+ .claude/skills/quiz-weak-spots/)", flush=True)


LESSONS = ROOT / ".claude" / "skills" / "quiz-lessons"


def write_lessons(quiz, prac, done_q, right, asked, stuck, exam_result, pol, rnd, points):
    """The quiz writes what it has learned into a skill, so Claude and Hermes can read it later."""
    qs = quiz["questions"]
    rows = {}
    for i in prac:
        name = group_name(qs[i])
        r = rows.setdefault(name, [0, 0, 0, 0, 0])      # questions, finished, right, asked, stuck
        r[0] += 1
        r[1] += int(done_q[i])
        r[2] += int(right[i])
        r[3] += int(asked[i])
        r[4] += int(stuck[i])
    ex = (exam_result or {}).get("by_setup", {})
    lines = ["| Setup | Practice | Finished | Right answers | Stuck | Exam (unseen) |", "|---|---|---|---|---|---|"]
    weak, strong = [], []
    for name, (q, f, r, a, s_) in sorted(rows.items(), key=lambda kv: -kv[1][0]):
        e = ex.get(name)
        epct = round(100 * e[0] / e[1]) if e and e[1] else None
        lines.append(f"| {name} | {q} | {f} ({round(100 * f / q)}%) | {round(100 * r / max(1, a))}% | {s_} | "
                     + (f"{e[0]}/{e[1]} ({epct}%)" if e else "–") + " |")
        if epct is not None and e[1] >= 10:
            (weak if epct < 55 else strong if epct >= 75 else []).append((name, epct))
    stuck_ids = [int(i) + 1 for i in prac if stuck[i]][:30]
    when = datetime.now(timezone.utc).isoformat(timespec="minutes")
    exam_line = (f"{exam_result['right']:,}/{exam_result['total']:,} ({exam_result['pct']}%) on questions it never "
                 "trained on; guessing gets about 33%." if exam_result else "No exam yet.")
    body = f"""---
name: quiz-lessons
description: What the Trading Bot's quiz agent has learned in Quiz school - which professional gold setups it has mastered, which it still gets wrong, its exam score on unseen charts, and the questions it is stuck on. Written by the quiz itself after every run. Use this whenever the user asks how the quiz/reinforcement-learning agent is doing, whether to trust its second opinion or "what would you do now" answer, or which setups it struggles with.
---

# Quiz lessons (written by the quiz agent)

Last updated {when} UTC after {rnd:,} rounds. Quiz built {quiz['built']} with {len(qs):,} questions.
Agent: {pol.hidden} units, {len(pol.features) + pol.chart} inputs (indicators + the chart). Points earned: {points:+,d}.

- Practice finished (right 5 times in a row): {int(done_q[prac].sum()):,} of {len(prac):,}
- Exam: {exam_line}
- Question mix: {len({q['setup'] for q in qs if q['setup'] != 'wait'})} pro setup types, {sum(bool(q.get('trap')) for q in qs):,} traps (setups that failed: stay out), {sum(q['setup'] == 'wait' for q in qs):,} stay-out spots; difficulty {', '.join(f"{lvl} {sum(q.get('difficulty') == lvl for q in qs):,}" for lvl in ('easy', 'medium', 'hard'))}
- Stuck right now: {int(stuck[prac].sum()):,}{(' (for example Q' + ', Q'.join(map(str, stuck_ids)) + ')') if stuck_ids else ''}

## By setup
{chr(10).join(lines)}

## How to use this
- Trust its answers most on: {', '.join(f'{n} ({p}%)' for n, p in strong) or 'nothing yet (no setup reaches 75% on the exam)'}.
- Treat these as coin flips for now: {', '.join(f'{n} ({p}%)' for n, p in weak) or 'none'}.
- Practice finished is memory; the exam is skill. If practice is near 100% but the exam is low, it memorised the
  answers: build a bigger quiz (more history) rather than training longer.
- Stuck questions: Quiz tab -> pick them on the board -> Work on picked. It loops until they are finished.
"""
    LESSONS.mkdir(parents=True, exist_ok=True)
    (LESSONS / "SKILL.md").write_text(body, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--symbol", default="XAUUSD")
    b.add_argument("--questions", type=int, default=40)
    b.add_argument("--point", type=float, default=0.01)
    b.add_argument("--seed", type=int, default=7)
    t = sub.add_parser("train")
    t.add_argument("--max-rounds", type=int, default=0, help="0 = loop until everything is finished or Stop")
    t.add_argument("--lr", type=float, default=0.01)
    t.add_argument("--resume", action="store_true", help="continue with the saved agent and progress")
    t.add_argument("--no-refresh", action="store_true", help="don't silently refresh finished questions")
    t.add_argument("--focus", default="", help="comma-separated question numbers to work on (finished ones are skipped)")
    a = ap.parse_args()
    if a.cmd == "build":
        build(a.symbol, a.questions, point=a.point, seed=a.seed)
    else:
        focus = [int(v) for v in a.focus.replace(" ", "").split(",") if v] or None
        train(a.max_rounds, a.lr, resume=a.resume, focus=focus, refresh=not a.no_refresh)


if __name__ == "__main__":
    main()
