"""The models argue about a trade — and must finish at once.

No loops that can run on: at most MAX_ROUNDS rounds of DeGroot averaging (each model moves toward the others, more
toward the ones with a better track record), then a decision is forced. Pure arithmetic on a handful of numbers, so a
whole debate takes microseconds; `ms` in the result proves it. Prices can't move while the bots talk.
"""
import time

MAX_ROUNDS = 3          # hard cap after the opening statements: the debate always ends here, agreed or not
AGREE_SPREAD = 0.06     # closer than this = agreed early
PULL = 0.5              # how far each model moves toward the group per round

NAMES = {"xgb": "XGBoost", "lgbm": "LightGBM", "rf": "Random Forest", "cat": "CatBoost", "bot": "Merged bot"}


def _stance(p, need, floor):
    return "BUY" if p >= need else ("PASS" if p < floor else "UNSURE")


def _says(m, p, stance, moved, rnd):
    if rnd == 0:
        return {"BUY": f"I'm {p:.0%} on this. Buy.", "PASS": f"Only {p:.0%}. I'd pass.",
                "UNSURE": f"{p:.0%}. Not convinced either way."}[stance]
    if abs(moved) < 0.005:
        return f"Holding at {p:.0%}."
    return f"{'Up' if moved > 0 else 'Down'} to {p:.0%} after hearing the others."


def run(probs: dict, scores: dict | None = None, need=0.78, floor=0.65, size_sol=0.1, tp_pct=30.0, trail_pct=10.0,
        weights: dict | None = None):
    """probs: {model: p} (the merged bot's own 'bot' answer is kept out of the argument and reported beside it).
    weights: {model: vote weight} from the rank system (sol/ranks.py); without them, scores {model: points} give the
    proven models more pull. Returns rounds, consensus and the compromise trade."""
    t0 = time.perf_counter()
    cur = {m: float(p) for m, p in probs.items() if m != "bot"}
    if not cur:
        return {"rounds": [], "consensus": {"verdict": "PASS", "score": 0, "spread": 0, "agreed": False, "rounds": 0,
                                            "note": "no trained models"}, "ms": 0.0}
    if weights:
        trust = {m: max(0.5, float(weights.get(m, 1.0))) for m in cur}       # the rank's weight, 1.0 .. 2.0
    else:
        scores = scores or {}
        lo = min(scores.get(m, 0) for m in cur)
        trust = {m: 1.0 + max(0.0, scores.get(m, 0) - lo) / 100 for m in cur}    # 1.0 .. ~2.0
    rounds = [{"n": 0, "stances": [{"model": m, "prob": round(p, 4), "stance": _stance(p, need, floor),
                                    "says": _says(m, p, _stance(p, need, floor), 0, 0), "moved": 0.0}
                                   for m, p in cur.items()]}]
    for n in range(1, MAX_ROUNDS + 1):
        if max(cur.values()) - min(cur.values()) < AGREE_SPREAD:
            break
        total = sum(trust.values())
        nxt = {}
        for m, p in cur.items():
            others = sum(trust[o] * cur[o] for o in cur if o != m) / (total - trust[m]) if len(cur) > 1 else p
            nxt[m] = p + PULL * (others - p) / trust[m]
        rounds.append({"n": n, "stances": [{"model": m, "prob": round(nxt[m], 4), "stance": _stance(nxt[m], need, floor),
                                            "says": _says(m, nxt[m], _stance(nxt[m], need, floor), nxt[m] - cur[m], n),
                                            "moved": round(nxt[m] - cur[m], 4)} for m in cur]})
        cur = nxt
    total = sum(trust.values())
    score = sum(trust[m] * cur[m] for m in cur) / total
    spread = max(cur.values()) - min(cur.values())
    agreed = spread < AGREE_SPREAD
    buy = score >= need and min(cur.values()) >= floor
    comp = None
    if buy:
        # the compromise: the more they still disagree and the closer to the line, the smaller and tighter the trade
        edge = min(1.0, (score - need) / max(1e-6, 1 - need))
        pct = max(0.25, min(1.0, (0.5 + 0.5 * edge) * (1 - spread)))
        comp = {"size_sol": round(size_sol * pct, 4), "size_pct": round(pct * 100), "tp_pct": round(tp_pct * (0.8 + 0.4 * edge), 1),
                "trail_pct": round(trail_pct * (1.2 - 0.4 * edge) if spread > AGREE_SPREAD / 2 else trail_pct, 1),
                "note": "full size, all agree" if pct >= 0.99 else f"{pct:.0%} size: {'still split' if not agreed else 'close to the line'}"}
    ms = (time.perf_counter() - t0) * 1000
    return {"rounds": rounds, "bot": probs.get("bot"), "ms": round(ms, 3), "weights": {m: round(w, 2) for m, w in trust.items()},
            "consensus": {"score": round(score, 4), "spread": round(spread, 4), "agreed": agreed, "rounds": len(rounds) - 1,
                          "verdict": "BUY" if buy else "PASS", "compromise": comp, "need": need, "floor": floor}}
