"""Hermes's long-term memory in one plain file: data/hermes_memory.json.

It holds `facts` (things Hermes was asked to remember or chose to save) and `messages` (every chat turn). The file is
written after every change (via a temp file, so a crash can't corrupt it) and read back at start, so Hermes keeps
its memory across app restarts and when the model is unloaded between chats. You can open, back up or edit it in any
text editor. An older data/memory.db (SQLite) is imported once, automatically.
"""
import json
import re
import threading
import time

from .settings import DATA

FILE = DATA / "hermes_memory.json"
OLD_DB = DATA / "memory.db"
MAX_MESSAGES = 5000                     # oldest chat turns drop off after this; facts are never dropped

_lock = threading.RLock()
_mem: dict | None = None


def _import_old() -> dict:
    """One-time import from the SQLite memory used before 2026-09-24."""
    mem = {"facts": [], "messages": [], "next_id": 1}
    if not OLD_DB.exists():
        return mem
    try:
        import sqlite3
        with sqlite3.connect(OLD_DB) as c:
            mem["facts"] = [{"id": i, "ts": ts, "text": t} for i, ts, t in c.execute("SELECT id, ts, text FROM facts ORDER BY id")]
            mem["messages"] = [{"role": r, "content": t, "ts": ts}
                               for r, t, ts in c.execute("SELECT role, content, ts FROM messages ORDER BY id")]
        mem["next_id"] = max([f["id"] for f in mem["facts"]], default=0) + 1
    except Exception:                   # noqa: BLE001 - an unreadable old file just means starting fresh
        pass
    return mem


def _load() -> dict:
    global _mem
    if _mem is None:
        try:
            _mem = json.loads(FILE.read_text(encoding="utf-8"))
            _mem.setdefault("facts", [])
            _mem.setdefault("messages", [])
            _mem.setdefault("next_id", max([f["id"] for f in _mem["facts"]], default=0) + 1)
        except FileNotFoundError:
            _mem = _import_old()
            _save()
        except ValueError:              # damaged file: keep it aside and start a new one
            FILE.replace(FILE.with_suffix(f".broken-{int(time.time())}.json"))
            _mem = {"facts": [], "messages": [], "next_id": 1}
            _save()
    return _mem


def _save():
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(_mem, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(FILE)


def add_message(role: str, content: str):
    with _lock:
        m = _load()
        m["messages"].append({"role": role, "content": content, "ts": time.time()})
        del m["messages"][:-MAX_MESSAGES]
        _save()


def recent_messages(n: int = 16) -> list[dict]:
    with _lock:
        return [dict(x) for x in _load()["messages"][-n:]] if n > 0 else []


def remember(text: str) -> str:
    text = text.strip()
    if not text:
        return "nothing to remember"
    with _lock:
        m = _load()
        if any(f["text"] == text for f in m["facts"]):
            return f"already saved: {text}"
        m["facts"].append({"id": m["next_id"], "ts": time.time(), "text": text})
        m["next_id"] += 1
        _save()
    return f"saved: {text}"


def forget(fact_id: int) -> str:
    with _lock:
        m = _load()
        m["facts"] = [f for f in m["facts"] if f["id"] != fact_id]
        _save()
    return f"deleted fact {fact_id}"


def all_facts() -> list[dict]:
    with _lock:
        return [dict(f) for f in _load()["facts"]]


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 2}


def relevant_facts(query: str, limit: int = 12) -> list[str]:
    """Keyword-overlap ranking; newest facts win ties. Cheap enough to run on every message."""
    facts = all_facts()
    q = _words(query)
    scored = sorted(facts, key=lambda f: (len(q & _words(f["text"])), f["ts"]), reverse=True)
    return [f["text"] for f in scored[:limit]]


def search_messages(query: str, limit: int = 8) -> list[dict]:
    """Past chat turns that mention the query (newest first), for the recall tool."""
    q = query.lower()
    with _lock:
        hits = [x for x in reversed(_load()["messages"]) if q in x["content"].lower()][:limit]
    return [{"role": x["role"], "content": x["content"][:500], "ts": x["ts"]} for x in hits]


def clear_chat():
    """Clear the chat log (the Clear button). Saved facts stay."""
    with _lock:
        _load()["messages"] = []
        _save()
