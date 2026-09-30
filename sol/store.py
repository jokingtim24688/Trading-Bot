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
    """)
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


def add_score(model, pts, win=False, quiz=False):
    with conn() as c:
        c.execute("INSERT OR IGNORE INTO bots VALUES (?,0,0,0)", (model,))
        if quiz:
            c.execute("UPDATE bots SET quiz=quiz+? WHERE model=?", (pts, model))
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
