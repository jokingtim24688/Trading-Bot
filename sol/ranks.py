"""The crew's rank system: a trading-desk career ladder from Intern to Legend.

A rank needs points (trade points + the latest quiz grade), experience (closed trades it voted on) and, from Senior
Trader up, accuracy (share of its closed calls that earned points). Rank is what the agent wears (tie, pocket square,
pin) and how much its vote counts in the debate. Promotions happen as soon as every requirement is met; a demotion
only when it falls clearly below its current rank (10 % under the points, 2 points under the accuracy), so an agent
doesn't flicker between two ranks on one trade. Every change is logged (sol.db rank_log) and sent to Telegram.
"""
from . import store

RANKS = [
    {"id": 0, "name": "Intern", "short": "Intern", "pts": None, "trades": 0, "acc": None, "weight": 1.0,
     "perk": "learning the desk: its vote counts normally"},
    {"id": 1, "name": "Junior Trader", "short": "Junior", "pts": 25, "trades": 0, "acc": None, "weight": 1.1,
     "perk": "passed the quiz: its vote counts 1.1×"},
    {"id": 2, "name": "Trader", "short": "Trader", "pts": 75, "trades": 5, "acc": None, "weight": 1.2,
     "perk": "its vote counts 1.2×"},
    {"id": 3, "name": "Senior Trader", "short": "Senior", "pts": 150, "trades": 15, "acc": 0.55, "weight": 1.35,
     "perk": "its vote counts 1.35×"},
    {"id": 4, "name": "Portfolio Manager", "short": "Manager", "pts": 300, "trades": 30, "acc": 0.58, "weight": 1.5,
     "perk": "its vote counts 1.5×"},
    {"id": 5, "name": "Partner", "short": "Partner", "pts": 600, "trades": 60, "acc": 0.60, "weight": 1.7,
     "perk": "its vote counts 1.7×"},
    {"id": 6, "name": "Legend", "short": "Legend", "pts": 1200, "trades": 120, "acc": 0.62, "weight": 2.0,
     "perk": "its vote counts double"},
]
DEMOTE_PTS, DEMOTE_ACC = 0.9, 0.02


def _meets(r: dict, points: float, trades: int, acc: float | None, slack: bool = False) -> bool:
    need_pts = (r["pts"] or 0) * (DEMOTE_PTS if slack else 1)
    need_acc = (r["acc"] or 0) - (DEMOTE_ACC if slack else 0)
    return (r["pts"] is None or points >= need_pts) and trades >= r["trades"] and (
        r["acc"] is None or (acc is not None and acc >= need_acc))


def rank_for(points: float, trades: int, acc: float | None, current: int | None = None) -> int:
    """The rank these numbers earn. With `current`, keeps it unless it's clearly lost (hysteresis)."""
    earned = 0
    for r in RANKS:
        if _meets(r, points, trades, acc):
            earned = r["id"]
        else:
            break
    if current is not None and earned < current:
        keep = current
        while keep > earned and not _meets(RANKS[keep], points, trades, acc, slack=True):
            keep -= 1
        return keep
    return earned


def info(i: int) -> dict:
    r = RANKS[max(0, min(len(RANKS) - 1, int(i or 0)))]
    return {k: r[k] for k in ("id", "name", "short", "weight", "perk")}


def progress(i: int, points: float, trades: int, acc: float | None) -> dict | None:
    """What the next rank needs and how far along the agent is (None at the top)."""
    if i + 1 >= len(RANKS):
        return None
    r = RANKS[i + 1]
    need = []
    if r["pts"] is not None:
        need.append({"what": "points", "have": round(points, 1), "need": r["pts"],
                     "frac": max(0.0, min(1.0, points / r["pts"])) if r["pts"] else 1.0})
    if r["trades"]:
        need.append({"what": "trades", "have": trades, "need": r["trades"], "frac": min(1.0, trades / r["trades"])})
    if r["acc"] is not None:
        a = acc or 0.0
        need.append({"what": "accuracy", "have": round(a, 3), "need": r["acc"], "frac": min(1.0, a / r["acc"])})
    return {**info(r["id"]), "needs": need, "frac": round(min(x["frac"] for x in need), 3) if need else 1.0}


def stats_for(model: str, bots: dict | None = None) -> tuple[float, int, float | None]:
    bots = bots if bots is not None else store.bots()
    b = bots.get(model, {})
    vs = store.vote_stats(model)
    return (b.get("score") or 0) + (b.get("quiz") or 0), int(vs.get("right", 0) + vs.get("wrong", 0)), vs.get("accuracy")


def update(models=None, say=None) -> list[dict]:
    """Re-rank these models (all known ones by default); log and announce every change. Returns the changes."""
    bots = store.bots()
    changes = []
    for m in (models or list(bots)):
        points, trades, acc = stats_for(m, bots)
        cur = int((bots.get(m) or {}).get("rank") or 0)
        new = rank_for(points, trades, acc, current=cur)
        if new != cur:
            store.set_rank(m, new, cur, points)
            ch = {"model": m, "from": info(cur), "to": info(new), "up": new > cur}
            changes.append(ch)
            if say:
                say(ch)
    return changes


def weights(bots: dict | None = None) -> dict:
    """Debate weight per model, from its rank."""
    bots = bots if bots is not None else store.bots()
    return {m: RANKS[int(b.get("rank") or 0)]["weight"] for m, b in bots.items()}
