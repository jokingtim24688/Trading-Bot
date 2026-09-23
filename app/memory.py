"""Long-term memory on disk (SQLite). Used by the local Hermes backend; Hermes Agent keeps its own memory too.

Two tables: `messages` (every chat turn) and `facts` (things the assistant was asked to remember or chose to save).
Only the most relevant facts and the last few messages are loaded into RAM per request.
"""
import re
import sqlite3
import time

from .settings import DATA

DB = DATA / "memory.db"


def _conn():
    c = sqlite3.connect(DB)
    c.execute("CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, ts REAL, role TEXT, content TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS facts (id INTEGER PRIMARY KEY, ts REAL, text TEXT UNIQUE)")
    return c


def add_message(role: str, content: str):
    with _conn() as c:
        c.execute("INSERT INTO messages (ts, role, content) VALUES (?, ?, ?)", (time.time(), role, content))


def recent_messages(n: int = 16) -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT role, content, ts FROM messages ORDER BY id DESC LIMIT ?", (n,)).fetchall()
    return [{"role": r, "content": t, "ts": ts} for r, t, ts in reversed(rows)]


def remember(text: str) -> str:
    text = text.strip()
    if not text:
        return "nothing to remember"
    with _conn() as c:
        c.execute("INSERT OR IGNORE INTO facts (ts, text) VALUES (?, ?)", (time.time(), text))
    return f"saved: {text}"


def forget(fact_id: int) -> str:
    with _conn() as c:
        c.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
    return f"deleted fact {fact_id}"


def all_facts() -> list[dict]:
    with _conn() as c:
        return [{"id": i, "ts": ts, "text": t} for i, ts, t in c.execute("SELECT id, ts, text FROM facts ORDER BY id")]


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 2}


def relevant_facts(query: str, limit: int = 12) -> list[str]:
    """Keyword-overlap ranking; newest facts win ties. Cheap enough to run on every message."""
    facts = all_facts()
    q = _words(query)
    scored = sorted(facts, key=lambda f: (len(q & _words(f["text"])), f["ts"]), reverse=True)
    return [f["text"] for f in scored[:limit]]


def search_messages(query: str, limit: int = 8) -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT role, content, ts FROM messages WHERE content LIKE ? ORDER BY id DESC LIMIT ?",
                         (f"%{query}%", limit)).fetchall()
    return [{"role": r, "content": t[:500], "ts": ts} for r, t, ts in rows]


def clear_chat():
    with _conn() as c:
        c.execute("DELETE FROM messages")
