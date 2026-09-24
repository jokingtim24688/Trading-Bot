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
SPACING = 60                      # candles between questions (1 hour)
BEFORE, AFTER = 90, 60            # chart candles before the question and revealed after it
EXPLORE = 0.05                    # share of answers picked at random...
EXPLORE_MAX = 0.5                 # ...rising to half the time on a question it keeps missing
EXTRA = 2                         # unfinished questions are asked this many extra times per round (7 more once stuck)
HIDDEN = 64
MAX_QUESTIONS = 10_000
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
}
WAIT_NAME = "No setup (stay out)"
WAIT_TEXT = ("Price is in the middle of the day's range with no key level, sweep or breakout nearby. Pros stay out here: "
             "neither a buy nor a sell with the same stop would have been a clean trade.")


def setup_name(key: str) -> str:
    return WAIT_NAME if key == "wait" else SETUP_NAMES.get(key, key)


def explain(q: dict) -> str:
    text = WAIT_TEXT if q["setup"] == "wait" else PRO_SETUPS[q["setup"]][1]
    t = q.get("trade")
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
    """Candle positions where each pro setup first appears (in session hours)."""
    h1 = f["h1_structure"]
    sweep_lo_now = f["sweep_long"].eq(1) & f["sweep_long"].shift(1).eq(0)
    sweep_hi_now = f["sweep_short"].eq(1) & f["sweep_short"].shift(1).eq(0)
    orb_up = _first((f["lon_or_pos"] > 0.2) | (f["ny_or_pos"] > 0.2))
    orb_dn = _first((f["lon_or_pos"] < -0.2) | (f["ny_or_pos"] < -0.2))
    sa = f["sess_avg_dist"]
    reclaim_up = (sa > 0) & (sa.shift(1) < 0) & (h1 >= 1)
    reclaim_dn = (sa < 0) & (sa.shift(1) > 0) & (h1 <= -1)
    gap = f["fvg_net10"].diff()
    fvg_up = (gap >= 1) & (h1 >= 1)
    fvg_dn = (gap <= -1) & (h1 <= -1)
    pdl, pdh = f["pdl_dist"], f["pdh_dist"]
    pdl_hold = (pdl.between(0, 0.4)) & (f["body"] > 0.2) & (pdl.shift(3) > 0.8)
    pdh_hold = (pdh.between(-0.4, 0)) & (f["body"] < -0.2) & (pdh.shift(3) < -0.8)
    hours = f.index.hour
    ok = ((hours >= SESSION[0]) & (hours < SESSION[1])) & f.notna().all(axis=1).to_numpy()
    conds = {"sweep_long": sweep_lo_now, "sweep_short": sweep_hi_now, "orb_long": orb_up, "orb_short": orb_dn,
             "avg_reclaim_long": reclaim_up, "avg_reclaim_short": reclaim_dn, "fvg_bull": fvg_up, "fvg_bear": fvg_dn,
             "pdl_test": pdl_hold, "pdh_test": pdh_hold}
    out = {k: np.flatnonzero(v.fillna(False).to_numpy() & ok) for k, v in conds.items()}
    quiet = ((f["day_range_pos"].between(0.35, 0.65)) & (f["sweep_long"] == 0) & (f["sweep_short"] == 0)
             & (f["lon_or_pos"] == 0) & (f["ny_or_pos"] == 0) & (f["sess_avg_dist"].abs().between(0.5, 2.5))
             & (f["round_big_dist"].abs() > 1) & (f["pdh_dist"].abs() > 2) & (f["pdl_dist"].abs() > 2))
    out["wait"] = np.flatnonzero(quiet.fillna(False).to_numpy() & ok)
    return out


def _trade(df_np, i: int, side: str, stop_dist: float, spread: float):
    """Walk forward a pro-style trade (target 2R). Returns (won, minutes, stop, target, worst move against it in R)."""
    o, h, l, c = df_np
    entry = c[i] + spread if side == "buy" else c[i]
    stop = entry - stop_dist if side == "buy" else entry + stop_dist
    target = entry + 2 * stop_dist if side == "buy" else entry - 2 * stop_dist
    mae = 0.0
    for k in range(i + 1, min(len(c), i + 1 + HORIZON)):
        if side == "buy":
            mae = max(mae, (entry - l[k]) / stop_dist)
            if l[k] <= stop:
                return False, k - i, stop, target, mae
            if h[k] >= target:
                return True, k - i, stop, target, mae
        else:
            mae = max(mae, (h[k] + spread - entry) / stop_dist)
            if h[k] + spread >= stop:
                return False, k - i, stop, target, mae
            if l[k] + spread <= target:
                return True, k - i, stop, target, mae
    return False, HORIZON, stop, target, mae


def _conflicts(Xz: np.ndarray, answers: np.ndarray, thr: float = 3.0, k: int = 5) -> set:
    """Questions no one could answer from the chart: a near-twin has the other answer, or most of its closest
    look-alikes (4 of 5) do. Those are coin flips, not lessons."""
    bad = set()
    sq = (Xz ** 2).sum(1)
    for s in range(0, len(Xz), 1000):
        blk = Xz[s:s + 1000]
        d2 = sq[s:s + 1000, None] + sq[None, :] - 2 * blk @ Xz.T
        rows = np.arange(len(blk))
        d2[rows, rows + s] = np.inf                      # not its own neighbour
        diff = answers[s:s + 1000, None] != answers[None, :]
        ii, jj = np.nonzero((d2 < thr * thr) & diff)
        for a, b in zip(ii + s, jj):
            bad.add(int(max(a, b)))
        if len(Xz) > k:
            nn = np.argpartition(d2, k, axis=1)[:, :k]
            opposite = (answers[nn] != answers[s:s + 1000, None]).sum(1)
            bad.update(int(v) for v in np.flatnonzero(opposite >= k - 1) + s)
    return bad


def build(symbol: str = "XAUUSD", n_questions: int = 40, exam_share: float = 0.25, point: float = 0.01, seed: int = 7):
    from .history import load_bars
    n_questions = int(min(MAX_QUESTIONS, max(34, n_questions)))
    df = load_bars(symbol)
    print(f"looking for pro setups in {len(df):,} candles ({df.index[0]:%Y-%m-%d} -> {df.index[-1]:%Y-%m-%d})...", flush=True)
    f = build_features(df, point)
    a = atr(df, 14).to_numpy()
    df_np = tuple(df[k].to_numpy() for k in ("open", "high", "low", "close"))
    spread = df["spread"].to_numpy(dtype=float) * point
    cands = _candidates(f)
    for k, v in cands.items():
        print(f"  {setup_name(k)}: {len(v):,} candidates", flush=True)

    rng = np.random.default_rng(seed)
    want = int(n_questions * 1.3) + 10                   # extra, some get dropped as contradictions
    n_wait = max(4, round(want * 0.2))
    kinds = [k for k in PRO_SETUPS if len(cands[k])]
    if not kinds:
        raise SystemExit("No pro setups found. Download more history (Train tab) and try again.")
    orders = {k: rng.permutation(cands[k]) for k in kinds + ["wait"]}
    pos = {k: 0 for k in orders}
    taken = set()                                        # 1-hour buckets already used

    def free(i):
        b = i // SPACING
        return not ({b - 1, b, b + 1} & taken)

    def take(kind):
        arr = orders[kind]
        while pos[kind] < len(arr):
            i = int(arr[pos[kind]])
            pos[kind] += 1
            if i < 3000 or i + HORIZON >= len(df) or not free(i) or not a[i] > 0:
                continue
            if kind == "wait":                           # neither a buy nor a sell would have been a clean pro trade
                sd = 1.5 * a[i]
                if any(w and m <= CLEAN_MINUTES and e <= CLEAN_MAE
                       for w, m, _, _, e in (_trade(df_np, i, s_, sd, spread[i]) for s_ in ("buy", "sell"))):
                    continue
                return i, "wait", None
            side = PRO_SETUPS[kind][0]
            if kind.startswith("sweep"):                 # stop just beyond the sweep's wick
                if side == "buy":
                    sd = df_np[3][i] + spread[i] - df_np[2][i - 4:i + 1].min() + 0.2 * a[i]
                else:
                    sd = df_np[1][i - 4:i + 1].max() - df_np[3][i] + 0.2 * a[i]
                sd = float(np.clip(sd, 0.8 * a[i], 3 * a[i]))
            else:
                sd = 1.5 * a[i]
            won, mins, stop, target, mae = _trade(df_np, i, side, sd, spread[i])
            if won and mins <= CLEAN_MINUTES and mae <= CLEAN_MAE:
                return i, side, {"minutes": int(mins), "stop": round(float(stop), 2), "target": round(float(target), 2),
                                 "entry": round(float(df_np[3][i] + (spread[i] if side == "buy" else 0)), 2)}
        return None

    picks = []
    plan = [kinds[j % len(kinds)] for j in range(want - n_wait)] + ["wait"] * n_wait
    plan = [plan[k] for k in rng.permutation(len(plan))]  # stay-out spots mixed in, not left for last
    last_print = time.time()
    for kind in plan:
        got = take(kind)
        if got is None and kind != "wait":
            for other in kinds:
                got = take(other)
                if got:
                    kind = other
                    break
        if got is None:
            continue
        i, answer, trade = got
        taken.add(i // SPACING)
        picks.append((i, kind, answer, trade))
        if time.time() - last_print > 2:
            print(f"  found {len(picks):,} of {want:,}...", flush=True)
            last_print = time.time()
    if len(picks) < 10:
        raise SystemExit(f"Only found {len(picks)} usable questions. Download more history and try again.")

    sample = f.dropna().sample(min(50_000, len(f.dropna())), random_state=seed)
    mean, std = sample.mean().to_numpy(), sample.std().replace(0, 1).to_numpy()
    X = f.iloc[[p[0] for p in picks]].to_numpy(dtype=np.float32)
    Xz = np.clip(np.nan_to_num((X - mean) / std), -5, 5)
    bad = _conflicts(Xz, np.array([p[2] for p in picks]))
    keep = [k for k in rng.permutation(len(picks)) if k not in bad][:n_questions]     # shuffled, so every kind survives
    print(f"  dropped {len(bad):,} questions whose look-alikes have the opposite answer (no one could tell them apart)",
          flush=True)

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
        i, kind, answer, trade = picks[k]
        lo, hi = i - BEFORE + 1, min(len(df), i + AFTER + 1)
        bars[qid, : hi - lo] = ohlc[lo:hi]
        times[qid, : hi - lo] = epoch[lo:hi]
        questions.append({"id": qid + 1, "time": str(df.index[i])[:16], "setup": kind, "answer": answer, "trade": trade,
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
    if n < n_questions:
        print(f"  your history only had room for {n:,} clean questions; download more years (Train tab) for more", flush=True)
    print(f"saved {n:,} questions ({n - n_exam:,} practice, {n_exam:,} exam; answers {by})", flush=True)
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
    q.update(setup_name=setup_name(q["setup"]), explanation=explain(q), bars=rows[:BEFORE], after=rows[BEFORE:])
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


def _save_progress(built, streak, right, asked, done_q, expect, last_right):
    np.savez(PROGRESS, streak=streak, right=right, asked=asked, done=done_q, expect=expect, last_right=last_right,
             built=np.array(built))


def quiz_inputs(quiz: dict, pol: QuizPolicy) -> np.ndarray:
    """Every question's inputs: its indicator readings plus its chart."""
    Z = np.clip(np.nan_to_num((np.load(QX).astype(float) - pol.mean) / pol.std), -5, 5)
    if not pol.chart:
        return Z
    bars = np.load(QBARS, mmap_mode="r")
    C = np.stack([chart_features(bars[k, :BEFORE]) for k in range(len(Z))])
    return np.hstack([Z, C])


STALL_ROUNDS = 100                # rounds without a newly finished question before it changes tactics
STUCK_AFTER = 30                  # rounds since its last right answer before a question counts as stuck


def train(max_rounds: int = 0, lr: float = 0.01, seed: int = 1, resume: bool = False, focus: list[int] | None = None):
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
    if (resume or focus) and PROGRESS.exists():
        pr = np.load(PROGRESS)
        if str(pr["built"]) == quiz["built"] and len(pr["streak"]) == n:
            streak, right, asked, done_q, expect = (pr[k].copy() for k in ("streak", "right", "asked", "done", "expect"))
    pool = prac
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
    level, note = 0, ""
    started, last_write, last_saved = time.time(), 0.0, time.time()
    ctl, ctl_read, due = read_control(), time.time(), time.time()
    print(f"quiz: {len(prac):,} practice questions, {len(exam):,} exam questions, {X.shape[1]} inputs each "
          f"(indicators + the chart). Points are the reward: right {POINTS['right']:+d}, wrong way "
          f"{POINTS['wrong_way']:+d}, traded when it should stay out {POINTS['traded_should_wait']:+d}, missed a good "
          f"trade {POINTS['missed_trade']:+d}. It loops until every question is right {MASTERY} times in a row.",
          flush=True)

    def stuck_mask(rnd):
        return ~done_q & (asked > 0) & (rnd - last_right >= STUCK_AFTER)

    def hardest(k=12):
        idx = pool[(asked[pool] > 0) & ~done_q[pool]]
        if not len(idx):
            return []
        worst = idx[np.lexsort((streak[idx], right[idx] / asked[idx]))[:k]]
        return [{"id": int(i) + 1, "setup_name": setup_name(qs[i]["setup"]), "answer": qs[i]["answer"],
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
            "mistake": mistake, "hardest": hardest(), "exam": exam_result,
            "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")})

    def save_all(meta):
        pol.meta = meta
        pol.save()
        _save_progress(quiz["built"], streak, right, asked, done_q, expect, last_right)

    rnd, stopped, reason = 0, False, ""
    while not max_rounds or rnd < max_rounds:
        rnd += 1
        round_points = 0
        todo = pool[~done_q[pool]]
        stk = pool[stuck_mask(rnd)[pool]]
        reps = [pool] + [todo] * EXTRA + ([stk] * 6 if level >= 1 else [])
        for i in rng.permutation(np.concatenate(reps)):
            if time.time() - ctl_read > 0.2:
                ctl, ctl_read = read_control(), time.time()
                if ctl.get("stop"):
                    stopped = True
                    break
            x = X[i]
            p = pol.probs(x)
            explore = min(EXPLORE_MAX, EXPLORE + 0.01 * misses[i])   # stuck here -> try other answers more
            a = int(rng.integers(3)) if rng.random() < explore else int(rng.choice(3, p=p))
            act = ACTIONS[a]
            pts, verdict = points_for(act, qs[i]["answer"])
            boost = 3.0 if level >= 1 and not done_q[i] and rnd - last_right[i] >= STUCK_AFTER else 1.0
            pol.learn(x, a, (pts - expect[i]) / 10.0, lr * boost)   # the reward: more points than usual here -> more of that
            expect[i] += 0.3 * (pts - expect[i])
            points += pts
            round_points += pts
            n_asked += 1
            asked[i] += 1
            recent.append(a == ans[i])
            misses[i] = 0 if a == ans[i] else misses[i] + 1
            if a == ans[i]:
                streak[i] += 1
                right[i] += 1
                last_right[i] = rnd
                if streak[i] >= MASTERY:
                    done_q[i] = True
            else:
                streak[i] = 0
                mistake = {"id": int(i) + 1, "action": act, "points": pts, "verdict": verdict,
                           "probs": {k: round(float(v), 3) for k, v in zip(ACTIONS, p)}, "at": n_asked}
            now = time.time()
            if now - last_write > 0.25:
                if now - last_saved > 20:                # keep progress if the app is closed mid-quiz
                    save_all({"quiz_built": quiz["built"], "partial": True})
                    last_saved = now
                if mistake and "bars" not in mistake:
                    mistake.update(question_view(mistake["id"], quiz))
                state(rnd, current=int(i) + 1)          # the question it is on right now (baby blue on the board)
                last_write = now
            speed = float(ctl.get("speed", 0))
            if speed > 0:
                due = max(due, now - 0.5) + 1.0 / speed
                if due - now > 0.003:
                    time.sleep(due - now)
        if stopped:
            reason = "stopped from the app"
            break
        per_round.append(round_points)
        mastered = int(done_q[pool].sum())
        if mastered > best_mastered:
            best_mastered, best_round = mastered, rnd
        if rnd % 10 == 0 or mastered == len(pool):
            print(f"round {rnd}: {int(done_q[prac].sum()):,}/{len(prac):,} finished ({MASTERY} right in a row), "
                  f"{round_points:+,d} points this round, {points:+,d} total" + (f" | {note}" if note else ""), flush=True)
        if done_q[pool].all():
            reason = "every chosen question finished" if focus else "every practice question finished"
            break
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
                expect[left] = POINTS["wrong_way"]          # a right answer there now counts as a huge surprise
                misses[left] = 50                           # and it tries other answers half the time
                note = f"still stuck at {pol.hidden} units: shaking up the {len(left)} stuck questions and looping again"
            print(note, flush=True)
    else:
        reason = f"reached {max_rounds} rounds"

    exam_result = None
    if len(exam):
        pe = np.array([pol.probs(X[i]) for i in exam]).argmax(1)
        ok = pe == ans[exam]
        pts = sum(points_for(ACTIONS[a], qs[i]["answer"])[0] for a, i in zip(pe, exam))
        by = {}
        for i, good in zip(exam, ok):
            r_, t_ = by.get(setup_name(qs[i]["setup"]), (0, 0))
            by[setup_name(qs[i]["setup"])] = (r_ + int(good), t_ + 1)
        exam_result = {"right": int(ok.sum()), "total": int(len(exam)), "pct": round(100 * ok.mean(), 1), "points": int(pts),
                       "by_setup": {k: list(v) for k, v in sorted(by.items())}}
    mastered = int(done_q[prac].sum())
    save_all({"trained": datetime.now(timezone.utc).isoformat(timespec="seconds"), "rounds": rnd, "asked": n_asked,
              "points": points, "mastered": mastered, "practice": len(prac), "exam": exam_result,
              "quiz_built": quiz["built"], "reason": reason, "hidden": pol.hidden, "inputs": int(X.shape[1])})
    state(rnd, done=True, stopped=stopped, exam_result=exam_result, reason=reason)
    try:
        write_lessons(quiz, prac, done_q, right, asked, stuck_mask(rnd), exam_result, pol, rnd, points)
    except OSError:
        pass
    print(f"\nfinished after {rnd} rounds ({reason}), {n_asked:,} answers, {points:+,d} points. "
          f"Finished {mastered:,}/{len(prac):,}.", flush=True)
    if exam_result:
        print(f"exam (never-seen questions): {exam_result['right']:,}/{exam_result['total']:,} right "
              f"({exam_result['pct']}%, guessing would be ~33%), {exam_result['points']:+,d} points", flush=True)
    print("saved the quiz agent to models/quiz_policy.json and its lessons to .claude/skills/quiz-lessons/", flush=True)


LESSONS = ROOT / ".claude" / "skills" / "quiz-lessons"


def write_lessons(quiz, prac, done_q, right, asked, stuck, exam_result, pol, rnd, points):
    """The quiz writes what it has learned into a skill, so Claude and Hermes can read it later."""
    qs = quiz["questions"]
    rows = {}
    for i in prac:
        name = setup_name(qs[i]["setup"])
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
    t.add_argument("--focus", default="", help="comma-separated question numbers to work on (finished ones are skipped)")
    a = ap.parse_args()
    if a.cmd == "build":
        build(a.symbol, a.questions, point=a.point, seed=a.seed)
    else:
        focus = [int(v) for v in a.focus.replace(" ", "").split(",") if v] or None
        train(a.max_rounds, a.lr, resume=a.resume, focus=focus)


if __name__ == "__main__":
    main()
