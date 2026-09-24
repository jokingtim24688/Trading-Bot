"""Quiz school: the bot answers "what do you do here?" on real gold situations and learns from points (reinforcement learning).

    python -m agent.quiz bank --watch             # one question creator keeps the question bank up to date (always on)
    python -m agent.quiz build --questions 1000   # pick a quiz from the bank (0 = every usable question; no maximum)
    python -m agent.quiz train                    # quiz the agent until it gets every question right 5 times in a row

The question bank (data/quiz_bank/)
    Questions are made from history in fixed half-years. One question creator works at all times in the background,
    below normal priority, and only redoes a half-year when its candles change (so new candles only touch the latest
    one). Build quiz wakes up all 10 creators (the other 9 are idle until then) to finish anything left, then picks
    the quiz from the bank. The whole bank is also written as markdown: data/quiz_bank/README.md and one table per
    year in data/quiz_bank/questions/.

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
    After a wrong answer it is also shown the right answer and learns it straight away, and that question's retries
    are swapped for random section-mates (its 5 closest look-alikes with the same setup and answer), so it learns the
    pattern rather than one chart; the 5th right answer in a row is always on the question itself.
    A question counts as mastered once it has been answered right 5 times in a row; mastered questions keep coming up
    so it doesn't forget them, and unfinished questions are asked 2 extra times per round. It never gives up on its
    own: when no new question is finished for 100 rounds it asks the stuck ones 7 extra times with 3x bigger learning
    steps, then doubles its network (64 -> 512 units, keeping what it learned), then shakes up the stuck questions and
    loops again, until every question is finished or you press Stop. Then it sits the exam and writes its lessons to
    the quiz-lessons skill. "Continue" picks up the saved agent and progress; "focus" works only on the questions you
    pick (finished ones are left out).

Files: data/quiz_bank/ (the bank + markdown), data/quiz_cache/slices/ (saved creator results per half-year),
data/quiz.json (questions), data/quiz_x.npy (inputs), data/quiz_bars.npy + data/quiz_times.npy (charts),
models/quiz_policy.json (the trained agent), data/quiz_state.json (live progress for the app).
"""
import argparse
import hashlib
import json
import os
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
QC = DATA / "quiz_c.npy"
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
SPACINGS = (60, 30, 15, 10)                # minutes between questions; tightens only when more are needed
MAX_SHARE = {"trade": 1.0, "trap": 2 * TRAP_SHARE, "wait": 2 * WAIT_SHARE}   # most a group may reach when others run out


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


def _group(key) -> str:
    """A pool's group: clean trade, trap or stay-out."""
    return "trap" if key[2] else "wait" if key[0] == "wait" else "trade"


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


CACHE_DIR = DATA / "quiz_cache"
SLICE_DIR = CACHE_DIR / "slices"
BUILD_STATE = DATA / "quiz_build.json"
CACHE_VERSION = 2
WARMUP = 30_000                   # candles of warm-up before each slice, so its indicators match the full run
MAX_CREATORS = 10                 # question creators (finder processes) working at once by default
CREATOR_GB = 0.6                  # RAM one creator needs for a half-year slice
SAMPLE_ROWS = 3000                # rows per slice used to scale the inputs (mean/std)
TRADE_FIELDS = ("t", "won", "mins", "mae", "stop", "target", "entry")


def default_workers() -> int:
    """Question creators at once: up to 10, never more than the CPU threads minus two, fewer if RAM is short."""
    threads = os.cpu_count() or 4
    try:
        import psutil
        free_gb = psutil.virtual_memory().available / 1e9
    except Exception:                                    # noqa: BLE001
        free_gb = 8.0
    return max(1, min(MAX_CREATORS, threads - 2, int(free_gb * 0.7 / CREATOR_GB)))


def _lower_priority():
    """Question creators run below normal priority, so trading and the app stay smooth while they work."""
    try:
        import psutil
        p = psutil.Process()
        p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 10)
    except Exception:                                    # noqa: BLE001
        pass


class _Progress:
    """Build progress for the app (data/quiz_build.json, or the bank's status file); creators write their own files
    next to it."""

    def __init__(self, workers, path: Path = BUILD_STATE, prefix: str = "quiz_build_w"):
        self.t0, self.workers, self.path, self.prefix = time.time(), workers, path, prefix
        self.stage, self.pct, self.cached, self.labels, self.short = "starting", 0.0, False, [], ""
        self.extra: dict = {}
        for p in DATA.glob(f"{prefix}*.json"):
            p.unlink(missing_ok=True)

    def worker_file(self, k: int) -> Path:
        return DATA / f"{self.prefix}{k}.json"

    def set(self, stage=None, pct=None, done=False):
        self.stage = stage or self.stage
        self.pct = self.pct if pct is None else pct
        finders = []
        for k, label in enumerate(self.labels):
            w = _load_json(self.worker_file(k), {})
            finders.append({"label": label, "stage": w.get("stage", "waiting"), "pct": w.get("pct", 0)})
        _write(self.path, {"running": not done, "done": done, "stage": self.stage, "pct": round(self.pct, 3),
                           "elapsed": round(time.time() - self.t0, 1), "cached": self.cached, "workers": self.workers,
                           "short": self.short, "finders": finders, **self.extra})


def _find(job):
    """One question creator: every pro setup and stay-out spot in its half-year of history, and what happened after
    each. Runs in its own process; up to 10 run at once on different half-years and the bank merges what they find.
    Candidates are identified by their candle time, so saved results stay valid when earlier history is added."""
    k, wfile, lo, own_lo, own_hi, total, times_ns, ohlc, spread_pts, point, label, low = job
    if low:
        _lower_priority()

    def report(stage, pct):
        _write(Path(wfile), {"stage": stage, "pct": round(pct, 3)})

    report("reading indicators", 0.02)
    df = pd.DataFrame(ohlc, columns=["open", "high", "low", "close"], index=pd.DatetimeIndex(times_ns, tz="UTC"))
    df["tick_volume"] = 0
    df["spread"] = spread_pts
    f = build_features(df, point)
    a = atr(df, 14).to_numpy()
    df_np = tuple(df[c].to_numpy() for c in ("open", "high", "low", "close"))
    spread = spread_pts.astype(float) * point
    report("finding setups", 0.5)
    cands = _candidates(f)
    s0, s1 = own_lo - lo, own_hi - lo                    # this creator's own candles (the rest is warm-up/look-ahead)

    def usable(v):
        g = v + lo
        return v[(v >= s0) & (v < s1) & (g >= 3000) & (g + HORIZON < total) & (a[v] > 0)]

    out = {}
    kinds = list(PRO_SETUPS)
    for j, kind in enumerate(kinds):
        side = PRO_SETUPS[kind][0]
        idx = usable(cands[kind])
        if len(idx):
            sd = _stop_dist(kind, idx, df_np, a, spread)
            won, mins, mae, stop, target, entry = _outcomes(df_np, idx, side, sd, spread)
            out[kind] = {"t": times_ns[idx], "won": won, "mins": mins.astype(np.int16), "mae": mae.astype(np.float32),
                         "stop": stop, "target": target, "entry": entry}
        report("checking what happened", 0.5 + 0.45 * (j + 1) / (len(kinds) + 1))
    idx = usable(cands["wait"])
    if len(idx):
        sd = 1.5 * a[idx]
        wb, mb, eb, *_ = _outcomes(df_np, idx, "buy", sd, spread)
        ws, ms, es, *_ = _outcomes(df_np, idx, "sell", sd, spread)
        out["wait"] = {"t": times_ns[idx], "clean_b": wb & (mb <= CLEAN_MINUTES) & (eb <= CLEAN_MAE),
                       "clean_s": ws & (ms <= CLEAN_MINUTES) & (es <= CLEAN_MAE)}
    local = np.unique(np.concatenate([np.searchsorted(times_ns, v["t"]) for v in out.values()])) if out else \
        np.zeros(0, np.int64)
    X = f.to_numpy(np.float32)[local] if len(local) else np.zeros((0, f.shape[1]), np.float32)
    own = f.iloc[s0:s1].dropna()
    seed = int(hashlib.md5(label.encode()).hexdigest()[:8], 16)
    sample = own.sample(min(len(own), SAMPLE_ROWS), random_state=seed).to_numpy(np.float32) if len(own) else \
        np.zeros((0, f.shape[1]), np.float32)
    report("done", 1.0)
    return {"label": label, "out": out, "t": times_ns[local], "X": X, "sample": sample, "columns": list(f.columns)}


def _history_sig(symbol: str) -> list:
    """Cheap fingerprint of the history files (size + time changed): the bank watcher checks it every minute."""
    files = []
    for name in (f"{symbol}_M1.parquet", f"{symbol}_M1_history.parquet"):
        p = DATA / name
        if p.exists():
            st = p.stat()
            files.append([name, st.st_size, int(st.st_mtime)])
    return files


def _slice_plan(df) -> list[tuple[str, int, int]]:
    """Fixed calendar half-years (2016H1, 2016H2, ...). A slice's candles, and so its saved results, only change
    when its own data changes: new candles only ever touch the latest slice."""
    t = df.index.asi8
    first, last = df.index[0], df.index[-1]
    edges = [pd.Timestamp(year=y, month=m, day=1, tz="UTC") for y in range(first.year, last.year + 2) for m in (1, 7)]
    pos = np.searchsorted(t, [e.as_unit("ns").value for e in edges])
    return [(f"{edges[k].year}H{1 if edges[k].month == 1 else 2}", int(pos[k]), int(pos[k + 1]))
            for k in range(len(edges) - 1) if pos[k + 1] > pos[k]]


def _slice_hash(label, lo, hi, times_ns, ohlc, spread_pts, point) -> str:
    h = hashlib.blake2b(digest_size=16)
    h.update(json.dumps([CACHE_VERSION, label, point, HORIZON, CLEAN_MINUTES, CLEAN_MAE, list(SESSION), WARMUP,
                         hi - lo]).encode())
    for arr in (times_ns[lo:hi], ohlc[lo:hi], spread_pts[lo:hi]):
        h.update(np.ascontiguousarray(arr).tobytes())
    return h.hexdigest()


def _save_slice(label: str, r: dict):
    SLICE_DIR.mkdir(parents=True, exist_ok=True)
    arrays = {"t": r["t"], "X": r["X"], "sample": r["sample"]}
    for kind, d in r["out"].items():
        for field, v in d.items():
            arrays[f"{kind}__{field}"] = v
    tmp = SLICE_DIR / f"{label}.tmp.npz"
    np.savez(tmp, **arrays)
    tmp.replace(SLICE_DIR / f"{label}.npz")


def _load_slice(label: str, columns: list) -> dict:
    z = np.load(SLICE_DIR / f"{label}.npz")
    r = {"label": label, "t": z["t"], "X": z["X"], "sample": z["sample"], "columns": columns, "out": {}}
    for name in z.files:
        if "__" in name:
            kind, field = name.split("__", 1)
            r["out"].setdefault(kind, {})[field] = z[name]
    return r


def _slice_jobs(df, point):
    """Every half-year slice with its fingerprint, and whether its saved results still match it."""
    n = len(df)
    times_ns = df.index.asi8
    ohlc = df[["open", "high", "low", "close"]].to_numpy(np.float64)
    spread_pts = df["spread"].to_numpy(np.float64)
    index = _load_json(SLICE_DIR / "index.json", {})
    plan = []
    for label, own_lo, own_hi in _slice_plan(df):
        lo, hi = max(0, own_lo - WARMUP), min(n, own_hi + HORIZON + 1)
        hsh = _slice_hash(label, lo, hi, times_ns, ohlc, spread_pts, point)
        saved = index.get(label, {})
        fresh = saved.get("hash") == hsh and (SLICE_DIR / f"{label}.npz").exists()
        plan.append({"label": label, "lo": lo, "own_lo": own_lo, "own_hi": own_hi, "hi": hi, "hash": hsh,
                     "fresh": fresh, "columns": saved.get("columns")})
    return plan, (times_ns, ohlc, spread_pts)


def _find_all(df, point, workers, prog, plan=None, arrays=None, low=False, should_yield=None):
    """Up to 10 question creators work through the half-years at once, each taking the next one when it finishes.
    Half-years whose candles haven't changed are loaded from their saved results instead of being redone."""
    if plan is None:
        plan, arrays = _slice_jobs(df, point)
    times_ns, ohlc, spread_pts = arrays
    n = len(df)
    todo = [p for p in plan if not p["fresh"]]
    workers = max(1, min(workers, len(todo) or 1))
    prog.labels = [p["label"] for p in plan]
    prog.workers = workers
    prog.cached = not todo
    for k, p in enumerate(plan):
        if p["fresh"]:
            _write(prog.worker_file(k), {"stage": "saved earlier", "pct": 1.0})
    print(f"  {len(plan)} half-years of history ({plan[0]['label']} to {plan[-1]['label']}): "
          f"{len(plan) - len(todo)} saved earlier, {len(todo)} to do with {workers} question creator(s) at once",
          flush=True)
    prog.set("question creators at work" if todo else "using saved results", 0.05)
    index = _load_json(SLICE_DIR / "index.json", {})
    results = {}
    jobs = [(k, str(prog.worker_file(k)), p["lo"], p["own_lo"], p["own_hi"], n, times_ns[p["lo"]:p["hi"]],
             ohlc[p["lo"]:p["hi"]], spread_pts[p["lo"]:p["hi"]], point, p["label"], low)
            for k, p in enumerate(plan) if not p["fresh"]]

    def keep(r):
        _save_slice(r["label"], r)
        index[r["label"]] = {"hash": next(p["hash"] for p in plan if p["label"] == r["label"]), "columns": r["columns"]}
        _write(SLICE_DIR / "index.json", index)
        results[r["label"]] = r

    if jobs and workers == 1:
        for j in jobs:
            if should_yield and should_yield():          # a build wants all 10 creators: step aside, keep what's saved
                return None
            keep(_find(j))
            prog.set("question creators at work", 0.05 + 0.6 * len(results) / len(jobs))
    elif jobs:
        from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
        with ProcessPoolExecutor(max_workers=workers) as ex:
            pending = {ex.submit(_find, j) for j in jobs}
            while pending:
                done, pending = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
                for fut in done:
                    keep(fut.result())
                prog.set("question creators at work", 0.05 + 0.6 * len(results) / len(jobs))
    columns = next((r["columns"] for r in results.values()), None) or next(p["columns"] for p in plan if p["columns"])
    parts = [results.get(p["label"]) or _load_slice(p["label"], columns) for p in plan]
    out: dict = {}
    for r in parts:
        for kind, d in r["out"].items():
            for k2, v in d.items():
                out.setdefault(kind, {}).setdefault(k2, []).append(v)
    out = {kind: {k2: np.concatenate(v) for k2, v in d.items()} for kind, d in out.items()}
    for d in out.values():                               # candle positions in today's history
        d["idx"] = np.searchsorted(times_ns, d["t"])
    sample = np.vstack([r["sample"] for r in parts])
    mean = np.nanmean(sample, 0)
    std = np.nanstd(sample, 0, ddof=1)
    std[~(std > 0)] = 1.0
    t_all = np.concatenate([r["t"] for r in parts])
    return {"out": out, "pos": np.searchsorted(times_ns, t_all), "X": np.vstack([r["X"] for r in parts]),
            "mean": mean, "std": std, "columns": columns}


class _Neighbours:
    """Each question's 5 closest look-alikes, kept up to date as questions are added (so top-ups only compare the new
    ones), computed on several CPU threads. Near-twins vote: a question is a contradiction only when near-twins with
    the other answer outnumber it and its same-answer twins (on a tie the older question stays), so a new look-alike
    can't knock out a well-supported question. Also flags near-copies (an earlier near-identical question, same answer)."""

    def __init__(self, k=5, twin=3.0, dup=1.0, threads=None):
        import os
        self.k, self.t2, self.d2 = k, twin * twin, dup * dup
        self.threads = threads or max(1, os.cpu_count() or 1)
        self.Z = None

    def _map(self, fn, starts):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=self.threads) as ex:
            list(ex.map(fn, starts))

    def add(self, Znew, ans_new):
        Znew = Znew.astype(np.float32)
        k, m = self.k, len(Znew)
        if self.Z is None:
            n0 = 0
            self.Z, self.ans = Znew, ans_new
            self.nd = np.full((m, k), np.inf, np.float32)
            self.na = np.empty((m, k), ans_new.dtype)
            self.same, self.other = np.zeros(m, np.int32), np.zeros(m, np.int32)
            self.older_other = np.zeros(m, bool)
            self.dupe = np.zeros(m, bool)
        else:
            n0 = len(self.Z)
            self.Z, self.ans = np.vstack([self.Z, Znew]), np.concatenate([self.ans, ans_new])
            self.nd = np.vstack([self.nd, np.full((m, k), np.inf, np.float32)])
            self.na = np.concatenate([self.na, np.empty((m, k), ans_new.dtype)])
            self.same = np.concatenate([self.same, np.zeros(m, np.int32)])
            self.other = np.concatenate([self.other, np.zeros(m, np.int32)])
            self.older_other = np.concatenate([self.older_other, np.zeros(m, bool)])
            self.dupe = np.concatenate([self.dupe, np.zeros(m, bool)])
        Z, ans, n = self.Z, self.ans, len(self.Z)
        sq = (Z * Z).sum(1)
        step = max(64, min(2048, 20_000_000 // max(1, n)))

        def new_rows(s):                                 # the new questions against everything
            r = np.arange(n0 + s, min(n, n0 + s + step))
            d2 = Z[r] @ Z.T                                # squared distances, built in place (no big temporaries)
            d2 *= -2
            d2 += sq[None, :]
            d2 += sq[r, None]
            d2[np.arange(len(r)), r] = np.inf
            ii, jj = np.nonzero(d2 < self.t2)              # near pairs are rare: check only those
            if len(ii):
                other = ans[r[ii]] != ans[jj]
                self.other[r] = np.bincount(ii[other], minlength=len(r))
                self.same[r] = np.bincount(ii[~other], minlength=len(r))
                self.older_other[r[np.unique(ii[other & (jj < r[ii])])]] = True
                cp = ~other & (d2[ii, jj] < self.d2) & (jj < r[ii])
                self.dupe[r[np.unique(ii[cp])]] = True
            if n > k:
                nn = np.argpartition(d2, k, axis=1)[:, :k]
                self.nd[r] = np.take_along_axis(d2, nn, 1)
                self.na[r] = ans[nn]

        def old_rows(s):                                 # older questions: merge in the new ones as look-alikes
            r = np.arange(s, min(n0, s + step))
            d2 = Z[r] @ Z[n0:].T
            d2 *= -2
            d2 += sq[None, n0:]
            d2 += sq[r, None]
            ii, jj = np.nonzero(d2 < self.t2)
            if len(ii):
                other = ans[r[ii]] != ans[n0 + jj]
                self.other[r] += np.bincount(ii[other], minlength=len(r)).astype(np.int32)
                self.same[r] += np.bincount(ii[~other], minlength=len(r)).astype(np.int32)
            cand_d = np.hstack([self.nd[r], d2])
            cand_a = np.hstack([self.na[r], np.broadcast_to(ans[None, n0:], d2.shape)])
            nn = np.argpartition(cand_d, k, axis=1)[:, :k] if cand_d.shape[1] > k else np.arange(cand_d.shape[1])[None].repeat(len(r), 0)
            self.nd[r] = np.take_along_axis(cand_d, nn, 1)
            self.na[r] = np.take_along_axis(cand_a, nn, 1)

        self._map(new_rows, range(0, m, step))
        if n0:
            self._map(old_rows, range(0, n0, step))

    def restore(self, Z, ans, saved: dict):
        """Pick up from a saved bank, so only new questions need comparing."""
        self.Z, self.ans = Z.astype(np.float32), np.asarray(ans)
        self.nd, self.na = saved["nd"].astype(np.float32), saved["na"].astype(self.ans.dtype)
        self.same, self.other = saved["same"].astype(np.int32), saved["other"].astype(np.int32)
        self.older_other, self.dupe = saved["older"].astype(bool), saved["dupe"].astype(bool)

    def result(self):
        own = self.same + 1                                # a question votes for its own answer
        contra = (self.other > own) | ((self.other == own) & self.older_other)
        if len(self.Z) <= self.k:
            return np.ones(len(self.Z)), contra, self.dupe
        return (self.na == self.ans[:, None]).mean(1), contra, self.dupe


# ---------------------------------------------------------------- the question bank
# One question creator keeps turning history into questions at all times (in the background, below normal priority);
# the Build quiz button wakes up all 10 creators to finish whatever is left, then picks the quiz from the bank.
BANK_DIR = DATA / "quiz_bank"
BANK = BANK_DIR / "bank.npz"
BANK_META = BANK_DIR / "meta.json"
BANK_STATUS = BANK_DIR / "status.json"
BANK_LOCK = BANK_DIR / "lock"
BUILD_REQUEST = BANK_DIR / "build_request"
BANK_MD = BANK_DIR / "questions"
BANK_VERSION = 1
KINDS = list(PRO_SETUPS) + ["wait"]
BANK_FIELDS = ("t", "kind", "ans", "trap", "quality", "mins", "stop", "target", "entry", "X",
               "nd", "na", "same", "other", "older", "dupe")
SHARE = {"trade": 1 - TRAP_SHARE - WAIT_SHARE, "trap": TRAP_SHARE, "wait": WAIT_SHARE}


class _BankLock:
    """Only one process updates the bank at a time. A build asks the background creator to step aside
    (BUILD_REQUEST); it does so after the half-year it is working on."""

    def __init__(self, prog=None, wait_stage="waiting for the background question creator to save its work"):
        self.prog, self.wait_stage = prog, wait_stage

    def __enter__(self):
        BANK_DIR.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                fd = os.open(BANK_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return self
            except FileExistsError:
                if self._stale():
                    BANK_LOCK.unlink(missing_ok=True)
                    continue
                if self.prog:
                    self.prog.set(self.wait_stage)
                time.sleep(0.5)

    def __exit__(self, *exc):
        BANK_LOCK.unlink(missing_ok=True)

    @staticmethod
    def _stale() -> bool:
        try:
            text, age = BANK_LOCK.read_text().strip(), time.time() - BANK_LOCK.stat().st_mtime
        except OSError:
            return False
        if not text:
            return age > 10
        try:
            import psutil
            return not psutil.pid_exists(int(text))
        except (ImportError, ValueError):
            return age > 3 * 3600


def _stable_random(t: np.ndarray) -> np.ndarray:
    """A fixed 'random' order for stay-out spots, the same on every update."""
    return ((t.astype(np.uint64) // np.uint64(60_000_000_000) * np.uint64(2654435761)) % np.uint64(1 << 32)
            ).astype(np.float64) / (1 << 32)


def _bank_pools(raw, years, t_min=None):
    """Clean pro winners, traps (quick failures) and clean stay-out spots, best examples first across years (only
    those after t_min when topping up the bank). Also returns each pool's trade details."""
    pools, details = {}, {}
    for kind, (side, _) in PRO_SETUPS.items():
        d = raw["out"].get(kind)
        if d is None or not len(d["idx"]):
            continue
        idx, won, mins, mae = d["idx"], d["won"], d["mins"].astype(float), d["mae"].astype(float)
        new = d["t"] > t_min if t_min is not None else np.ones(len(idx), bool)
        clean = won & (mins <= CLEAN_MINUTES) & (mae <= CLEAN_MAE) & new
        trap = ~won & (mins <= TRAP_MINUTES) & new
        for mask, is_trap, quality in ((clean, False, (1 - mae) + (1 - mins / CLEAN_MINUTES)),
                                       (trap, True, 1 - mins / TRAP_MINUTES)):
            sel = np.flatnonzero(mask)
            key = (kind, "wait" if is_trap else side, is_trap)
            order = _year_balanced(np.arange(len(sel)), quality[sel], years[idx[sel]])
            pools[key] = idx[sel][order]
            details[key] = {"pos": idx[sel][order], "t": d["t"][sel][order], "quality": quality[sel][order],
                            "mins": d["mins"][sel][order], "stop": d["stop"][sel][order],
                            "target": d["target"][sel][order], "entry": d["entry"][sel][order]}
    d = raw["out"].get("wait")
    if d is not None and len(d["idx"]):
        new = d["t"] > t_min if t_min is not None else np.ones(len(d["idx"]), bool)
        sel = np.flatnonzero(~d["clean_b"] & ~d["clean_s"] & new)
        q = _stable_random(d["t"][sel])
        order = _year_balanced(np.arange(len(sel)), q, years[d["idx"][sel]])
        key = ("wait", "wait", False)
        pools[key] = d["idx"][sel][order]
        z = np.zeros(len(sel))
        details[key] = {"pos": d["idx"][sel][order], "t": d["t"][sel][order], "quality": q[order],
                        "mins": z.astype(np.int16), "stop": z, "target": z, "entry": z}
    return pools, details


def _select_all(pools, occupied, counts):
    """Take every candidate the spacing rules allow (60 -> 30 -> 15 -> 10 minutes apart, tightening only for what is
    left), keeping the 65/15/20 mix while it lasts and never letting traps or stay-outs swamp the bank."""
    by_group = {g: [k for k in pools if _group(k) == g and len(pools[k])] for g in SHARE}
    taken = []
    for spacing in SPACINGS:
        at = {k: 0 for k in pools}
        live = {g: list(v) for g, v in by_group.items()}
        rr = {g: 0 for g in SHARE}
        while True:
            total = sum(counts.values()) + 1
            open_ = [g for g in SHARE if live[g] and counts[g] < MAX_SHARE[g] * total]
            if not open_:
                break
            g = max(open_, key=lambda x: SHARE[x] * total - counts[x])   # the group furthest behind its share
            ks = live[g]
            k = ks[rr[g] % len(ks)]                                          # round-robin over its setups
            rr[g] += 1
            arr, got = pools[k], None
            while at[k] < len(arr):
                i = int(arr[at[k]])
                at[k] += 1
                if not occupied[max(0, i - spacing + 1):i + spacing].any():
                    got = i
                    break
            if at[k] >= len(arr):
                ks.remove(k)
            if got is None:
                continue
            occupied[got] = True
            counts[g] += 1
            taken.append((got, k, at[k] - 1))
    return taken


def _load_bank() -> dict:
    z = np.load(BANK)
    return {k: z[k] for k in z.files}


def _bank_z(X, mean, std):
    return np.clip(np.nan_to_num((X - mean) / std), -5, 5).astype(np.float32)


def _bank_step(df, raw, meta_old, plan, symbol, point, prog):
    """Turn the creators' candidates into the bank: pick them under the spacing and mix rules, check each against its
    look-alikes, save, and write the markdown copy. Only new history is added when the old history is unchanged."""
    times_ns = df.index.asi8
    years = df.index.year.to_numpy()
    slices_now = {p["label"]: p["hash"] for p in plan}
    prev = None
    if (meta_old and meta_old.get("version") == BANK_VERSION and BANK.exists() and meta_old.get("symbol") == symbol
            and meta_old.get("point") == point and meta_old.get("columns") == raw["columns"]):
        old = list(meta_old.get("slices", {}))
        now = list(slices_now)
        if (old and now[:len(old) - 1] == old[:-1] and old[-1] in slices_now
                and all(slices_now[lb] == meta_old["slices"][lb] for lb in old[:-1])):
            prev = _load_bank()
    if prev is not None:
        mean, std, t_min = np.array(meta_old["mean"]), np.array(meta_old["std"]), meta_old["scan_end"]
        mode = "adding the new history"
    else:
        mean, std, t_min = raw["mean"], raw["std"], None
        mode = "sorting all the history"
    prog.set(f"picking questions ({mode})", 0.7)
    pools, details = _bank_pools(raw, years, t_min)
    if prev is None and not any(len(v) for k, v in pools.items() if k[0] != "wait"):
        raise SystemExit("No pro setups found. Download more history (Train tab) and try again.")
    occupied = np.zeros(len(df), bool)
    counts = {"trade": 0, "trap": 0, "wait": 0}
    if prev is not None and len(prev["t"]):
        occupied[np.searchsorted(times_ns, prev["t"])] = True
        for g, n_ in zip(("trade", "trap", "wait"), (int(((prev["kind"] < len(PRO_SETUPS)) & ~prev["trap"]).sum()),
                                                     int(prev["trap"].sum()), int((prev["kind"] == len(PRO_SETUPS)).sum()))):
            counts[g] = n_
    picks = _select_all(pools, occupied, counts)
    m = len(picks)
    new = {"t": np.zeros(m, np.int64), "kind": np.zeros(m, np.int16), "ans": np.zeros(m, np.int8),
           "trap": np.zeros(m, bool), "quality": np.zeros(m, np.float32), "mins": np.zeros(m, np.int16),
           "stop": np.zeros(m), "target": np.zeros(m), "entry": np.zeros(m)}
    for j, (pos_, key, at_) in enumerate(picks):
        d = details[key]
        new["t"][j] = d["t"][at_]
        new["kind"][j] = KINDS.index(key[0])
        new["ans"][j] = ACTIONS.index(key[1])
        new["trap"][j] = key[2]
        for f_ in ("quality", "mins", "stop", "target", "entry"):
            new[f_][j] = d[f_][at_]
    new["X"] = raw["X"][np.searchsorted(raw["pos"], np.searchsorted(times_ns, new["t"]))] if m else \
        np.zeros((0, len(raw["columns"])), np.float32)
    total = m + (len(prev["t"]) if prev is not None else 0)
    prog.set(f"checking {total:,} questions against their look-alikes", 0.8)
    print(f"  bank: {m:,} new questions ({mode}), {total:,} in total; checking look-alikes...", flush=True)
    nb = _Neighbours()
    if prev is not None and len(prev["t"]):
        nb.restore(_bank_z(prev["X"], mean, std), prev["ans"], prev)
    if m:
        nb.add(_bank_z(new["X"], mean, std), new["ans"])
    bank = {}
    for f_ in ("t", "kind", "ans", "trap", "quality", "mins", "stop", "target", "entry", "X"):
        bank[f_] = np.concatenate([prev[f_], new[f_]]) if prev is not None else new[f_]
    if nb.Z is not None:
        bank.update(nd=nb.nd, na=nb.na, same=nb.same, other=nb.other, older=nb.older_other, dupe=nb.dupe)
        share, contra, dupe = nb.result()
    else:
        share, contra, dupe = np.ones(0), np.zeros(0, bool), np.zeros(0, bool)
    bank.update(share=share.astype(np.float32), contra=contra, bad=contra | dupe | (share <= 0.2))
    BANK_DIR.mkdir(parents=True, exist_ok=True)
    tmp = BANK_DIR / "bank.tmp.npz"
    np.savez(tmp, **bank)
    tmp.replace(BANK)
    good = int((~bank["bad"]).sum())
    meta = {"version": BANK_VERSION, "symbol": symbol, "point": point, "columns": raw["columns"],
            "mean": np.round(mean, 6).tolist(), "std": np.round(std, 6).tolist(), "slices": slices_now,
            "scan_end": int(times_ns[max(0, len(df) - HORIZON - 2)]),
            "history": f"{df.index[0]:%Y-%m-%d} to {df.index[-1]:%Y-%m-%d}",
            "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "questions": int(len(bank["t"])),
            "good": good}
    _write(BANK_META, meta)
    prog.set("writing the markdown copy", 0.9)
    _write_bank_md(bank, meta)
    print(f"  bank: {good:,} usable questions of {len(bank['t']):,} ({meta['history']})", flush=True)
    return bank, meta


def _write_bank_md(bank, meta):
    """The bank as plain markdown: data/quiz_bank/README.md plus one table per year in data/quiz_bank/questions/."""
    BANK_MD.mkdir(parents=True, exist_ok=True)
    t = pd.to_datetime(bank["t"], utc=True)
    order = np.argsort(bank["t"], kind="stable")
    status = np.where(bank["contra"], "dropped: look-alikes have the other answer",
                      np.where(bank["dupe"], "dropped: near-copy",
                               np.where(bank["share"] <= 0.2, "dropped: closest look-alikes disagree", "kept")))
    diff = np.where(bank["share"] >= 0.8, "easy", np.where(bank["share"] >= 0.5, "medium", "hard"))
    rows_by_year: dict = {}
    for i in order:
        k = int(bank["kind"][i])
        kind = KINDS[k]
        trap = bool(bank["trap"][i])
        name = setup_name(kind, trap)
        if kind == "wait":
            result = "no clean trade either way"
        elif trap:
            result = f"stop hit in {int(bank['mins'][i])} min"
        else:
            result = f"target hit in {int(bank['mins'][i])} min"
        lv = "" if status[i] != "kept" else diff[i]
        prices = ("" if kind == "wait" else
                  f"{bank['entry'][i]:.2f} | {bank['stop'][i]:.2f} | {bank['target'][i]:.2f}")
        if kind == "wait":
            prices = " |  | "
        rows_by_year.setdefault(t[i].year, []).append(
            f"| {t[i]:%Y-%m-%d %H:%M} | {name} | {ACTIONS[int(bank['ans'][i])].upper()} | {prices} | {result} | "
            f"{status[i]} | {lv} |")
    head = ("| Time (UTC) | Setup | Right answer | Entry | Stop | Target | What happened | Status | Difficulty |\n"
            "|---|---|---|---|---|---|---|---|---|\n")
    for f_ in BANK_MD.glob("*.md"):
        if int(f_.stem) not in rows_by_year:
            f_.unlink()
    for year, rows in rows_by_year.items():
        (BANK_MD / f"{year}.md").write_text(f"# Quiz questions from {year}\n\n{len(rows):,} questions.\n\n" + head
                                            + "\n".join(rows) + "\n", encoding="utf-8")
    kept = ~bank["bad"]
    lines = []
    for k, kind in enumerate(KINDS):
        for trap in (False, True):
            sel = (bank["kind"] == k) & (bank["trap"] == trap)
            if sel.any():
                lines.append(f"| {setup_name(kind, trap)} | {int(sel.sum()):,} | {int((sel & kept).sum()):,} |")
    years_ = ", ".join(f"[{y}](questions/{y}.md)" for y in sorted(rows_by_year))
    (BANK_DIR / "README.md").write_text(
        f"# Quiz question bank\n\nUpdated {meta['updated']} from {meta['history']} of {meta['symbol']} M1 history.\n\n"
        f"**{meta['good']:,} usable questions** of {meta['questions']:,} found. One question creator keeps adding new "
        "ones in the background as new candles arrive; Build quiz picks from here.\n\n"
        "| Setup | Found | Usable |\n|---|---|---|\n" + "\n".join(lines) + f"\n\nBy year: {years_}\n", encoding="utf-8")


def _bank_update(symbol, point, workers, prog, should_yield=None, low=False):
    """Bring the bank up to date with the history. Returns (bank, meta, df), or None if it stepped aside for a build."""
    from .history import load_bars
    for f_ in (CACHE_DIR / "raw.npz", CACHE_DIR / "key.json"):           # the old single-file cache
        f_.unlink(missing_ok=True)
    prog.set("loading history", 0.01)
    df = load_bars(symbol)
    plan, arrays = _slice_jobs(df, point)
    meta = _load_json(BANK_META, None)
    if (meta and meta.get("version") == BANK_VERSION and BANK.exists() and meta.get("symbol") == symbol
            and meta.get("point") == point and meta.get("slices") == {p["label"]: p["hash"] for p in plan}):
        prog.cached = True
        return _load_bank(), meta, df
    raw = _find_all(df, point, workers, prog, plan, arrays, low=low, should_yield=should_yield)
    if raw is None or (should_yield and should_yield()):
        return None
    bank, meta = _bank_step(df, raw, meta, plan, symbol, point, prog)
    return bank, meta, df


def _bank_cycle(symbol, point, parent):
    """One background update, run in its own process so its memory is handed back when it ends. Exit code 0 = up to
    date, 3 = stepped aside for a build (or the app closed)."""
    _lower_priority()

    why = []

    def should_yield():
        if BUILD_REQUEST.exists():
            why[:] = ["paused: the Build quiz button is using all 10 question creators"]
            return True
        try:
            import psutil
            gone = not psutil.pid_exists(parent)
        except ImportError:
            gone = False
        if gone:
            why[:] = ["stopped: the app closed (it carries on next time)"]
        return gone

    prog = _Progress(1, path=BANK_STATUS, prefix="quiz_bank_w")
    try:
        with _BankLock():
            r = _bank_update(symbol, point, 1, prog, should_yield=should_yield, low=True)
    except SystemExit as e:                              # no history yet
        prog.set(f"waiting for history: {e}", 0.0, done=True)
        raise SystemExit(0)
    if r is None:
        prog.set(why[0] if why else "paused", prog.pct, done=True)
        raise SystemExit(3)
    _, meta, _ = r
    prog.extra = {"questions": meta["good"], "found": meta["questions"], "history": meta["history"],
                  "updated": meta["updated"]}
    prog.set(f"up to date: {meta['good']:,} questions ready", 1.0, done=True)


def bank_watch(symbol: str = "XAUUSD", point: float = 0.01, every: float = 60):
    """Keeps one question creator turning history into questions at all times: whenever the history changes (a data
    fetch or a history download) it updates the bank. Idle and nearly free in between."""
    import multiprocessing as mp
    _lower_priority()
    last, parent = None, os.getpid()
    print("question bank: one question creator keeps the bank up to date in the background", flush=True)
    while True:
        sig = _history_sig(symbol)
        if sig and sig != last and not BUILD_REQUEST.exists():
            p = mp.Process(target=_bank_cycle, args=(symbol, point, parent))
            p.start()
            p.join()
            if p.exitcode == 0:
                last = sig
                print(f"{datetime.now():%H:%M} bank up to date: {_load_json(BANK_STATUS, {}).get('stage', '')}", flush=True)
            elif p.exitcode == 3:
                print(f"{datetime.now():%H:%M} paused for a build; resuming after it", flush=True)
            else:
                print(f"{datetime.now():%H:%M} bank update failed (exit {p.exitcode}); retrying in {every:.0f}s",
                      flush=True)
        time.sleep(5 if BUILD_REQUEST.exists() or last != sig else every)


def _pick_from_bank(bank, n: int):
    """The quiz: n usable questions from the bank (all of them when n is 0), best examples first across years, in the
    65/15/20 mix while it lasts."""
    good = np.flatnonzero(~bank["bad"])
    if n <= 0 or n >= len(good):
        return good
    years = pd.to_datetime(bank["t"][good], utc=True).year.to_numpy()
    pools = {}
    for kind_code in np.unique(bank["kind"][good]):
        for trap in (False, True):
            sel = good[(bank["kind"][good] == kind_code) & (bank["trap"][good] == trap)]
            if len(sel):
                ysel = years[np.searchsorted(good, sel)]
                key = (KINDS[int(kind_code)], ACTIONS[int(bank["ans"][sel[0]])], trap)
                pools[key] = list(sel[_year_balanced(np.arange(len(sel)), bank["quality"][sel], ysel)])
    counts = {"trade": 0, "trap": 0, "wait": 0}
    live = {g: [k for k in pools if _group(k) == g] for g in SHARE}
    rr = {g: 0 for g in SHARE}
    at = {k: 0 for k in pools}
    out = []
    while len(out) < n:
        total = len(out) + 1
        open_ = [g for g in SHARE if live[g] and counts[g] < MAX_SHARE[g] * max(total, n)]
        if not open_:
            break
        g = max(open_, key=lambda x: SHARE[x] * total - counts[x])
        k = live[g][rr[g] % len(live[g])]
        rr[g] += 1
        out.append(pools[k][at[k]])
        at[k] += 1
        counts[g] += 1
        if at[k] >= len(pools[k]):
            live[g].remove(k)
    return np.array(out, dtype=np.int64)


def build(symbol: str = "XAUUSD", n_questions: int = 40, exam_share: float = 0.25, point: float = 0.01, seed: int = 7,
          workers: int = 0):
    """Build the quiz from the question bank (n_questions = 0 takes every usable question). All 10 question creators
    first finish whatever history the background creator hasn't reached yet."""
    n_questions = max(0, int(n_questions))
    if 0 < n_questions < 34:
        n_questions = 34
    workers = workers or default_workers()
    prog = _Progress(workers)
    t0 = time.time()
    BANK_DIR.mkdir(parents=True, exist_ok=True)
    BUILD_REQUEST.write_text(str(os.getpid()))           # the background creator steps aside
    try:
        with _BankLock(prog):
            bank, meta, df = _bank_update(symbol, point, workers, prog)
    finally:
        BUILD_REQUEST.unlink(missing_ok=True)
    t_find = time.time()
    rng = np.random.default_rng(seed)
    prog.set(f"picking {n_questions or 'all'} questions from the bank ({meta['good']:,} ready)", 0.92)
    chosen = _pick_from_bank(bank, n_questions)
    if len(chosen) < 10:
        raise SystemExit(f"Only found {len(chosen)} usable questions. Download more history and try again.")
    keep = chosen[rng.permutation(len(chosen))]
    times_ns = df.index.asi8
    pos = np.searchsorted(times_ns, bank["t"][keep])
    prog.set("saving the questions and their charts", 0.95)
    n = len(keep)
    n_exam = max(3, round(n * exam_share))
    if n - n_exam < 30 and n >= 33:
        n_exam = n - 30
    df_np = tuple(df[c].to_numpy() for c in ("open", "high", "low", "close"))
    ohlc = np.stack(df_np, axis=1).astype(np.float32)
    epoch = times_ns // 1_000_000_000
    bars = np.full((n, BEFORE + AFTER, 4), np.nan, dtype=np.float32)
    times = np.zeros((n, BEFORE + AFTER), dtype=np.int64)
    difficulty = np.where(bank["share"] >= 0.8, "easy", np.where(bank["share"] >= 0.5, "medium", "hard"))
    questions = []
    for qid, (b, i) in enumerate(zip(keep, pos)):
        lo, hi = int(i) - BEFORE + 1, min(len(df), int(i) + AFTER + 1)
        bars[qid, : hi - lo] = ohlc[lo:hi]
        times[qid, : hi - lo] = epoch[lo:hi]
        kind, trap = KINDS[int(bank["kind"][b])], bool(bank["trap"][b])
        trade = None if kind == "wait" else {"minutes": int(bank["mins"][b]), "stop": round(float(bank["stop"][b]), 2),
                                             "target": round(float(bank["target"][b]), 2),
                                             "entry": round(float(bank["entry"][b]), 2)}
        questions.append({"id": qid + 1, "time": str(df.index[i])[:16], "setup": kind,
                          "answer": ACTIONS[int(bank["ans"][b])], "trap": trap, "trade": trade,
                          "difficulty": str(difficulty[b]), "set": "exam" if qid >= n - n_exam else "practice"})
    DATA.mkdir(exist_ok=True)
    np.save(QX, bank["X"][keep])
    np.save(QBARS, bars)
    np.save(QTIMES, times)
    np.save(QC, chart_features_batch(bars[:, :BEFORE]))    # the chart inputs, ready for training
    quiz = {"symbol": symbol, "built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "features": meta["columns"], "norm": {"mean": meta["mean"], "std": meta["std"]}, "points": POINTS,
            "mastery": MASTERY, "practice": n - n_exam, "exam": n_exam, "questions": questions}
    _write(QUIZ, quiz)
    by = pd.Series([q["answer"] for q in questions]).value_counts().to_dict()
    lv = pd.Series([q["difficulty"] for q in questions]).value_counts().to_dict()
    traps = sum(q["trap"] for q in questions)
    if n_questions and n < n_questions:
        mix = ", ".join(f"{v / n:.0%} {k}" for k, v in by.items())
        prog.short = (f"Stopped at {n:,} of {n_questions:,}: that's every usable question in the {meta['history']} "
                      f"history (answers {mix}; {traps / n:.0%} traps). Download more years (Train tab) for more; the "
                      "background question creator adds new ones as new candles arrive.")
        print("  " + prog.short, flush=True)
    took = time.time() - t0
    print(f"saved {n:,} questions ({n - n_exam:,} practice, {n_exam:,} exam; answers {by}; {traps:,} traps; "
          f"difficulty {lv}; {len({q['setup'] for q in questions} - {'wait'})} pro setup types) in {took:.0f}s "
          f"(bank {t_find - t0:.0f}s{' already up to date' if prog.cached else ''}, picking and saving "
          f"{took - (t_find - t0):.0f}s)", flush=True)
    prog.set(f"done: {n:,} questions in {took:.0f}s", 1.0, done=True)
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


def chart_features_batch(bars) -> np.ndarray:
    """chart_features() for many questions at once: bars is (n, candles, 4) with at least 54 candles ending at the
    question candle. Rows with gaps fall back to the one-chart version."""
    A = np.asarray(bars, float)[:, -90:]
    out = np.zeros((len(A), CHART_DIM))
    ok = ~np.isnan(A).any((1, 2))
    if ok.any() and A.shape[1] >= CHART_BARS + 14:
        B = A[ok]
        atr_ = np.maximum(np.mean(B[:, -14:, 1] - B[:, -14:, 2], 1), 1e-6)
        ref = B[:, -1, 3]
        last = (B[:, -CHART_BARS:] - ref[:, None, None]) / atr_[:, None, None]
        outline = (B[:, ::-1, 3][:, ::5][:, :CHART_LONG][:, ::-1] - ref[:, None]) / atr_[:, None]
        if outline.shape[1] < CHART_LONG:
            outline = np.pad(outline, ((0, 0), (CHART_LONG - outline.shape[1], 0)))
        out[ok] = np.clip(np.hstack([last.transpose(0, 2, 1).reshape(len(B), -1), outline]) / 5, -3, 3)
    for r in np.flatnonzero(~ok):
        out[r] = chart_features(A[r])
    return out


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
    C = np.load(QC) if QC.exists() else None               # saved by the build; older quizzes compute it here
    if C is None or len(C) != len(Z):
        C = chart_features_batch(np.load(QBARS, mmap_mode="r")[:, :BEFORE])
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
SECTION = 5                       # a question's section: its 5 closest look-alikes (same setup group, same answer)
SWAP_RETRIES = True               # after a miss, retries are swapped for random section-mates (the last one is itself)
CORRECT = 0.25                    # after a miss it is shown the right answer and learns it at once (this strength)


def sections(qs, prac, X, ans, k: int = SECTION) -> np.ndarray:
    """Each practice question's section: its k closest practice look-alikes from the same setup group (same setup,
    same trap flag) with the same right answer. -1 fills the gaps in tiny groups. Exam questions are never used."""
    sib = np.full((len(qs), k), -1, dtype=np.int64)
    groups: dict = {}
    for i in prac:
        groups.setdefault((qs[i]["setup"], bool(qs[i].get("trap")), int(ans[i])), []).append(int(i))
    for g in groups.values():
        if len(g) < 2:
            continue
        g = np.array(g)
        Z = X[g].astype(np.float32)
        sq = (Z * Z).sum(1)
        kk = min(k, len(g) - 1)
        for s0 in range(0, len(g), 1024):
            rows = np.arange(s0, min(len(g), s0 + 1024))
            d2 = Z[rows] @ Z.T
            d2 *= -2
            d2 += sq[None, :]
            d2 += sq[rows, None]
            d2[np.arange(len(rows)), rows] = np.inf
            nn = np.argpartition(d2, kk - 1, axis=1)[:, :kk]
            order = np.take_along_axis(d2, nn, 1).argsort(1)
            sib[g[rows], :kk] = g[np.take_along_axis(nn, order, 1)]
    return sib


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
    sib = sections(qs, prac, X, ans) if SWAP_RETRIES else np.full((len(qs), SECTION), -1)
    n_sib = (sib >= 0).sum(1)
    swap = np.zeros(len(qs), bool)                       # missed: its retries are swapped for section-mates
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
            # a missed question's retries are answered on a random section-mate (a real look-alike with the same
            # answer), so it learns the pattern rather than one chart; its last retry is always itself
            src = bi.copy()
            sw = swap[bi] & (streak[bi] < MASTERY - 1) & (n_sib[bi] > 0)
            if sw.any():
                rows = np.flatnonzero(sw)
                src[rows] = sib[bi[rows], (rng.random(len(rows)) * n_sib[bi[rows]]).astype(int)]
            Xb = X[src]
            P, _ = pol.probs_batch(Xb)
            a = np.minimum((rng.random(len(bi))[:, None] > P.cumsum(1)).sum(1), 2)
            explore = rng.random(len(bi)) < np.minimum(EXPLORE_MAX, EXPLORE + 0.01 * misses[bi])  # stuck: try more
            a[explore] = rng.integers(3, size=int(explore.sum()))
            pts = PTS[a, ans[bi]]
            ok = a == ans[bi]
            boost = np.where((level >= 1) & (rnd - last_right[bi] >= STUCK_AFTER), 3.0, 1.0)
            adv = (pts - expect[bi]) / 10.0 * boost      # the reward: more points than usual -> more of that
            Xl, al, advl = [Xb], [a], [adv]
            if CORRECT and (~ok).any():                  # a miss: it is shown the right answer and learns it at once
                Xl.append(Xb[~ok])
                al.append(ans[bi][~ok])
                advl.append(CORRECT * boost[~ok])
            if refresh and len(fin):                     # silent refresher: keep finished answers from being overwritten
                r = fin[rng.integers(len(fin), size=max(1, int(len(bi) * REFRESH_SHARE)))]
                Xl.append(X[r])
                al.append(ans[r])
                advl.append(np.full(len(r), 1.0))
            pol.learn_batch(np.vstack(Xl), np.concatenate(al), np.concatenate(advl), lr)
            expect[bi] += 0.3 * (pts - expect[bi])
            points += int(pts.sum())
            round_points += int(pts.sum())
            n_asked += len(bi)
            asked[bi] += 1
            swap[bi[~ok]] = True
            recent.extend(ok.tolist())
            misses[bi] = np.where(ok, 0, misses[bi] + 1)
            streak[bi] = np.where(ok, streak[bi] + 1, 0)
            right[bi] += ok
            last_right[bi[ok]] = rnd
            # finished = right 5 times in a row AND its best answer is right (not 5 lucky guesses); the 5th answer is
            # always on the question itself (src == bi), never on a section-mate
            fin_now = ok & (streak[bi] >= MASTERY) & (P.argmax(1) == ans[bi]) & (src == bi)
            done_q[bi[fin_now]] = True
            swap[bi[fin_now]] = False
            if (~ok).any():
                wrong[bi[~ok], a[~ok]] += 1
                j = int(np.flatnonzero(~ok)[-1])
                mistake = {"id": int(src[j]) + 1, "action": ACTIONS[a[j]], "points": int(pts[j]),
                           "for": int(bi[j]) + 1 if src[j] != bi[j] else None,
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
    b.add_argument("--questions", type=int, default=40, help="0 = every usable question in the bank (no maximum)")
    b.add_argument("--point", type=float, default=0.01)
    b.add_argument("--seed", type=int, default=7)
    b.add_argument("--workers", type=int, default=0, help="question creators at once (0 = up to 10)")
    k = sub.add_parser("bank", help="keep the question bank up to date with one background question creator")
    k.add_argument("--symbol", default="XAUUSD")
    k.add_argument("--point", type=float, default=0.01)
    k.add_argument("--watch", action="store_true", help="keep running and update whenever the history changes")
    k.add_argument("--workers", type=int, default=1, help="question creators for a one-off update (default 1)")
    t = sub.add_parser("train")
    t.add_argument("--max-rounds", type=int, default=0, help="0 = loop until everything is finished or Stop")
    t.add_argument("--lr", type=float, default=0.01)
    t.add_argument("--resume", action="store_true", help="continue with the saved agent and progress")
    t.add_argument("--no-refresh", action="store_true", help="don't silently refresh finished questions")
    t.add_argument("--focus", default="", help="comma-separated question numbers to work on (finished ones are skipped)")
    a = ap.parse_args()
    if a.cmd == "build":
        build(a.symbol, a.questions, point=a.point, seed=a.seed, workers=a.workers)
    elif a.cmd == "bank":
        if a.watch:
            bank_watch(a.symbol, a.point)
        else:
            with _BankLock():
                _bank_update(a.symbol, a.point, a.workers, _Progress(a.workers, path=BANK_STATUS, prefix="quiz_bank_w"))
    else:
        focus = [int(v) for v in a.focus.replace(" ", "").split(",") if v] or None
        train(a.max_rounds, a.lr, resume=a.resume, focus=focus, refresh=not a.no_refresh)


if __name__ == "__main__":
    main()
