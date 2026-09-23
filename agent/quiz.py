"""Quiz school: the bot answers "what do you do here?" on real gold situations and learns from points (reinforcement learning).

    python -m agent.quiz build --questions 40     # find the questions in your downloaded M1 history
    python -m agent.quiz train                    # quiz the agent until it gets every question right 5 times in a row

Where the questions come from
    There is no public record of individual professional gold trades, so the quiz is built from real XAUUSD candles:
    moments where a textbook professional setup appeared (agent/pro.py: liquidity sweep, opening-range breakout,
    session-average reclaim, fair value gap, prior-day level test) AND a trade taken the way a pro would take it
    (stop beyond the sweep wick or 1.5 ATR, target 2R) actually reached its target. Those have the answer buy/sell.
    Clean no-trade situations are mixed in (middle of the day's range, no level, no setup, and both a buy and a sell
    would have failed): the answer there is "wait". Questions come from different days and are split into a practice
    set (at least 30) and an exam set the agent never trains on.

How it learns (reinforcement learning)
    The agent sees what a trader would see at that candle (the model's 49 inputs, including the pro levels) and picks
    buy, sell or wait from its policy: softmax(W x + b). Points are its reward and its only goal:
        right answer  +10 points
        wrong way     -10 points   (bought a sell, or sold a buy)
        traded when it should have waited   -5 points
        waited when there was a good trade  -3 points
    After each answer the policy is nudged toward actions that earned more points than it usually earns (REINFORCE
    with a baseline), so over time it prefers whatever gets it points. It answers by sampling from its policy, so
    "right 5 times in a row" means it has become confident, not lucky. Training stops when every practice question has a
    streak of 5, then it sits the exam (questions it never saw) - the honest measure of whether it learned the pattern
    or just memorised the answers.

The trained policy is saved to models/quiz_policy.json. The app can ask it about the live market, and (Settings) use it
as a second opinion before the bot enters.
"""
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .features import atr, build_features
from .pro import SETUP_NAMES

ROOT = Path(__file__).resolve().parent.parent
QUIZ = ROOT / "data" / "quiz.json"
STATE = ROOT / "data" / "quiz_state.json"
CONTROL = ROOT / "data" / "quiz_control.json"
POLICY = ROOT / "models" / "quiz_policy.json"

ACTIONS = ("buy", "sell", "wait")
POINTS = {"right": 10, "wrong_way": -10, "traded_should_wait": -5, "missed_trade": -3}
MASTERY = 5                       # correct answers in a row per question
HORIZON = 240                     # candles a quiz trade has to reach its target (4 hours)
SESSION = (10, 20)                # server hours pros are active in (London open to late New York)

# the pro setups used for questions, the direction a pro takes, and how they'd put it
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
WAIT_TEXT = ("Price is in the middle of the day's range with no key level, sweep or breakout nearby. Pros stay out here: "
             "a buy and a sell with the same stop both failed.")


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
    pdl = f["pdl_dist"]
    pdh = f["pdh_dist"]
    pdl_hold = (pdl.between(0, 0.4)) & (f["body"] > 0.2) & (pdl.shift(3) > 0.8)
    pdh_hold = (pdh.between(-0.4, 0)) & (f["body"] < -0.2) & (pdh.shift(3) < -0.8)
    hours = f.index.hour
    in_session = (hours >= SESSION[0]) & (hours < SESSION[1])
    conds = {"sweep_long": sweep_lo_now, "sweep_short": sweep_hi_now, "orb_long": orb_up, "orb_short": orb_dn,
             "avg_reclaim_long": reclaim_up, "avg_reclaim_short": reclaim_dn, "fvg_bull": fvg_up, "fvg_bear": fvg_dn,
             "pdl_test": pdl_hold, "pdh_test": pdh_hold}
    out = {k: np.flatnonzero((v.fillna(False).to_numpy()) & in_session & f.notna().all(axis=1).to_numpy())
           for k, v in conds.items()}
    quiet = ((f["day_range_pos"].between(0.35, 0.65)) & (f["sweep_long"] == 0) & (f["sweep_short"] == 0)
             & (f["lon_or_pos"] == 0) & (f["ny_or_pos"] == 0) & (f["sess_avg_dist"].abs().between(0.5, 2.5))
             & (f["round_big_dist"].abs() > 1) & (f["pdh_dist"].abs() > 2) & (f["pdl_dist"].abs() > 2))
    out["wait"] = np.flatnonzero(quiet.fillna(False).to_numpy() & in_session & f.notna().all(axis=1).to_numpy())
    return out


def _trade(df_np, i: int, side: str, stop_dist: float, spread: float):
    """Walk forward: did a pro-style trade (target 2R) hit its target before its stop? Returns (won, minutes, stop, target)."""
    o, h, l, c = df_np
    entry = c[i] + spread if side == "buy" else c[i]
    stop = entry - stop_dist if side == "buy" else entry + stop_dist
    target = entry + 2 * stop_dist if side == "buy" else entry - 2 * stop_dist
    end = min(len(c), i + 1 + HORIZON)
    for k in range(i + 1, end):
        if side == "buy":
            if l[k] <= stop:
                return False, k - i, stop, target
            if h[k] >= target:
                return True, k - i, stop, target
        else:
            if h[k] + spread >= stop:
                return False, k - i, stop, target
            if l[k] + spread <= target:
                return True, k - i, stop, target
    return False, HORIZON, stop, target


def _bars(df, lo, hi):
    idx = df.index[lo:hi]
    t = ((idx - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1)).to_numpy().astype(int)
    sub = df.iloc[lo:hi]
    return [{"time": int(a), "open": round(float(b), 2), "high": round(float(c), 2), "low": round(float(d), 2),
             "close": round(float(e), 2)} for a, b, c, d, e in zip(t, sub["open"], sub["high"], sub["low"], sub["close"])]


def build(symbol: str = "XAUUSD", n_questions: int = 40, exam_share: float = 0.25, point: float = 0.01, seed: int = 7):
    from .history import load_bars
    df = load_bars(symbol)
    print(f"looking for pro setups in {len(df):,} candles ({df.index[0]:%Y-%m-%d} -> {df.index[-1]:%Y-%m-%d})...", flush=True)
    f = build_features(df, point)
    a = atr(df, 14).to_numpy()
    df_np = tuple(df[k].to_numpy() for k in ("open", "high", "low", "close"))
    spread = df["spread"].to_numpy(dtype=float) * point
    cands = _candidates(f)
    for k, v in cands.items():
        print(f"  {SETUP_NAMES[k] if k != 'wait' else 'No setup (stay out)'}: {len(v):,} candidates", flush=True)

    rng = np.random.default_rng(seed)
    n_wait = max(4, round(n_questions * 0.2))
    n_trade = n_questions - n_wait
    kinds = [k for k in PRO_SETUPS if len(cands[k])]
    if not kinds:
        raise SystemExit("No pro setups found. Download more history (Train tab) and try again.")
    orders = {k: rng.permutation(cands[k]) for k in kinds + ["wait"]}
    pos = {k: 0 for k in orders}
    used_days, questions = set(), []

    def day_of(i):
        return df.index[i].date()

    def take(kind):
        """Next usable candle for this setup: a pro trade that worked (or, for wait, one where both sides failed)."""
        arr = orders[kind]
        while pos[kind] < len(arr):
            i = int(arr[pos[kind]])
            pos[kind] += 1
            if i < 3000 or i + HORIZON >= len(df) or day_of(i) in used_days or not a[i] > 0:
                continue
            if kind == "wait":
                sd = 1.5 * a[i]
                won_b, *_ = _trade(df_np, i, "buy", sd, spread[i])
                won_s, *_ = _trade(df_np, i, "sell", sd, spread[i])
                if won_b or won_s:
                    continue
                return i, "wait", None
            side = PRO_SETUPS[kind][0]
            if kind.startswith("sweep"):        # stop just beyond the sweep's wick
                if side == "buy":
                    sd = df_np[3][i] + spread[i] - df_np[2][i - 4:i + 1].min() + 0.2 * a[i]
                else:
                    sd = df_np[1][i - 4:i + 1].max() - df_np[3][i] + 0.2 * a[i]
                sd = float(np.clip(sd, 0.8 * a[i], 3 * a[i]))
            else:
                sd = 1.5 * a[i]
            won, mins, stop, target = _trade(df_np, i, side, sd, spread[i])
            if won:
                return i, side, {"minutes": int(mins), "stop": round(float(stop), 2), "target": round(float(target), 2),
                                 "entry": round(float(df_np[3][i] + (spread[i] if side == "buy" else 0)), 2)}
        return None

    # round-robin over the setups so the quiz covers all of them, then the wait questions
    plan = [kinds[j % len(kinds)] for j in range(n_trade)] + ["wait"] * n_wait
    for kind in plan:
        got = take(kind)
        if got is None:                          # this setup ran out; use any other that still has candidates
            for other in kinds:
                got = take(other)
                if got:
                    kind = other
                    break
        if got is None:
            continue
        i, answer, trade = got
        used_days.add(day_of(i))
        t = df.index[i]
        text = PRO_SETUPS[kind][1] if kind != "wait" else WAIT_TEXT
        if trade:
            text += (f" Entry {trade['entry']:.2f}, stop {trade['stop']:.2f}, target {trade['target']:.2f} (2R): "
                     f"it reached the target {trade['minutes']} minutes later.")
        questions.append({
            "time": str(t), "setup": kind, "setup_name": SETUP_NAMES[kind] if kind != "wait" else "No setup (stay out)",
            "answer": answer, "explanation": text, "trade": trade,
            "x": [None if v != v else round(float(v), 5) for v in f.iloc[i].to_numpy()],
            "bars": _bars(df, i - 89, i + 1), "after": _bars(df, i + 1, min(len(df), i + 61)),
        })
    if len(questions) < 10:
        raise SystemExit(f"Only found {len(questions)} usable questions. Download more history and try again.")
    order = rng.permutation(len(questions))
    questions = [questions[k] for k in order]
    n_exam = max(3, round(len(questions) * exam_share))
    if len(questions) - n_exam < 30 and len(questions) >= 33:
        n_exam = len(questions) - 30
    for k, q in enumerate(questions):
        q["id"] = k + 1
        q["set"] = "exam" if k >= len(questions) - n_exam else "practice"

    # scale inputs with statistics from the whole history, so live answers use the same scale
    sample = f.dropna().sample(min(50_000, len(f.dropna())), random_state=seed)
    norm = {"mean": sample.mean().round(6).tolist(), "std": sample.std().replace(0, 1).round(6).tolist()}
    quiz = {"symbol": symbol, "built": datetime.now(timezone.utc).isoformat(timespec="seconds"), "features": list(f.columns),
            "norm": norm, "points": POINTS, "mastery": MASTERY, "questions": questions}
    _write(QUIZ, quiz)
    prac = sum(q["set"] == "practice" for q in questions)
    by = pd.Series([q["answer"] for q in questions]).value_counts().to_dict()
    print(f"saved {len(questions)} questions ({prac} practice, {len(questions) - prac} exam; answers {by}) to data/quiz.json",
          flush=True)
    return quiz


# ---------------------------------------------------------------- the agent (policy) and its reward

def points_for(action: str, answer: str) -> tuple[int, str]:
    if action == answer:
        return POINTS["right"], "right"
    if answer == "wait":
        return POINTS["traded_should_wait"], "should have waited"
    if action == "wait":
        return POINTS["missed_trade"], "missed a good trade"
    return POINTS["wrong_way"], "wrong way"


class QuizPolicy:
    """Softmax policy over buy / sell / wait. Its objective is the points it earns: nothing else."""

    def __init__(self, features, mean, std, W=None, b=None, meta=None):
        self.features = list(features)
        self.mean, self.std = np.asarray(mean, float), np.asarray(std, float)
        d = len(self.features)
        self.W = np.zeros((3, d)) if W is None else np.asarray(W, float)
        self.b = np.zeros(3) if b is None else np.asarray(b, float)
        self.meta = meta or {}

    def x(self, raw) -> np.ndarray:
        v = np.asarray([np.nan if r is None else r for r in raw], float)
        z = (v - self.mean) / self.std
        return np.clip(np.nan_to_num(z), -5, 5)

    def probs(self, x: np.ndarray) -> np.ndarray:
        s = self.W @ x + self.b
        e = np.exp(s - s.max())
        return e / e.sum()

    def learn(self, x, action_idx: int, advantage: float, lr: float):
        """REINFORCE: raise the log-probability of the action in proportion to how many more points it earned."""
        p = self.probs(x)
        g = -p
        g[action_idx] += 1
        self.W += lr * advantage * np.outer(g, x)
        self.b += lr * advantage * g

    def answer_row(self, row: dict) -> dict:
        x = self.x([row.get(k) for k in self.features])
        p = self.probs(x)
        return {"action": ACTIONS[int(p.argmax())], "probs": {a: round(float(v), 3) for a, v in zip(ACTIONS, p)}}

    def save(self, path: Path = POLICY):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"features": self.features, "mean": self.mean.tolist(), "std": self.std.tolist(),
                                    "W": self.W.round(6).tolist(), "b": self.b.round(6).tolist(), "meta": self.meta}))

    @classmethod
    def load(cls, path: Path = POLICY):
        d = json.loads(path.read_text())
        return cls(d["features"], d["mean"], d["std"], d["W"], d["b"], d.get("meta"))


def load_policy():
    try:
        return QuizPolicy.load()
    except (OSError, ValueError, KeyError):
        return None


def read_control() -> dict:
    return _load_json(CONTROL, {"speed": 20, "stop": False})


def train(max_rounds: int = 3000, lr: float = 0.02, seed: int = 1):
    quiz = _load_json(QUIZ, None)
    if not quiz:
        raise SystemExit("No quiz yet. Build it first (Quiz tab -> Build quiz).")
    qs = quiz["questions"]
    practice = [q for q in qs if q["set"] == "practice"]
    exam = [q for q in qs if q["set"] == "exam"]
    pol = QuizPolicy(quiz["features"], quiz["norm"]["mean"], quiz["norm"]["std"])
    X = {q["id"]: pol.x(q["x"]) for q in qs}
    rng = np.random.default_rng(seed)
    streak = {q["id"]: 0 for q in practice}
    best = {q["id"]: 0 for q in practice}
    right_total = {q["id"]: 0 for q in practice}
    asked_total = {q["id"]: 0 for q in practice}
    points, asked, baseline = 0, 0, 0.0
    points_by_round = []
    started = time.time()
    last_write = 0.0
    ctl, ctl_read = read_control(), time.time()
    due = time.time()
    print(f"quiz: {len(practice)} practice questions, {len(exam)} exam questions. Points are the reward: right "
          f"{POINTS['right']:+d}, wrong way {POINTS['wrong_way']:+d}, traded when it should wait "
          f"{POINTS['traded_should_wait']:+d}, missed a good trade {POINTS['missed_trade']:+d}. "
          f"Goal: every question right {MASTERY} times in a row.", flush=True)

    def state(q=None, act=None, p=None, pts=0, verdict="", done=False, rnd=0, exam_result=None, stopped=False):
        mastered = sum(1 for v in streak.values() if v >= MASTERY)
        s = {"running": not done, "done": done, "stopped": stopped, "round": rnd, "asked": asked, "points": points,
             "mastered": mastered, "practice": len(practice), "exam_size": len(exam), "mastery": MASTERY,
             "streaks": [{"id": k, "streak": streak[k], "best": best[k], "right": right_total[k], "asked": asked_total[k]}
                         for k in streak],
             "points_by_round": points_by_round[-200:], "speed": ctl.get("speed", 20),
             "elapsed": round(time.time() - started), "exam": exam_result,
             "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        if q is not None:
            s["question"] = {k: q[k] for k in ("id", "time", "setup_name", "bars", "after", "answer", "explanation", "set", "trade")}
            s["agent"] = {"action": act, "probs": {a: round(float(v), 3) for a, v in zip(ACTIONS, p)}, "points": pts,
                          "verdict": verdict, "correct": act == q["answer"]}
        _write(STATE, s)

    rnd, stopped = 0, False
    while rnd < max_rounds:
        rnd += 1
        round_points = 0
        for qi in rng.permutation(len(practice)):
            q = practice[qi]
            if time.time() - ctl_read > 0.2:
                ctl, ctl_read = read_control(), time.time()
            if ctl.get("stop"):
                stopped = True
                break
            x = X[q["id"]]
            p = pol.probs(x)
            a_idx = int(rng.choice(3, p=p))
            act = ACTIONS[a_idx]
            pts, verdict = points_for(act, q["answer"])
            # the reward: points. Better than usual -> do more of that; worse -> do less.
            pol.learn(x, a_idx, (pts - baseline) / 10.0, lr)
            baseline += 0.02 * (pts - baseline)
            points += pts
            round_points += pts
            asked += 1
            asked_total[q["id"]] += 1
            if act == q["answer"]:
                streak[q["id"]] += 1
                right_total[q["id"]] += 1
                best[q["id"]] = max(best[q["id"]], streak[q["id"]])
            else:
                streak[q["id"]] = 0
            speed = float(ctl.get("speed", 20))
            now = time.time()
            if speed and speed <= 30 or now - last_write > 0.25:
                state(q, act, p, pts, verdict, rnd=rnd)
                last_write = now
            if speed > 0:
                due = max(due, now - 0.5) + 1.0 / speed
                if due - now > 0.003:
                    time.sleep(due - now)
        if stopped:
            break
        points_by_round.append(round_points)
        mastered = sum(1 for v in streak.values() if v >= MASTERY)
        if rnd % 10 == 0 or mastered == len(practice):
            print(f"round {rnd}: {mastered}/{len(practice)} questions mastered ({MASTERY} right in a row), "
                  f"{round_points:+d} points this round, {points:+,d} total", flush=True)
        if mastered == len(practice):
            break

    # exam: questions it never trained on, answered with its best guess (no sampling)
    exam_result = None
    if exam:
        rows, exam_pts = [], 0
        for q in exam:
            p = pol.probs(X[q["id"]])
            act = ACTIONS[int(p.argmax())]
            pts, verdict = points_for(act, q["answer"])
            exam_pts += pts
            rows.append({"id": q["id"], "setup_name": q["setup_name"], "answer": q["answer"], "action": act,
                         "correct": act == q["answer"], "points": pts})
        right = sum(r["correct"] for r in rows)
        exam_result = {"right": right, "total": len(rows), "points": exam_pts, "rows": rows,
                       "chance": round(100 / 3, 1), "pct": round(100 * right / len(rows), 1)}
    mastered = sum(1 for v in streak.values() if v >= MASTERY)
    pol.meta = {"trained": datetime.now(timezone.utc).isoformat(timespec="seconds"), "rounds": rnd, "asked": asked,
                "points": points, "mastered": mastered, "practice": len(practice), "exam": exam_result,
                "quiz_built": quiz["built"]}
    pol.save()
    state(done=True, rnd=rnd, exam_result=exam_result, stopped=stopped)
    print(f"\n{'stopped' if stopped else 'finished'} after {rnd} rounds, {asked:,} answers, {points:+,d} points. "
          f"Mastered {mastered}/{len(practice)}.", flush=True)
    if exam_result:
        print(f"exam (never-seen questions): {exam_result['right']}/{exam_result['total']} right "
              f"({exam_result['pct']}%, guessing would be ~33%), {exam_result['points']:+d} points", flush=True)
    print("saved the quiz agent to models/quiz_policy.json", flush=True)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--symbol", default="XAUUSD")
    b.add_argument("--questions", type=int, default=40)
    b.add_argument("--point", type=float, default=0.01)
    b.add_argument("--seed", type=int, default=7)
    t = sub.add_parser("train")
    t.add_argument("--max-rounds", type=int, default=3000)
    t.add_argument("--lr", type=float, default=0.02)
    a = ap.parse_args()
    if a.cmd == "build":
        build(a.symbol, max(34, a.questions), point=a.point, seed=a.seed)
    else:
        train(a.max_rounds, a.lr)


if __name__ == "__main__":
    main()
