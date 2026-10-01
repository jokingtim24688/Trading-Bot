"""Trenching: data, question bank and quiz training for the Solana bot.

What "trenching" is (researched 2026-09-30): Solana slang for digging through brand-new Pump.fun launches (and other
launchpads) to buy before a coin is widely noticed. Terminals (Axiom Pulse, GMGN, Trojan, Terminal) show three stages:
new launches, close to migrating off the bonding curve, and migrated to PumpSwap/Raydium. Most launches die within
hours; insiders, snipers and bundlers get the cheapest coins, so late buyers become exit liquidity. Traders who last
pick one lane (flip early coins, follow proven wallets, or back conviction plays), take partial profit fast (e.g. half
at 2x), check holder spread and locked liquidity before buying, and journal every trade.

Data:
- a STARTER SET is preloaded (made on first use from those facts, flagged synthetic) so the quiz can train at once;
- the DOWNLOADER then pulls real 1-minute candles of fresh PumpSwap pools from GeckoTerminal and labels every
  window: good buy = +25 % before -12 % within 30 minutes. Real samples replace the starter set as they arrive.
Questions live on disk (data/quiz_bank/trenching/questions.jsonl, read line by line), never all in RAM.
At least `quiz_min_creators` (2) question creators run while the app is open.
"""
import hashlib
import json
import math
import random
import threading
import time
from datetime import datetime, timezone

import numpy as np

from app import settings

from . import feeds, model, store
from .features import FEATURES, LABEL_MIN, label_path, vector

MAX_QUESTIONS = 200_000
LESSONS = [
    "Most fresh launches die within hours: the default answer is PASS.",
    "Buy pressure matters: far more buys than sells in the last 5 minutes is the first sign of a runner.",
    "Thin liquidity means your own sell moves the price: under ~$5k it's a trap.",
    "If the top 10 wallets own more than ~30 %, one of them can dump on you.",
    "A coin already up hundreds of percent in 5 minutes usually retraces: you're probably late.",
    "Very old coins with no volume rarely wake up; very new ones are where snipers feed.",
    "Take profit fast: +25 % in half an hour is a win in the trenches.",
]


def base():
    d = settings.DATA / "quiz_bank" / "trenching"
    d.mkdir(parents=True, exist_ok=True)
    return d


def samples_path():
    return base() / "samples.jsonl"


def questions_path():
    return base() / "questions.jsonl"


state = {"download": {"running": False, "progress": 0.0, "stage": "", "pools": 0, "samples": 0, "error": ""},
         "train": {"running": False, "progress": 0.0, "stage": "", "error": "", "last": None, "last_real_at_train": 0},
         "creators": {"running": 0, "wanted": 2, "made": 0}}
_file_lock = threading.Lock()


# ---------- samples on disk ----------
def _append(path, rows):
    if not rows:
        return
    with _file_lock, open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")


def iter_rows(path):
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    yield json.loads(line)
                except ValueError:
                    continue
    except OSError:
        return


def count_lines(path) -> int:
    try:
        with open(path, "rb") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def _sid(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


def starter_set(n=6000, seed=11) -> int:
    """The preloaded starter set: token moments drawn from what trenchers report (most coins die, pressure and
    liquidity separate runners from rugs). Written once; flagged synthetic so the app can say so."""
    if any(r.get("source") == "starter" for r in _head(samples_path(), 5)):
        return 0
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        age = rng.choice([rng.uniform(1, 30), rng.uniform(30, 240), rng.uniform(240, 1440)])
        liq = 10 ** rng.uniform(3.0, 5.6)
        buys = int(rng.expovariate(1 / 60))
        ratio = min(0.97, max(0.03, rng.gauss(0.52, 0.14)))
        sells = int(buys * (1 - ratio) / ratio) if buys else int(rng.expovariate(1 / 20))
        vol = (buys + sells) * rng.uniform(20, 180)
        chg = rng.gauss(0, 18) + (ratio - 0.5) * 60
        top10 = min(95, max(8, rng.gauss(28, 12)))
        s = {"liq_usd": liq, "age_min": age, "buys_5m": buys, "sells_5m": sells, "vol_5m": vol, "chg_5m": chg,
             "top10_pct": top10}
        z = (-2.6 + 5.0 * (ratio - 0.5) + 0.9 * (math.log10(liq) - 4) - 0.035 * max(0, top10 - 30)
             + 0.35 * math.log10(1 + buys) - 0.012 * max(0, chg - 60) - 0.4 * (age > 600) + rng.gauss(0, 0.8))
        y = int(rng.random() < 1 / (1 + math.exp(-z)))
        rows.append({"id": _sid("starter", seed, i), "source": "starter", "symbol": f"DEMO{i % 500}", "snap": s,
                     "label": y, "t": time.time()})
    _append(samples_path(), rows)
    return len(rows)


def _head(path, n):
    out = []
    for r in iter_rows(path):
        out.append(r)
        if len(out) >= n:
            break
    return out


def _windows(snap: dict, cs: list[list[float]], step=3) -> list[dict]:
    """Label every few minutes of a pool's candle history (features only from candles up to that minute)."""
    rows = []
    if len(cs) < LABEL_MIN + 6:
        return rows
    t_created = None
    if snap.get("age_min") is not None:
        t_created = time.time() - snap["age_min"] * 60
    ratio_now = (snap["buys_5m"] / (snap["buys_5m"] + snap["sells_5m"])) if snap["buys_5m"] + snap["sells_5m"] else 0.5
    for i in range(5, len(cs) - LABEL_MIN, step):
        t, o, h, lo, c, v = cs[i]
        past = cs[i - 5:i + 1]
        vol5 = sum(r[5] for r in past)
        chg5 = (c / past[0][1] - 1) * 100 if past[0][1] else 0
        ups = sum(1 for r in past if r[4] >= r[1])
        est_ratio = 0.5 * ratio_now + 0.5 * (ups / len(past))           # buy/sell split per candle isn't public
        trades = max(1, int(vol5 / 60))
        s = {"liq_usd": snap["liq_usd"] * (c / cs[-1][4]) if cs[-1][4] else snap["liq_usd"],
             "age_min": (t - t_created) / 60 if t_created else None, "buys_5m": int(trades * est_ratio),
             "sells_5m": int(trades * (1 - est_ratio)), "vol_5m": vol5, "chg_5m": chg5, "top10_pct": snap.get("top10_pct")}
        y = label_path(c, [r[2] for r in cs[i + 1:]], [r[3] for r in cs[i + 1:]])
        if y is not None:
            rows.append({"id": _sid(snap["pool"], int(t)), "source": "geckoterminal", "symbol": snap["symbol"],
                         "mint": snap["mint"], "snap": s, "label": y, "t": t,
                         "candles": [round(r[4], 12) for r in cs[max(0, i - 29):i + 1]]})
    return rows


def download(pools=None) -> dict:
    """Real trenching data: fresh PumpSwap + new Solana pools, 1-minute candles, labelled windows. Looks at four
    lists so one quiet source (e.g. PumpSwap having a slow hour) doesn't starve the download: brand-new pools
    across the whole network, PumpSwap and Raydium trending (where migrated runners live), and the network's
    overall trending list as a catch-all."""
    pools = int(pools or settings.load().get("trench_download_pools", 40))
    d = state["download"]
    if d["running"]:
        raise RuntimeError("The trenching download is already running.")
    d.update(running=True, progress=0.0, stage="finding fresh pools", pools=0, samples=0, error="")
    try:
        found = (feeds.new_pools(3) + feeds.trending_pools(2, dex="pumpswap") + feeds.trending_pools(2, dex="raydium")
                 + feeds.trending_pools(1))
        seen, todo = set(), []
        for s in found:
            if s["pool"] and s["pool"] not in seen and s["liq_usd"] > 1000:
                seen.add(s["pool"]); todo.append(s)
        todo = todo[:pools]
        if not todo:
            raise RuntimeError("GeckoTerminal didn't answer (offline or blocked). The starter set is still there.")
        have = {r["id"] for r in iter_rows(samples_path()) if r.get("source") != "starter"}
        for k, s in enumerate(todo):
            d["stage"] = f"candles for {s['symbol']} ({k + 1}/{len(todo)})"
            rows = [r for r in _windows(s, feeds.candles(s["pool"], 1000)) if r["id"] not in have]
            _append(samples_path(), rows)
            d["pools"] += 1
            d["samples"] += len(rows)
            d["progress"] = (k + 1) / len(todo)
        d["stage"] = f"done: {d['samples']} new labelled moments from {d['pools']} pools"
        return dict(d)
    except Exception as e:
        d.update(error=str(e), stage="failed")
        raise
    finally:
        d["running"] = False


_info_cache = {"key": None, "val": None}


def _size(path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def dataset_info() -> dict:
    """Counts for the app (polled every 2 s): recounted only when one of the files changed size."""
    key = (str(base()), _size(samples_path()), _size(questions_path()))
    if _info_cache["key"] == key:
        return dict(_info_cache["val"])
    real = starter = good = 0
    for r in iter_rows(samples_path()):
        if r.get("source") == "starter":
            starter += 1
        else:
            real += 1
        good += r.get("label", 0)
    val = {"samples": real + starter, "real": real, "starter": starter, "good_share": round(good / max(1, real + starter), 3),
           "questions": count_lines(questions_path())}
    _info_cache.update(key=key, val=val)
    return dict(val)


# ---------- question creators ----------
def _question(r: dict) -> dict:
    s = r["snap"]
    right = "BUY" if r["label"] else "PASS"
    hints = []
    b, se = s.get("buys_5m") or 0, s.get("sells_5m") or 0
    if b + se and b / (b + se) > 0.62:
        hints.append("strong buy pressure")
    if (s.get("liq_usd") or 0) < 5000:
        hints.append("thin liquidity")
    if (s.get("top10_pct") or 0) > 30:
        hints.append("top holders too heavy")
    if (s.get("chg_5m") or 0) > 60:
        hints.append("already pumped")
    lesson = LESSONS[0] if right == "PASS" and not hints else random.choice(LESSONS[1:])
    return {"id": r["id"], "mode": "trenching", "symbol": r.get("symbol"), "source": r.get("source"),
            "x": [round(float(v), 5) for v in vector(s)], "answer": right, "hints": hints, "lesson": lesson,
            "candles": r.get("candles"), "t": r.get("t")}


class Creators:
    """Question creators: creator k of n turns samples k, k+n, k+2n... into questions in the file. Each keeps its own
    position (data/quiz_bank/trenching/creator_k.pos), so nothing is loaded into memory and nothing is done twice.
    `ensure()` keeps at least N alive (a stopped one is restarted in its own slot)."""

    def __init__(self):
        self.threads: dict[int, threading.Thread] = {}
        self.stop = threading.Event()
        self.n = 2

    def _pos_file(self, k):
        return base() / f"creator_{k}.pos"

    def _run(self, k: int, n: int):
        while not self.stop.is_set() and self.n == n:
            made = 0
            try:
                made = self._pass(k, n)
            except Exception:                           # noqa: BLE001 - a creator never dies on bad data
                pass
            self.stop.wait(5 if made else 30)

    def _pass(self, k, n) -> int:
        if count_lines(questions_path()) >= MAX_QUESTIONS:
            return 0
        try:
            saved = json.loads(self._pos_file(k).read_text())
            pos = saved["pos"] if saved.get("n") == n else 0
        except (OSError, ValueError, KeyError):
            pos = 0
        new, made, last = [], 0, pos - 1
        for i, r in enumerate(iter_rows(samples_path())):
            if self.stop.is_set():
                break
            if i < pos:
                continue
            last = i
            if i % n != k:
                continue
            new.append(_question(r))
            if len(new) >= 500:
                _append(questions_path(), new)
                made += len(new)
                state["creators"]["made"] += len(new)
                new = []
        _append(questions_path(), new)
        made += len(new)
        state["creators"]["made"] += len(new)
        self._pos_file(k).write_text(json.dumps({"n": n, "pos": last + 1}))
        return made

    def status(self) -> dict:
        state["creators"]["running"] = sum(1 for t in self.threads.values() if t.is_alive())
        return dict(state["creators"])

    def ensure(self, n: int | None = None):
        n = max(2, int(n or settings.load().get("quiz_min_creators", 2)))
        if n != self.n:                                 # a new count: old creators finish their pass and stop
            self.n = n
            self.threads = {}
        state["creators"]["wanted"] = n
        for k in range(n):
            t = self.threads.get(k)
            if t is None or not t.is_alive():
                t = threading.Thread(target=self._run, args=(k, n), name=f"trench-creator-{k}", daemon=True)
                t.start()
                self.threads[k] = t
        return self.status()


creators = Creators()


def _maybe_retrain(auto_gap: int):
    """Called after a download: if enough new real data has come in since the last training, train again by
    itself - so the crew's grades actually move while the app sits open, not just when you press the button."""
    tr = state["train"]
    if tr["running"] or model.state["training"]:
        return
    real = dataset_info()["real"]
    if real < 60 or real - tr.get("last_real_at_train", 0) < max(50, auto_gap):
        return
    try:
        train_quiz(auto=True)
    except Exception:                                   # noqa: BLE001 - the next download tries again later
        pass


def keep_alive():
    """App start: starter set, two creators, a background download; from then on a loop every 30 s that keeps the
    creators alive, re-downloads real data every `trench_download_min` minutes (first run at once) and, when
    `trench_auto_retrain` is on, retrains by itself once `trench_auto_retrain_gap` new real moments have come in."""
    def boot():
        try:
            starter_set()
        except OSError:
            pass
        creators.ensure()
        next_dl = 0.0
        while True:
            creators.ensure()
            s = settings.load()
            if time.time() >= next_dl:
                try:
                    download(s.get("trench_download_pools", 40))
                except Exception:                        # noqa: BLE001 - offline: the starter set trains meanwhile
                    pass
                if s.get("trench_auto_retrain", True):
                    _maybe_retrain(int(s.get("trench_auto_retrain_gap", 400)))
                next_dl = time.time() + max(5.0, float(s.get("trench_download_min", 20))) * 60
            time.sleep(30)
    threading.Thread(target=boot, name="trench-boot", daemon=True).start()


# ---------- quiz training ----------
def load_questions(limit=MAX_QUESTIONS, real_only=False):
    X, y, src = [], [], []
    for q in iter_rows(questions_path()):
        if real_only and q.get("source") == "starter":
            continue
        X.append(q["x"]); y.append(1 if q["answer"] == "BUY" else 0); src.append(q.get("source"))
        if len(X) >= limit:
            break
    return np.array(X, dtype=np.float32), np.array(y, dtype=int), src


def train_quiz(auto: bool = False) -> dict:
    """The crew takes the quiz: split into models, each learns from every question, they're graded on questions
    they never saw (points per right answer), then merged back into one bot. Every run is logged (training_log)
    so the Quiz tab can chart the grade actually moving as more real data comes in."""
    tr = state["train"]
    if tr["running"]:
        raise RuntimeError("Quiz training is already running.")
    tr.update(running=True, progress=0.0, stage="reading questions", error="")
    try:
        X, y, src = load_questions()
        real = sum(1 for s in src if s != "starter")
        if real >= 2000:                                # enough real data: leave the starter set out
            X, y, src = load_questions(real_only=True)
            real = sum(1 for s in src if s != "starter")
        tr["stage"] = f"{len(y)} questions: splitting the bot and training each model"
        meta = model.train(X, y, synthetic_share=1 - real / max(1, len(src)))
        for m, auc in (meta["metrics"].get("members") or {}).items():
            if auc is not None:                         # points: how far above guessing each model answered
                store.add_score(m, round((auc - 0.5) * 200, 1), quiz=True)
        from . import engine, ranks                     # the quiz grade can promote an intern
        ranks.update(list((meta["metrics"].get("members") or {})), say=engine.announce_rank)
        store.add_training(meta, real, auto=auto)
        tr.update(progress=1.0, stage="merged into one bot", last=meta, last_real_at_train=dataset_info()["real"])
        return meta
    except Exception as e:
        tr.update(error=str(e), stage="failed")
        raise
    finally:
        tr["running"] = False


def sample_question(i: int | None = None) -> dict | None:
    n = count_lines(questions_path())
    if not n:
        return None
    i = random.randrange(n) if i is None else i % n
    for k, q in enumerate(iter_rows(questions_path())):
        if k == i:
            q["features"] = dict(zip(FEATURES, q["x"]))
            if model.loaded():
                q["crew"] = model.predict(np.array(q["x"]))
            return q
    return None
