"""Weekly summary (`/api/review/weekly`): what went well and what to fix, for you and the bot, one ISO week at a time.

Built from the you-vs-bot numbers (app/stats.py), the P/L per day, and the bot's losing trades and lessons
(agent/learn.py). Hermes writes the sentences when its model is already up (it's never downloaded or started just for
this); otherwise rule-based sentences are used. Stored in data/reviews/<week>.json. The app makes last week's once a week
by itself (checked every hour).
"""
import json
import threading
import time
from datetime import date, datetime, timedelta, timezone

import httpx

from agent import learn

from . import brain, stats
from .settings import DATA, load

DIR = DATA / "reviews"
_busy: set[str] = set()
_lock = threading.Lock()
_thread: threading.Thread | None = None
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def week_bounds(week: str | None = None) -> tuple[str, datetime, datetime]:
    """'2026-W39' -> (label, Monday 00:00, next Monday 00:00). None = the last full week."""
    if not week:
        y, w, _ = (date.today() - timedelta(days=7)).isocalendar()
        week = f"{y}-W{w:02d}"
    try:
        y, w = week.upper().split("-W")
        monday = date.fromisocalendar(int(y), int(w), 1)
    except ValueError:
        raise ValueError(f"Week must look like 2026-W39, not {week!r}.")
    start = datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)
    return f"{int(y)}-W{int(w):02d}", start, start + timedelta(days=7)


def _money(v) -> str:
    return f"{'+' if v >= 0 else '-'}${abs(v):,.2f}"


def _facts(start: datetime, end: datetime) -> dict:
    you_rows = stats.you_trades(start, end)
    you_rows = [t for t in you_rows if start.timestamp() <= t["time"] < end.timestamp()]
    bot_rows = stats.bot_trades(int(start.timestamp()), int(end.timestamp()), None)   # the stage it is on now
    you, bot = stats.summarize(you_rows), stats.summarize(bot_rows)
    days: dict[str, float] = {}
    for t in you_rows + bot_rows:
        d = DAYS[datetime.fromtimestamp(t["time"], timezone.utc).weekday()]
        days[d] = round(days.get(d, 0.0) + t["profit"], 2)
    mistakes = [m for m in learn.load_mistakes()
                if start.isoformat() <= (m.get("close_utc") or "") < end.isoformat()]
    rules = learn.load_rules() if hasattr(learn, "load_rules") else {}
    tags: dict[str, list] = {}
    for t in you_rows:
        for tag in t.get("tags") or []:
            tags.setdefault(tag, []).append(t["profit"])
    return {"you": you, "bot": bot, "days": days, "mistakes": mistakes, "rules": rules or {}, "tags": tags}


def _hour_extremes(s: dict) -> tuple:
    rows = [h for h in s["by_hour"] if h["trades"]]
    if len(rows) < 2:
        return None, None
    best = max(rows, key=lambda h: h["net"])
    worst = min(rows, key=lambda h: h["net"])
    return (best if best["net"] > 0 else None), (worst if worst["net"] < 0 else None)


def rule_text(f: dict) -> tuple[list[str], list[str]]:
    good, fix = [], []
    for who, s in (("You", f["you"]), ("The bot", f["bot"])):
        if not s["trades"]:
            continue
        line = f"{who} closed {s['trades']} trade{'s' * (s['trades'] != 1)} for {_money(s['net'])} ({s['win_rate']}% won)."
        (good if s["net"] > 0 else fix).append(line)
        if s["profit_factor"] and s["profit_factor"] >= 1.2:
            good.append(f"{who}: profit factor {s['profit_factor']} - the wins more than paid for the losses.")
        if s["avg_win"] and s["avg_loss"] and abs(s["avg_loss"]) > s["avg_win"]:
            fix.append(f"{who}: the average loss ({_money(s['avg_loss'])}) was bigger than the average win "
                       f"({_money(s['avg_win'])}); let winners run or cut losers sooner.")
        best, worst = _hour_extremes(s)
        if best:
            good.append(f"{who}: best hour was {best['hour']:02d}:00 server time ({_money(best['net'])}).")
        if worst:
            fix.append(f"{who}: {worst['hour']:02d}:00 server time cost {_money(worst['net'])}; be pickier then.")
    tagged = {k: v for k, v in f.get("tags", {}).items() if len(v) >= 2}
    if tagged:                                       # your own notes: which kinds of trades worked
        net = {k: sum(v) for k, v in tagged.items()}
        best, worst = max(net, key=net.get), min(net, key=net.get)
        if net[best] > 0:
            good.append(f"Your \"{best}\" trades made {_money(net[best])} over {len(tagged[best])} trades.")
        if net[worst] < 0 and worst != best:
            fix.append(f"Your \"{worst}\" trades lost {_money(net[worst])} over {len(tagged[worst])} trades.")
    if f["days"]:
        bd = max(f["days"], key=f["days"].get)
        wd = min(f["days"], key=f["days"].get)
        if f["days"][bd] > 0:
            good.append(f"{bd} was the best day ({_money(f['days'][bd])}).")
        if f["days"][wd] < 0 and wd != bd:
            fix.append(f"{wd} was the worst day ({_money(f['days'][wd])}).")
    ms = f["mistakes"]
    if ms:
        stops = sum(1 for m in ms if m.get("exit_reason") == "sl")
        fix.append(f"The bot learned from {len(ms)} losing trade{'s' * (len(ms) != 1)} ({stops} hit the stop).")
        if ms[-1].get("lesson"):
            fix.append("Latest lesson: " + ms[-1]["lesson"])
    elif f["bot"]["trades"]:
        good.append("The bot had no losing trades to learn from.")
    if not good:
        good.append("No winning trades this week." if (f["you"]["trades"] or f["bot"]["trades"])
                    else "No trades this week, so nothing was risked.")
    if not fix:
        fix.append("Nothing stood out to fix; keep the same rules.")
    return good[:5], fix[:5]


def _hermes_text(f: dict, good: list[str], fix: list[str]) -> tuple[list[str], list[str]] | None:
    """Ask Hermes to rewrite the lists in its own words, only if its model is already running. None on any trouble."""
    s = load()
    try:
        if not (brain.ollama_alive(s) and brain.model_ready(s)):
            return None
        facts = {"you": stats.lite(f["you"]), "bot": stats.lite(f["bot"]), "p_l_by_day": f["days"],
                 "draft_went_well": good, "draft_fix": fix}
        prompt = ("You are Hermes, a trading coach. Here is last week's trading summary as JSON:\n"
                  f"{json.dumps(facts)}\n"
                  "Write 3 to 5 short, plain sentences for what went well and 3 to 5 for what to fix. Use only these "
                  "numbers; don't invent any. Reply with JSON only: {\"went_well\": [...], \"fix\": [...]}")
        r = httpx.post(f"{s['ollama_url']}/api/generate", timeout=httpx.Timeout(10, read=180),
                       json={"model": s["ollama_model"], "prompt": prompt, "stream": False, "format": "json",
                             "keep_alive": brain._keep_alive(s), "options": brain._options(s)})
        out = json.loads(r.json()["response"])
        g = [str(x).strip() for x in out.get("went_well", []) if str(x).strip()][:5]
        x = [str(x).strip() for x in out.get("fix", []) if str(x).strip()][:5]
        return (g, x) if g and x else None
    except Exception:                                      # noqa: BLE001 - fall back to the rule-based text
        return None


def build(week: str | None = None, use_hermes: bool = True) -> dict:
    label, start, end = week_bounds(week)
    f = _facts(start, end)
    good, fix = rule_text(f)
    source = "rules"
    if use_hermes:
        h = _hermes_text(f, good, fix)
        if h:
            (good, fix), source = h, "hermes"
    rv = {"week": label, "from": start.date().isoformat(), "to": (end - timedelta(days=1)).date().isoformat(),
          "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": source,
          "went_well": good, "fix": fix, "numbers": {"you": stats.lite(f["you"]), "bot": stats.lite(f["bot"])}}
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = DIR / f"{label}.tmp"
    tmp.write_text(json.dumps(rv, indent=1), encoding="utf-8")
    tmp.replace(DIR / f"{label}.json")
    return rv


def get(week: str | None = None) -> dict:
    """The stored review; made now (rules only, fast) if there isn't one yet. `working` while a rebuild runs."""
    label, _, _ = week_bounds(week)
    p = DIR / f"{label}.json"
    rv = json.loads(p.read_text(encoding="utf-8")) if p.exists() else build(label, use_hermes=False)
    return {**rv, "working": label in _busy}


def regenerate(week: str | None = None) -> dict:
    """Make the review again in the background (Hermes can take a minute). Poll GET for the result."""
    label, _, _ = week_bounds(week)
    with _lock:
        if label not in _busy:
            _busy.add(label)

            def run():
                try:
                    build(label)
                finally:
                    _busy.discard(label)
            threading.Thread(target=run, name=f"review {label}", daemon=True).start()
    return {"week": label, "working": True}


def weeks() -> list[str]:
    return sorted((p.stem for p in DIR.glob("*-W*.json")), reverse=True) if DIR.exists() else []


def _auto():
    """Once an hour: make last week's review if it isn't there yet."""
    while True:
        try:
            label, _, _ = week_bounds(None)
            if not (DIR / f"{label}.json").exists() and label not in _busy:
                regenerate(label)
        except Exception as e:                             # noqa: BLE001 - keep trying next hour
            print(f"(weekly review: {e})", flush=True)
        time.sleep(3600)


def start():
    global _thread
    if _thread is None or not _thread.is_alive():
        _thread = threading.Thread(target=_auto, name="weekly review", daemon=True)
        _thread.start()
