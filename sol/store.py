"""SQLite for the Solana bot: tokens seen, positions/trades, model scores, labelled samples. data/sol.db."""
import json
import sqlite3
import time

from app import settings


def path():
    return settings.DATA / "sol.db"


def conn():
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p, timeout=10)
    c.row_factory = sqlite3.Row
    c.executescript("""
    CREATE TABLE IF NOT EXISTS seen (mint TEXT PRIMARY KEY, symbol TEXT, name TEXT, t REAL, liq_usd REAL, age_min REAL,
        buys5 INTEGER, sells5 INTEGER, passed INTEGER, why TEXT, prob REAL, verdict TEXT, snap TEXT);
    CREATE INDEX IF NOT EXISTS ix_seen_t ON seen(t);
    CREATE TABLE IF NOT EXISTS positions (id INTEGER PRIMARY KEY, mint TEXT, symbol TEXT, mode TEXT, size_sol REAL,
        entry_px REAL, peak_px REAL, last_px REAL, tp_pct REAL, trail_pct REAL, timeout_min REAL, opened REAL,
        status TEXT, exit_px REAL, closed REAL, reason TEXT, pnl_sol REAL, pnl_pct REAL, debate TEXT, tx TEXT);
    CREATE INDEX IF NOT EXISTS ix_pos_status ON positions(status);
    CREATE TABLE IF NOT EXISTS bots (model TEXT PRIMARY KEY, score REAL, last_win REAL, quiz REAL);
    CREATE TABLE IF NOT EXISTS debates (mint TEXT PRIMARY KEY, t REAL, body TEXT);
    CREATE TABLE IF NOT EXISTS votes (id INTEGER PRIMARY KEY, model TEXT, mint TEXT, symbol TEXT, t REAL,
        open_prob REAL, final_prob REAL, stance TEXT, verdict TEXT, position_id INTEGER, pnl_pct REAL, points REAL,
        closed REAL);
    CREATE INDEX IF NOT EXISTS ix_votes_model ON votes(model, t);
    CREATE INDEX IF NOT EXISTS ix_votes_pos ON votes(position_id);
    CREATE TABLE IF NOT EXISTS rank_log (id INTEGER PRIMARY KEY, model TEXT, t REAL, rank INTEGER, prev INTEGER,
        points REAL);
    CREATE TABLE IF NOT EXISTS tweets (id INTEGER PRIMARY KEY, mint TEXT, symbol TEXT, model TEXT, beat TEXT,
        tweet_id TEXT, author TEXT, followers INTEGER, likes INTEGER, url TEXT, text TEXT, t REAL, tweet_t REAL,
        heat REAL, voices INTEGER, status TEXT, why TEXT, verdict TEXT, also TEXT);
    CREATE INDEX IF NOT EXISTS ix_tweets_t ON tweets(t);
    CREATE INDEX IF NOT EXISTS ix_tweets_model ON tweets(model, t);
    CREATE INDEX IF NOT EXISTS ix_tweets_mint ON tweets(mint, t);
    """)
    have = {r[1] for r in c.execute("PRAGMA table_info(bots)")}
    for col, typ in (("rank", "INTEGER DEFAULT 0"), ("rank_t", "REAL DEFAULT 0")):
        if col not in have:                          # databases made before the rank system
            c.execute(f"ALTER TABLE bots ADD COLUMN {col} {typ}")
    return c


def now():
    return time.time()


def jdump(v):
    return json.dumps(v, separators=(",", ":"), default=float)


def jload(v, default=None):
    try:
        return json.loads(v) if v else default
    except ValueError:
        return default


# ---------- seen tokens (the feed) ----------
def record_seen(snap: dict, gate: dict, prob=None, verdict=None):
    with conn() as c:
        c.execute("""INSERT OR REPLACE INTO seen VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (snap["mint"], snap.get("symbol"), snap.get("name"), now(), snap.get("liq_usd"), snap.get("age_min"),
                   snap.get("buys_5m"), snap.get("sells_5m"), int(gate["passed"]), "; ".join(gate["why"]), prob, verdict,
                   jdump(snap)))


def feed(limit=60):
    with conn() as c:
        rows = c.execute("SELECT * FROM seen ORDER BY t DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d.pop("snap", None)
        d["passed"] = bool(d["passed"])
        d["why"] = [w for w in (d["why"] or "").split("; ") if w]
        out.append(d)
    return out


def seen_before(mint: str) -> bool:
    with conn() as c:
        return c.execute("SELECT 1 FROM seen WHERE mint=?", (mint,)).fetchone() is not None


def counts():
    with conn() as c:
        r = c.execute("SELECT COUNT(*), COALESCE(SUM(passed),0) FROM seen").fetchone()
    return {"scanned": r[0], "passed": r[1], "blocked": r[0] - r[1]}


# ---------- positions ----------
def open_position(mint, symbol, mode, size_sol, px, tp_pct, trail_pct, timeout_min, debate, tx=None) -> int:
    with conn() as c:
        return c.execute("""INSERT INTO positions (mint, symbol, mode, size_sol, entry_px, peak_px, last_px, tp_pct,
                            trail_pct, timeout_min, opened, status, debate, tx) VALUES (?,?,?,?,?,?,?,?,?,?,?, 'open', ?,?)""",
                         (mint, symbol, mode, size_sol, px, px, px, tp_pct, trail_pct, timeout_min, now(), jdump(debate),
                          tx)).lastrowid


def update_price(pid, px):
    with conn() as c:
        c.execute("UPDATE positions SET last_px=?, peak_px=MAX(peak_px, ?) WHERE id=?", (px, px, pid))


def close_position(pid, px, reason, tx=None) -> dict:
    with conn() as c:
        p = c.execute("SELECT * FROM positions WHERE id=?", (pid,)).fetchone()
        if not p or p["status"] != "open":
            return dict(p) if p else {}
        pct = (px / p["entry_px"] - 1) * 100 if p["entry_px"] else 0.0
        pnl = p["size_sol"] * pct / 100
        c.execute("""UPDATE positions SET status='closed', exit_px=?, closed=?, reason=?, pnl_sol=?, pnl_pct=?, last_px=?,
                     tx=COALESCE(?, tx) WHERE id=?""", (px, now(), reason, pnl, pct, px, tx, pid))
        return dict(c.execute("SELECT * FROM positions WHERE id=?", (pid,)).fetchone())


def positions(status="open", limit=200):
    with conn() as c:
        rows = c.execute("SELECT * FROM positions WHERE status=? ORDER BY id DESC LIMIT ?", (status, limit)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["debate"] = jload(d["debate"], {})
        if status == "open" and d["entry_px"]:
            d["pnl_pct"] = (d["last_px"] / d["entry_px"] - 1) * 100
            d["pnl_sol"] = d["size_sol"] * d["pnl_pct"] / 100
            d["age_min"] = (now() - d["opened"]) / 60
        out.append(d)
    return out


def get_position(pid):
    with conn() as c:
        r = c.execute("SELECT * FROM positions WHERE id=?", (pid,)).fetchone()
    return dict(r) if r else None


def realized(mode=None):
    q, a = "SELECT pnl_sol FROM positions WHERE status='closed'", []
    if mode:
        q += " AND mode=?"; a.append(mode)
    with conn() as c:
        vals = [r[0] or 0.0 for r in c.execute(q, a)]
    return {"prof": sum(v for v in vals if v > 0), "loss": sum(v for v in vals if v < 0), "n": len(vals),
            "wins": sum(1 for v in vals if v > 0)}


def pnl_curve(mode=None):
    q, a = "SELECT closed, pnl_sol FROM positions WHERE status='closed'", []
    if mode:
        q += " AND mode=?"; a.append(mode)
    with conn() as c:
        rows = c.execute(q + " ORDER BY closed", a).fetchall()
    cum, pts = 0.0, []
    for t, v in rows:
        cum += v or 0.0
        pts.append({"t": t, "cum_sol": round(cum, 6)})
    return pts


# ---------- model scores ----------
def bots():
    with conn() as c:
        return {r["model"]: dict(r) for r in c.execute("SELECT * FROM bots")}


def _ensure_bot(c, model):
    c.execute("INSERT OR IGNORE INTO bots (model, score, last_win, quiz, rank, rank_t) VALUES (?,0,0,0,0,0)", (model,))


def add_score(model, pts, win=False, quiz=False):
    """Trade points add up. Quiz points are the latest grade, not a running total (training again mustn't count
    twice)."""
    with conn() as c:
        _ensure_bot(c, model)
        if quiz:
            c.execute("UPDATE bots SET quiz=? WHERE model=?", (pts, model))
        else:
            c.execute("UPDATE bots SET score=score+?, last_win=CASE WHEN ? THEN ? ELSE last_win END WHERE model=?",
                      (pts, int(win), now(), model))


# ---------- debates ----------
def save_debate(mint, body):
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO debates VALUES (?,?,?)", (mint, now(), jdump(body)))
        c.execute("DELETE FROM debates WHERE t < ?", (now() - 86400,))


def get_debate(mint):
    with conn() as c:
        r = c.execute("SELECT body FROM debates WHERE mint=?", (mint,)).fetchone()
    return jload(r[0]) if r else None


# ---------- each model's votes (its profile: confidence, what it did, how it turned out) ----------
def record_votes(mint, symbol, rounds, verdict):
    """One row per model for a debate: its opening and final confidence, final stance and the crew's verdict."""
    if not rounds:
        return
    first = {x["model"]: x for x in rounds[0]["stances"]}
    with conn() as c:
        for x in rounds[-1]["stances"]:
            c.execute("""INSERT INTO votes (model, mint, symbol, t, open_prob, final_prob, stance, verdict)
                         VALUES (?,?,?,?,?,?,?,?)""", (x["model"], mint, symbol, now(),
                                                      first.get(x["model"], x)["prob"], x["prob"], x["stance"], verdict))
        c.execute("DELETE FROM votes WHERE t < ?", (now() - 30 * 86400,))


def link_votes(mint, pid):
    """The trade that came out of the latest debate on this coin."""
    with conn() as c:
        t = c.execute("SELECT MAX(t) FROM votes WHERE mint=? AND position_id IS NULL", (mint,)).fetchone()[0]
        if t is not None:
            c.execute("UPDATE votes SET position_id=? WHERE mint=? AND position_id IS NULL AND t >= ?", (pid, mint, t - 1))


def settle_votes(pid, pnl_pct) -> dict:
    """The trade closed: a model that said BUY earns its P/L %, one that doubted it earns the opposite."""
    out = {}
    with conn() as c:
        for r in c.execute("SELECT id, model, stance FROM votes WHERE position_id=?", (pid,)).fetchall():
            pts = round(pnl_pct if r["stance"] == "BUY" else -pnl_pct, 2)
            c.execute("UPDATE votes SET pnl_pct=?, points=?, closed=? WHERE id=?", (pnl_pct, pts, now(), r["id"]))
            out[r["model"]] = pts
    return out


def votes(model, limit=30):
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM votes WHERE model=? ORDER BY t DESC LIMIT ?", (model, limit))]


def vote_stats(model) -> dict:
    with conn() as c:
        r = c.execute("""SELECT COUNT(*), AVG(final_prob), SUM(stance='BUY'), SUM(position_id IS NOT NULL),
                         SUM(points > 0), SUM(points < 0), SUM(closed IS NOT NULL) FROM votes WHERE model=?""",
                      (model,)).fetchone()
    n, avg, buys, traded, right, wrong, closed = (v or 0 for v in r)
    return {"debates": n, "avg_confidence": round(avg, 4) if n else None, "buy_rate": round(buys / n, 3) if n else None,
            "trades": traded, "right": right, "wrong": wrong, "accuracy": round(right / closed, 3) if closed else None}


def seen_snap(mint) -> dict:
    with conn() as c:
        r = c.execute("SELECT snap FROM seen WHERE mint=?", (mint,)).fetchone()
    return jload(r[0], {}) if r else {}


# ---------- ranks ----------
def set_rank(model, rank, prev, points):
    with conn() as c:
        _ensure_bot(c, model)
        c.execute("UPDATE bots SET rank=?, rank_t=? WHERE model=?", (rank, now(), model))
        c.execute("INSERT INTO rank_log (model, t, rank, prev, points) VALUES (?,?,?,?,?)", (model, now(), rank, prev, points))


def rank_log(model, limit=12):
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM rank_log WHERE model=? ORDER BY t DESC LIMIT ?", (model, limit))]



# ---------- the tweet monitors ----------
def record_tweet(row: dict) -> int:
    """One coin a monitor picked out of X, with the post that put it there."""
    cols = ("mint", "symbol", "model", "beat", "tweet_id", "author", "followers", "likes", "url", "text",
            "tweet_t", "heat", "voices", "status", "why", "verdict", "also")
    with conn() as c:
        cur = c.execute(f"INSERT INTO tweets (t, {','.join(cols)}) VALUES ({','.join(['?'] * (len(cols) + 1))})",
                        (now(), *(row.get(k) for k in cols)))
        return cur.lastrowid


def tweet_verdict(rid: int, status: str, verdict: str | None = None, why: str | None = None):
    with conn() as c:
        c.execute("UPDATE tweets SET status=?, verdict=COALESCE(?, verdict), why=COALESCE(?, why) WHERE id=?",
                  (status, verdict, why, rid))


def tweet_finds(limit=40, model=None) -> list[dict]:
    q = "SELECT * FROM tweets" + (" WHERE model=?" if model else "") + " ORDER BY t DESC LIMIT ?"
    with conn() as c:
        return [dict(r) for r in c.execute(q, ((model, limit) if model else (limit,)))]


def tweet_ids(since: float) -> set:
    """Posts already handled, so the same tweet never costs a second look."""
    with conn() as c:
        return {r[0] for r in c.execute("SELECT tweet_id FROM tweets WHERE t>=?", (since,)) if r[0]}


def tweet_voices(mint: str, since: float) -> int:
    with conn() as c:
        r = c.execute("SELECT COUNT(DISTINCT author) FROM tweets WHERE mint=? AND t>=?", (mint, since)).fetchone()
    return int(r[0] or 0)


def tweet_stats(model=None) -> dict:
    where, args = (" WHERE model=?", (model,)) if model else ("", ())
    with conn() as c:
        r = c.execute(f"SELECT COUNT(*) n, SUM(status='traded') bought, SUM(status='blocked') blocked, "
                      f"MAX(t) last FROM tweets{where}", args).fetchone()
    return {"found": int(r["n"] or 0), "bought": int(r["bought"] or 0), "blocked": int(r["blocked"] or 0),
            "last": r["last"]}
