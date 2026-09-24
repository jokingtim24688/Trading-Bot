"""Your own alert sounds (Sounds page): upload, list, play, rename, delete. Files live in data/sounds/<id>.<ext>, with
their names in data/sounds/index.json. Uploads come as base64 in JSON (no multipart dependency), at most 5 MB, and
must really be audio: wav, mp3, ogg, m4a/aac, flac or webm (the first bytes are checked, not just the name).
"""
import base64
import binascii
import json
import re
import secrets
import threading
import time

from .settings import DATA

DIR = DATA / "sounds"
INDEX = DIR / "index.json"
MAX_BYTES = 5 * 1024 * 1024
_lock = threading.Lock()

# extension -> content type served back
TYPES = {"wav": "audio/wav", "mp3": "audio/mpeg", "ogg": "audio/ogg", "m4a": "audio/mp4", "aac": "audio/aac",
         "flac": "audio/flac", "webm": "audio/webm"}
ALIASES = {"audio/wav": "wav", "audio/x-wav": "wav", "audio/wave": "wav", "audio/vnd.wave": "wav",
           "audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/ogg": "ogg", "application/ogg": "ogg", "audio/opus": "ogg",
           "audio/mp4": "m4a", "audio/x-m4a": "m4a", "audio/m4a": "m4a", "audio/aac": "aac", "audio/x-aac": "aac",
           "audio/flac": "flac", "audio/x-flac": "flac", "audio/webm": "webm", "video/webm": "webm"}


class TooBig(ValueError):
    pass


class NotAudio(ValueError):
    pass


def _sniff(b: bytes) -> str | None:
    """The audio format from the file's first bytes."""
    if b[:4] == b"RIFF" and b[8:12] == b"WAVE":
        return "wav"
    if b[:3] == b"ID3" or (len(b) > 1 and b[0] == 0xFF and (b[1] & 0xE0) == 0xE0 and (b[1] & 0x06)):
        return "mp3"                                # ID3 tag, or an MPEG audio frame (layer bits set)
    if b[:4] == b"OggS":
        return "ogg"
    if b[:4] == b"fLaC":
        return "flac"
    if b[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    if b[4:8] == b"ftyp":
        return "m4a"
    if len(b) > 1 and b[0] == 0xFF and (b[1] & 0xF6) == 0xF0:
        return "aac"                                # ADTS frame
    return None


def _load() -> dict:
    try:
        return json.loads(INDEX.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(idx: dict):
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = INDEX.with_suffix(".tmp")
    tmp.write_text(json.dumps(idx, indent=1), encoding="utf-8")
    tmp.replace(INDEX)


def _row(sid: str, r: dict) -> dict:
    return {"id": sid, "name": r["name"], "type": TYPES[r["ext"]], "size": r["size"], "added": r["added"],
            "url": f"/api/sounds/{sid}"}


def _clean_name(name: str) -> str:
    name = re.sub(r"\s+", " ", str(name or "")).strip()[:80]
    if not name:
        raise ValueError("Give the sound a name.")
    return name


def listing() -> list[dict]:
    with _lock:
        idx = _load()
    return sorted((_row(k, v) for k, v in idx.items()), key=lambda r: r["added"], reverse=True)


def add(name: str, type_: str, data: str) -> dict:
    name = _clean_name(name)
    if not isinstance(data, str) or not data:
        raise ValueError("No file data.")
    if "," in data[:100] and data.startswith("data:"):
        data = data.split(",", 1)[1]                # a data: URL is fine too
    if len(data) > (MAX_BYTES * 4) // 3 + 8:
        raise TooBig("That file is bigger than 5 MB.")
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("The file data isn't valid base64.")
    if len(raw) > MAX_BYTES:
        raise TooBig("That file is bigger than 5 MB.")
    ext = _sniff(raw[:16])
    said = ALIASES.get((type_ or "").split(";")[0].strip().lower())
    if ext is None or (said and said != ext and {said, ext} not in ({"m4a", "aac"}, {"ogg", "webm"})):
        raise NotAudio("Only wav, mp3, ogg, m4a/aac, flac or webm audio files can be added.")
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:24] or "sound"
    sid = f"{slug}-{secrets.token_hex(3)}"
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / f"{sid}.{ext}").write_bytes(raw)
    with _lock:
        idx = _load()
        idx[sid] = {"name": name, "ext": ext, "size": len(raw), "added": int(time.time())}
        _save(idx)
        return _row(sid, idx[sid])


def _get(sid: str) -> dict:
    r = _load().get(sid)
    if not r or not re.fullmatch(r"[a-z0-9-]+", sid):
        raise KeyError(sid)
    return r


def file(sid: str) -> tuple:
    """(path, content type) for playing it."""
    with _lock:
        r = _get(sid)
    return DIR / f"{sid}.{r['ext']}", TYPES[r["ext"]]


def rename(sid: str, name: str) -> dict:
    name = _clean_name(name)
    with _lock:
        idx = _load()
        _get(sid)
        idx[sid]["name"] = name
        _save(idx)
        return _row(sid, idx[sid])


def delete(sid: str) -> dict:
    with _lock:
        idx = _load()
        r = _get(sid)
        (DIR / f"{sid}.{r['ext']}").unlink(missing_ok=True)
        del idx[sid]
        _save(idx)
    return {"ok": True}
