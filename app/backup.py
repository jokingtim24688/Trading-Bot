"""Daily backup of everything the app has learned and recorded, as one zip.

What goes in: the bot's trade ledger (a consistent copy of trades.db), settings, Hermes's memory, the bot's rules,
lessons and mistakes, the stage ladder, your trade notes and stop rules, weekly reviews, Hermes's notes, your sounds,
the quiz report and the trained models. Left out: candle history and quiz caches (they can be downloaded or rebuilt).

Where: `backup_dir` (e.g. a OneDrive or USB folder, so a dead disk doesn't take the backups with it), default
data/backups/full/. The newest `backup_keep` (14) are kept. Made once a day by itself; `POST /api/backup/data` makes one
now. To restore: close the app, unzip the file over the Trading-Bot folder, start the app.
"""
import sqlite3
import tempfile
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path

from .settings import DATA, ROOT, load

FILES = ["settings.json", "hermes_memory.json", "learned_rules.json", "mistakes.json", "progression.json",
         "manual_auto.json", "closed_levels.json", "trade_notes.json", "quiz_report.json", "quiz_report.md"]
DIRS = ["reviews", "notes", "sounds"]
MODEL_GLOBS = ["*.json"]                               # models/: XGBoost + quiz policy, a few MB
DAY_S = 24 * 3600
_lock = threading.Lock()
_thread: threading.Thread | None = None
_last = {"error": ""}


def folder() -> Path:
    d = (load().get("backup_dir") or "").strip()
    return Path(d).expanduser() if d else DATA / "backups" / "full"


def listing() -> list[dict]:
    d = folder()
    if not d.exists():
        return []
    rows = [{"name": p.name, "time": int(p.stat().st_mtime), "size": p.stat().st_size, "path": str(p),
             "_ns": p.stat().st_mtime_ns} for p in d.glob("data-*.zip")]
    rows.sort(key=lambda r: r.pop("_ns"), reverse=True)            # newest first
    return rows


def make() -> dict:
    """Write a backup zip now and prune old ones."""
    with _lock:
        d = folder()
        d.mkdir(parents=True, exist_ok=True)
        stem = f"data-{datetime.now():%Y%m%d-%H%M%S}"
        name, k = f"{stem}.zip", 2
        while (d / name).exists():
            name, k = f"{stem}-{k}.zip", k + 1
        tmp = d / (name + ".part")
        n = 0
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            db = DATA / "trades.db"
            if db.exists():                            # sqlite's own backup: consistent even while the bot writes
                with tempfile.TemporaryDirectory() as td:
                    copy = Path(td) / "trades.db"
                    src, dst = sqlite3.connect(db, timeout=10), sqlite3.connect(copy)
                    try:
                        src.backup(dst)
                    finally:
                        src.close()
                        dst.close()
                    z.write(copy, "data/trades.db")
                    n += 1
            for f in FILES:
                p = DATA / f
                if p.exists():
                    z.write(p, f"data/{f}")
                    n += 1
            for sub in DIRS:
                base = DATA / sub
                for p in sorted(base.rglob("*")) if base.exists() else []:
                    if p.is_file():
                        z.write(p, f"data/{p.relative_to(DATA).as_posix()}")
                        n += 1
            for p in sorted((DATA / "backups").glob("settings-*.json")):   # the settings backups too
                z.write(p, f"data/backups/{p.name}")
                n += 1
            models = ROOT / "models"
            for g in MODEL_GLOBS:
                for p in sorted(models.glob(g)) if models.exists() else []:
                    z.write(p, f"models/{p.name}")
                    n += 1
        tmp.replace(d / name)
        keep = max(1, int(load().get("backup_keep", 14) or 14))
        for old in listing()[keep:]:
            Path(old["path"]).unlink(missing_ok=True)
        _last["error"] = ""
        p = d / name
        return {"name": name, "path": str(p), "size": p.stat().st_size, "files": n}


def _auto():
    """Every hour: make a backup if the newest is more than a day old."""
    while True:
        try:
            if load().get("backup_daily", True):
                rows = listing()
                if not rows or time.time() - rows[0]["time"] > DAY_S:
                    make()
        except Exception as e:                         # noqa: BLE001 - e.g. the backup folder is on a missing drive
            _last["error"] = f"backup failed: {e}"
            print(f"({_last['error']})", flush=True)
        time.sleep(3600)


def status() -> dict:
    s = load()
    return {"folder": str(folder()), "daily": bool(s.get("backup_daily", True)), "keep": s.get("backup_keep", 14),
            "backups": listing(), "error": _last["error"]}


def start():
    global _thread
    if _thread is None or not _thread.is_alive():
        _thread = threading.Thread(target=_auto, name="backup", daemon=True)
        _thread.start()
