"""Pause around big news: the Fed, US jobs (NFP), CPI and other high-impact releases move gold hard.

The week's economic calendar comes from the public ForexFactory feed (JSON), cached in data/news_calendar.json and
refreshed every 6 hours in the background (a failed refresh keeps the last copy). `pause_reason(now)` says why the bot
shouldn't open a trade right now: a high-impact event for a watched currency (USD for gold) within N minutes before or
after. Used by agent/run.py (live and paper) and shown in the app (`GET /api/news`). Replays don't use it: there's no
calendar for past years.
"""
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

FEED = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CACHE = Path(__file__).resolve().parent.parent / "data" / "news_calendar.json"
REFRESH_S = 6 * 3600
RETRY_S = 15 * 60
_state = {"loading": False, "tried": 0.0, "error": ""}
_lock = threading.Lock()


def _read() -> dict:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"fetched": 0, "events": []}


def _parse(rows: list) -> list[dict]:
    out = []
    for r in rows:
        try:
            t = datetime.fromisoformat(str(r["date"]).replace("Z", "+00:00")).astimezone(timezone.utc)
        except (KeyError, ValueError):
            continue
        out.append({"time": int(t.timestamp()), "utc": t.isoformat(timespec="minutes"), "title": r.get("title", ""),
                    "currency": r.get("country", ""), "impact": r.get("impact", ""),
                    "forecast": r.get("forecast", ""), "previous": r.get("previous", "")})
    return sorted(out, key=lambda e: e["time"])


def refresh() -> dict:
    """Download this week's calendar now (blocking, ~1 s). Keeps the old copy if it fails."""
    import httpx
    _state["tried"] = time.time()
    try:
        r = httpx.get(FEED, timeout=15, headers={"User-Agent": "TradingBot/1.0"})
        r.raise_for_status()
        events = _parse(r.json())
        old = [e for e in _read()["events"] if e["time"] < (events[0]["time"] if events else 0)]
        data = {"fetched": int(time.time()), "events": (old + events)[-400:]}   # keep last week's too
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(CACHE)
        _state["error"] = ""
        return data
    except Exception as e:                             # noqa: BLE001 - offline: keep trading on the last calendar
        _state["error"] = f"couldn't update the news calendar ({type(e).__name__})"
        return _read()
    finally:
        _state["loading"] = False


def ensure_fresh():
    """Start a background refresh when the calendar is older than 6 h (at most one try every 15 min)."""
    data = _read()
    now = time.time()
    with _lock:
        if _state["loading"] or now - data.get("fetched", 0) < REFRESH_S or now - _state["tried"] < RETRY_S:
            return
        _state["loading"] = True
    threading.Thread(target=refresh, name="news", daemon=True).start()


def _matches(e: dict, currencies, impacts) -> bool:
    return e["currency"] in currencies and e["impact"] in impacts


def pause_reason(now: datetime | None = None, before_min: float = 15, after_min: float = 15,
                 currencies=("USD",), impacts=("High",)) -> str | None:
    """Why not to open a trade right now, or None. `now` is UTC."""
    if before_min <= 0 and after_min <= 0:
        return None
    ensure_fresh()
    ts = (now or datetime.now(timezone.utc)).timestamp()
    for e in _read()["events"]:
        if _matches(e, currencies, impacts) and e["time"] - before_min * 60 <= ts <= e["time"] + after_min * 60:
            when = datetime.fromtimestamp(e["time"], timezone.utc).strftime("%H:%M")
            return f"news: {e['currency']} {e['title']} at {when} UTC (no new trades {before_min:g} min before to {after_min:g} min after)"
    return None


def upcoming(hours: float = 48, currencies=("USD",), impacts=("High",)) -> list[dict]:
    now = time.time()
    return [e for e in _read()["events"]
            if _matches(e, currencies, impacts) and now - 3600 <= e["time"] <= now + hours * 3600]


def summary(s: dict) -> dict:
    """For the app: the next events, whether the bot is paused now, and when the calendar was fetched."""
    cur, imp = tuple(s.get("news_currencies") or ["USD"]), tuple(s.get("news_impact") or ["High"])
    on = bool(s.get("news_pause", True))
    b, a = float(s.get("news_before_min", 15)), float(s.get("news_after_min", 15))
    data = _read()
    ensure_fresh()
    return {"enabled": on, "before_min": b, "after_min": a, "currencies": list(cur), "impact": list(imp),
            "paused": pause_reason(None, b, a, cur, imp) if on else None,
            "events": upcoming(48, cur, imp), "fetched": data.get("fetched") or None,
            "stale": time.time() - (data.get("fetched") or 0) > 2 * REFRESH_S, "error": _state["error"]}


if __name__ == "__main__":                              # python -m agent.news: fetch and print the next events
    refresh()
    for e in upcoming(24 * 7):
        print(e["utc"], e["currency"], e["impact"], e["title"])
    print(_state["error"] or "ok")
