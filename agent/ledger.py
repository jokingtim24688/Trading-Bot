"""The bot's own trade ledger (data/trades.db), shared by the agent process and the app.

Only trades the bot opened are recorded here (identified by its magic number in live mode), so your manual
trades on the same account never mix into its record. Times: `*_utc` are wall-clock ISO strings; `open_bar` /
`close_bar` are MT5 server-time epochs, the same clock the M1 chart uses, so the app can place markers.
"""
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from . import score as scoring

DB = Path(__file__).resolve().parent.parent / "data" / "trades.db"

COLUMNS = ("id", "mode", "symbol", "side", "lots", "entry", "sl", "sl0", "tp", "prob", "risk_money", "ticket",
           "status", "open_utc", "open_bar", "exit", "exit_reason", "pnl", "r_multiple", "close_utc", "close_bar", "updated")


def _conn():
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY, mode TEXT, symbol TEXT, side TEXT, lots REAL, entry REAL, sl REAL, sl0 REAL, tp REAL,
        prob REAL, risk_money REAL, ticket INTEGER, status TEXT, open_utc TEXT, open_bar INTEGER,
        exit REAL, exit_reason TEXT, pnl REAL, r_multiple REAL, close_utc TEXT, close_bar INTEGER, updated REAL)""")
    c.execute("CREATE INDEX IF NOT EXISTS ix_trades_mode_status ON trades(mode, status)")
    have = {r[1] for r in c.execute("PRAGMA table_info(trades)")}
    for col, typ in (("stake", "REAL"), ("score", "REAL"), ("close_hint", "TEXT"), ("setup", "TEXT"), ("quiz", "TEXT")):
        if col not in have:                         # upgrade ledgers created before scoring existed
            c.execute(f"ALTER TABLE trades ADD COLUMN {col} {typ}")
    return c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def open_trade(mode, symbol, side, lots, entry, sl, tp, prob=None, risk_money=None, ticket=None, open_bar=None,
               stake=None, open_utc=None, setup=None, quiz=None) -> int:
    """quiz: what the quiz agent said at entry (buy / sell / wait), to measure whether its second opinion helps."""
    with _conn() as c:
        cur = c.execute("""INSERT INTO trades (mode, symbol, side, lots, entry, sl, sl0, tp, prob, risk_money, ticket, status,
                           open_utc, open_bar, updated, stake, setup, quiz) VALUES (?,?,?,?,?,?,?,?,?,?,?, 'open', ?,?,?,?,?,?)""",
                        (mode, symbol, side, lots, entry, sl, sl, tp, prob, risk_money, ticket, open_utc or _now(), open_bar, time.time(),
                         stake, setup, quiz))
        return cur.lastrowid


def close_trade(trade_id: int, exit_price: float, reason: str, pnl: float, close_bar: int | None = None,
                close_utc: str | None = None):
    with _conn() as c:
        t = c.execute("SELECT side, entry, sl0, stake, mode FROM trades WHERE id = ?", (trade_id,)).fetchone()
        # R from price distance vs the ORIGINAL stop (side-aware), so paper and live compare regardless of lot size
        risk_px = abs(t["entry"] - t["sl0"]) if t and t["sl0"] else 0
        r = None
        if risk_px and exit_price:
            move = (exit_price - t["entry"]) if t["side"] == "buy" else (t["entry"] - exit_price)
            r = round(move / risk_px, 3)
        pts = scoring.trade_score(pnl, t["stake"] if t else None, r, reason)
        c.execute("UPDATE trades SET status='closed', exit=?, exit_reason=?, pnl=?, r_multiple=?, close_utc=?, "
                  "close_bar=?, updated=?, score=? WHERE id=?",
                  (exit_price, reason, round(pnl, 2), r, close_utc or _now(), close_bar, time.time(), pts, trade_id))
    if pnl < 0 and t and t["mode"] != "replay":          # a losing trade teaches the bot something right away
        try:
            from . import learn
            learn.on_mistake(trade_id)
        except Exception as e:                           # noqa: BLE001 - learning must never break recording a close
            print(f"(learning from trade {trade_id} skipped: {e})", flush=True)


def get(trade_id: int) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    return dict(r) if r else None


def set_close_hint(trade_id: int, reason: str):
    """Say why the bot/app is about to close a live trade ("early", "kill"), since MT5 only records it as an EA close."""
    with _conn() as c:
        c.execute("UPDATE trades SET close_hint=? WHERE id=?", (reason, trade_id))


def update_levels(trade_id: int, sl: float | None = None, tp: float | None = None):
    """Track SL/TP changes (e.g. you moved the bot's stop in MT5). R still uses the original stop `sl0`."""
    with _conn() as c:
        if sl is not None:
            c.execute("UPDATE trades SET sl=?, updated=? WHERE id=?", (sl, time.time(), trade_id))
        if tp is not None:
            c.execute("UPDATE trades SET tp=?, updated=? WHERE id=?", (tp, time.time(), trade_id))


def open_trades(mode: str | None = None, symbol: str | None = None) -> list[dict]:
    q, args = "SELECT * FROM trades WHERE status='open'", []
    if mode:
        q += " AND mode=?"; args.append(mode)
    if symbol:
        q += " AND symbol=?"; args.append(symbol)
    with _conn() as c:
        return [dict(r) for r in c.execute(q + " ORDER BY id", args)]


def recent(limit: int = 200, mode: str | None = None, symbol: str | None = None) -> list[dict]:
    q, args = "SELECT * FROM trades WHERE 1=1", []
    if mode:
        q += " AND mode=?"; args.append(mode)
    if symbol:
        q += " AND symbol=?"; args.append(symbol)
    with _conn() as c:
        return [dict(r) for r in c.execute(q + " ORDER BY id DESC LIMIT ?", (*args, limit))]


def realized_pnl(mode: str, since_utc: str | None = None, day: str | None = None) -> float:
    q, args = "SELECT COALESCE(SUM(pnl),0) FROM trades WHERE status='closed' AND mode=?", [mode]
    if since_utc:
        q += " AND close_utc >= ?"; args.append(since_utc)
    if day:                                            # 'YYYY-MM-DD'
        q += " AND close_utc >= ? AND close_utc < ?"; args += [day, day + "~"]
    with _conn() as c:
        return float(c.execute(q, args).fetchone()[0])


def stats(mode: str | None = None, symbol: str | None = None) -> dict:
    rows = [r for r in recent(100_000, mode, symbol) if r["status"] == "closed"]
    today = datetime.now(timezone.utc).date().isoformat()
    wins = [r for r in rows if (r["pnl"] or 0) > 0]
    rs = [r["r_multiple"] for r in rows if r["r_multiple"] is not None]
    gross_win = sum(r["pnl"] for r in wins)
    gross_loss = -sum(r["pnl"] for r in rows if (r["pnl"] or 0) < 0)
    return {
        "closed": len(rows),
        "open": len(open_trades(mode, symbol)),
        "win_pct": round(100 * len(wins) / len(rows), 1) if rows else None,
        "net_pnl": round(sum(r["pnl"] or 0 for r in rows), 2),
        "today_pnl": round(sum(r["pnl"] or 0 for r in rows if (r["close_utc"] or "").startswith(today)), 2),
        "total_r": round(sum(rs), 2),
        "avg_r": round(sum(rs) / len(rs), 3) if rs else None,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else None,
        "score": round(sum(r["score"] or 0 for r in rows), 1),
        "today_score": round(sum(r["score"] or 0 for r in rows if (r["close_utc"] or "").startswith(today)), 1),
        "avg_score": round(sum(r["score"] or 0 for r in rows) / len(rows), 1) if rows else None,
        "sl_hits": sum(1 for r in rows if r["exit_reason"] in scoring.STOP_REASONS),
        "early_exits": sum(1 for r in rows if r["exit_reason"] == "early"),
    }
