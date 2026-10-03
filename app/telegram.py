"""Trade alerts on your phone through your own Telegram bot.

Set up once: in Telegram, talk to @BotFather, send /newbot and copy the token it gives you into Settings (telegram_token).
Then send your new bot any message (e.g. "hi") and press "Find my chat" (`POST /api/telegram/detect`), which reads
that message to learn your chat id. `POST /api/telegram/test` sends a test message.

Which events are sent: `telegram_events` (default tp, sl, open, close; also possible: be, trail). Messages go out from a
background queue, so a slow or offline connection never holds up trading. Only this PC talks to api.telegram.org; the
token stays in data/settings.json.
"""
import queue
import re
import threading
import time

import httpx

from .settings import load, save

API = "https://api.telegram.org"
EVENTS = ("open", "tp", "sl", "close", "be", "trail", "watchdog")
WATCHDOG = ("agent_restart", "agent_failed", "agent_stuck", "mt5_down", "mt5_up")   # all under "watchdog"
_q: "queue.Queue[str]" = queue.Queue(maxsize=200)
_thread: threading.Thread | None = None
_last = {"error": "", "sent": 0}


def _url(token: str, method: str) -> str:
    return f"{API}/bot{token.strip()}/{method}"


def _call(token: str, method: str, **params) -> dict:
    if not token or ":" not in token:
        raise ValueError("Paste the bot token from @BotFather first (it looks like 123456:ABC...).")
    try:
        r = httpx.post(_url(token, method), json=params, timeout=15)
    except httpx.HTTPError as e:
        raise ValueError(f"Can't reach Telegram ({type(e).__name__}). Check the internet connection.")
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if not data.get("ok"):
        desc = data.get("description") or f"HTTP {r.status_code}"
        if r.status_code == 401:
            desc = "Telegram doesn't know that token. Copy it again from @BotFather."
        elif r.status_code in (400, 403) and "chat" in desc.lower():
            desc = f"{desc}. Send your bot a message in Telegram first, then press Find my chat."
        raise ValueError(desc)
    return data["result"]


def send_now(text: str, s: dict | None = None, html: bool = False) -> dict:
    s = s or load()
    if not str(s.get("telegram_chat_id") or "").strip():
        raise ValueError("No chat yet: send your bot a message in Telegram, then press Find my chat.")
    extra = {"parse_mode": "HTML"} if html else {}
    kb = keyboard(s)
    if kb:
        extra["reply_markup"] = kb
    _call(s.get("telegram_token", ""), "sendMessage", chat_id=str(s["telegram_chat_id"]).strip(), text=text,
          disable_web_page_preview=True, **extra)
    _last.update(error="", sent=_last["sent"] + 1)
    return {"ok": True}


def detect() -> dict:
    """Find your chat id from the newest message sent to the bot, save it and say hello."""
    s = load()
    updates = _call(s.get("telegram_token", ""), "getUpdates", timeout=0, allowed_updates=["message"])
    chats = [u["message"]["chat"] for u in updates if u.get("message", {}).get("chat")]
    if not chats:
        raise ValueError("No messages found. Open your bot in Telegram, press Start or send it \"hi\", then try again.")
    chat = chats[-1]
    name = chat.get("first_name") or chat.get("title") or chat.get("username") or "you"
    s = save({"telegram_chat_id": str(chat["id"])})
    send_now(f"✅ Trading Bot alerts are connected. Hi {name}!", s)
    return {"ok": True, "chat_id": str(chat["id"]), "name": name}


def test() -> dict:
    return send_now("🔔 Test alert from Trading Bot: alerts reach your phone.")


def status() -> dict:
    s = load()
    return {"enabled": bool(s.get("telegram_enabled")), "token_set": bool(s.get("telegram_token")),
            "chat_set": bool(str(s.get("telegram_chat_id") or "").strip()), "events": s.get("telegram_events"),
            "sent": _last["sent"], "error": _last["error"], "commands": commands_status()}


# ---------- event alerts ----------
CLOSE_KINDS = ("tp", "sl", "close")
# What each alert says. Settings > Phone alerts > "Make or change a command" can rewrite any of these
# (telegram_layouts); {fields} are filled in and empty ones drop out of the line.
LAYOUTS = {
    "tp": "✅ Take profit hit {money}\n{who} {symbol} {side} {lots} {at}",
    "sl": "🛑 Stop loss hit {money}\n{who} {symbol} {side} {lots} {at}",
    "close": "⏹ Trade closed {money}\n{who} {symbol} {side} {lots} {at}",
    "open": "▶️ Trade opened\n{who} {symbol} {side} {lots} {at}",
    "be": "🔒 Stop moved to break-even\n{who} {symbol} {side} {lots} {at}",
    "trail": "↗️ Trailing stop moved\n{who} {symbol} {side} {lots} {at}",
}
FIELDS = ("money", "who", "symbol", "side", "lots", "at", "price", "entry", "profit")


def layout(kind: str, s: dict | None = None) -> str:
    s = s if s is not None else load()
    return (s.get("telegram_layouts") or {}).get(kind) or LAYOUTS[kind]


def _money(p) -> str:
    return f"{'+' if p >= 0 else '-'}${abs(p):,.2f}" if p is not None else ""


def _text(ev: dict, s: dict | None = None) -> str:
    if ev["kind"] in WATCHDOG:
        icon = {"agent_restart": "🔁", "agent_failed": "⛔", "agent_stuck": "⏳", "mt5_down": "🔌", "mt5_up": "✅"}[ev["kind"]]
        return f"{icon} {ev.get('message') or ev['kind']}"
    word = {"tp": "at", "sl": "at", "close": "at", "open": "at", "be": "stop", "trail": "stop"}[ev["kind"]]
    vals = {"money": _money(ev.get("profit")), "who": {"you": "You", "bot": "Bot"}.get(ev.get("owner") or "", ""),
            "symbol": ev.get("symbol") or "", "side": (ev.get("side") or "").upper(),
            "lots": f"{ev['volume']:g} lot" if ev.get("volume") else "",
            "at": f"{word} {ev['price']}" if ev.get("price") else "", "price": ev.get("price") or "",
            "entry": ev.get("entry") or "", "profit": _money(ev.get("profit"))}
    try:
        txt = layout(ev["kind"], s).format(**vals)
    except (KeyError, IndexError, ValueError):            # a hand-edited layout with an unknown {name}: fall back
        txt = LAYOUTS[ev["kind"]].format(**vals)
    return "\n".join(" ".join(line.split()) for line in txt.split("\n")).strip()


def _esc(t) -> str:
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def summary_card(evs: list[dict], title: str | None = None) -> str:
    """One message for many closed trades (Telegram HTML): how many, gained, lost, the total, then one row per trade
    with where it started and what it made or lost."""
    n = len(evs)
    pnl = [float(e.get("profit") or 0) for e in evs]
    gain, loss = sum(p for p in pnl if p > 0), sum(p for p in pnl if p < 0)
    rows = []
    for k, e in enumerate(evs, 1):
        trade = f"{(e.get('side') or '').upper():<4} {e.get('symbol') or '':<7} {e['volume']:g}" if e.get("volume") else \
            f"{(e.get('side') or '').upper():<4} {e.get('symbol') or ''}"
        start = e.get("entry")
        rows.append(f"{k:<2} {trade:<17} {('' if start is None else f'{start:g}'):>9} {_money(e.get('profit')):>9}")
    head = f"{'#':<2} {'Trade':<17} {'Started':>9} {'Gain/loss':>9}"
    return (f"📋 <b>{_esc(title or f'{n} trades closed')}</b>\n"
            f"Gained <b>{_money(gain)}</b> · Lost <b>{_money(loss)}</b>\n"
            f"Total <b>{_money(gain + loss)}</b>\n"
            f"<pre>{_esc(head)}\n" + "\n".join(_esc(r) for r in rows) + "</pre>")


def for_event(ev: dict):
    """Queue an alert for an event from the watcher, if Telegram is on and this kind is wanted."""
    s = load()
    kind = "watchdog" if ev.get("kind") in WATCHDOG else ev.get("kind")
    if not s.get("telegram_enabled") or kind not in (s.get("telegram_events") or []):
        return
    try:
        _q.put_nowait({"kind": ev.get("kind"), "text": _text(ev, s), "ev": ev})
    except queue.Full:                                  # offline for a long time: drop the overflow
        return
    _start()


def _send(item: dict):
    for attempt in range(3):
        try:
            send_now(item["text"], html=bool(item.get("html")))
            return
        except ValueError as e:
            _last["error"] = str(e)
            if "token" in str(e).lower() or "chat" in str(e).lower():
                return                                  # setup problem: retrying won't help
            threading.Event().wait(5 * (attempt + 1))


def _gather(first: dict, s: dict) -> tuple[list[dict], list[dict]]:
    """After a trade closes, wait a few seconds for others closing with it (a close-all, several stops in one
    candle). Returns (closes, everything else that arrived meanwhile)."""
    closes, other = [first], []
    wait = max(0.0, float(s.get("telegram_batch_wait_s", 3)))
    end, cap = time.time() + wait, time.time() + wait * 4
    while True:
        left = end - time.time()
        if left <= 0:
            break
        try:
            nxt = _q.get(timeout=left)
        except queue.Empty:
            break
        if nxt.get("kind") in CLOSE_KINDS and nxt.get("ev"):
            closes.append(nxt)
            end = min(cap, time.time() + 1.0)           # still closing: give the rest a moment
        else:
            other.append(nxt)
    return closes, other


def _worker():
    while True:
        item = _q.get()
        if item.get("kind") in CLOSE_KINDS and item.get("ev"):
            s = load()
            closes, other = _gather(item, s)
            if len(closes) > int(s.get("telegram_batch_over", 3)):     # more than 3 (default): one card, not a flood
                _send({"text": summary_card([c["ev"] for c in closes]), "html": True})
                closes = []
            for it in closes + other:
                _send(it)
        else:
            _send(item)


def _start():
    global _thread
    if _thread is None or not _thread.is_alive():
        _thread = threading.Thread(target=_worker, name="telegram", daemon=True)
        _thread.start()


# ---------- commands: /prof /loss /total ----------
COMMANDS = {"/prof": "all the money earned (winning trades)", "/loss": "all the money lost (losing trades)",
            "/total": "profit and loss combined", "/commands": "every command you have and what it does",
            "/help": "this list"}
_cmd = {"thread": None, "offset": 0, "answered": 0, "last": "", "error": ""}


def money_summary() -> dict:
    """Closed-trade profit and loss per account: MT5 paper / demo / real, in account money. Open trades are not
    counted until they close."""
    from agent import ledger
    out = {"mt5": {}}
    for mode in ("paper", "demo", "real"):
        rows = [r for r in ledger.recent(100_000, mode) if r["status"] == "closed"]
        if rows:
            prof = sum(r["pnl"] for r in rows if (r["pnl"] or 0) > 0)
            loss = sum(r["pnl"] for r in rows if (r["pnl"] or 0) < 0)
            out["mt5"][mode] = {"prof": prof, "loss": loss, "total": prof + loss, "n": len(rows)}
    return out


_extra: dict[str, tuple[str, object]] = {}          # cmd -> (description, handler)


def register_command(cmd: str, description: str, handler):
    """Let another module answer a Telegram command. `handler(args: str) -> str`.

    Used by agent/fleet.py for /stop, /pause and friends, so this module never has to
    import the launcher. Registered commands override the built-ins of the same name.
    """
    _extra[cmd.lower()] = (description, handler)


def unregister_command(cmd: str):
    _extra.pop(cmd.lower(), None)


def money_text(key: str) -> str:
    m = money_summary()
    title = {"prof": "💰 Money earned", "loss": "🔻 Money lost", "total": "📊 Profit + loss combined"}[key]
    lines = [title]
    for mode, r in m["mt5"].items():
        lines.append(f"MT5 {mode}: {_money(r[key])}  ({r['n']} trades)")
    if len(lines) == 1:
        lines.append("No closed trades yet.")
    return "\n".join(lines)


def _bot_status(_args="") -> str:
    from agent import ledger
    from .jobs import jobs
    s = load()
    run = jobs.jobs["agent"].running
    opens = ledger.open_trades()
    return (f"🤖 Bot {'running' if run else 'stopped'} · {s.get('symbol')}\n"
            f"{len(opens)} trade{'s' if len(opens) != 1 else ''} open\n" + money_text("total").split("\n", 1)[-1])


def _open_trades(_args="") -> str:
    from agent import ledger
    rows = ledger.open_trades()
    if not rows:
        return "No trades open."
    return "Open trades:\n" + "\n".join(f"{r['side'].upper()} {r['symbol']} {r['lots']:g} from {r['entry']:g}" for r in rows[:20])


def _today(_args=""):
    """Today's closed trades as one card (same look as the summary of many closes)."""
    from datetime import datetime, timezone
    from agent import ledger
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = [r for r in ledger.recent(2000) if r["status"] == "closed" and str(r.get("close_utc") or "").startswith(day)]
    if not rows:
        return "No trades closed today."
    evs = [{"side": r["side"], "symbol": r["symbol"], "volume": r["lots"], "entry": r["entry"], "profit": r["pnl"]} for r in rows]
    return {"text": summary_card(evs[:40], f"Today: {len(rows)} trades closed"), "html": True}


def _start_bot(_args="") -> str:
    from . import server
    try:
        server.agent_start({})
        return "▶️ Bot started."
    except Exception as e:                              # noqa: BLE001 - HTTPException carries the reason
        return f"⚠ Couldn't start: {getattr(e, 'detail', e)}"


def _stop_bot(_args="") -> str:
    from . import server
    server.job_stop("agent")
    return "⏸ Bot stopped. Open trades keep their stops and targets."


def _flatten(args="") -> str:
    if args.strip().lower() not in ("yes", "y", "confirm"):
        return "This stops the bot and closes all its trades. Send the same command followed by yes to do it."
    from . import server
    server.kill_switch()
    return "🛑 Bot stopped and its trades closed."


# Everything a command can do. Settings > Phone alerts > "Make or change a command" builds commands from these.
ACTIONS = {
    "prof": ("all the money earned (winning trades)", lambda a="": money_text("prof")),
    "loss": ("all the money lost (losing trades)", lambda a="": money_text("loss")),
    "total": ("profit and loss combined", lambda a="": money_text("total")),
    "status": ("is the bot running, open trades, total", _bot_status),
    "open": ("the trades open right now", _open_trades),
    "today": ("today's closed trades as one card", _today),
    "start_bot": ("start the bot", _start_bot),
    "stop_bot": ("stop the bot (open trades keep their stops)", _stop_bot),
    "flatten": ("stop the bot and close its trades (asks for yes)", _flatten),
}


def custom_commands(s: dict | None = None) -> dict[str, dict]:
    s = s if s is not None else load()
    out = {}
    for c in s.get("telegram_custom_commands") or []:
        name = str(c.get("cmd") or "").strip().lower()
        if name.startswith("/") and (c.get("action") in ACTIONS or c.get("reply")):
            out[name] = c
    return out


def keyboard(s: dict | None = None) -> dict | None:
    """The buttons under the chat's text box (telegram_keyboard), three to a row."""
    s = s if s is not None else load()
    btns = [b for b in (s.get("telegram_keyboard") or []) if isinstance(b, str) and b.startswith("/")]
    if not btns:
        return None
    return {"keyboard": [[{"text": b} for b in btns[i:i + 3]] for i in range(0, len(btns), 3)],
            "resize_keyboard": True, "is_persistent": True}


def all_commands(s: dict | None = None) -> dict[str, str]:
    """Every command the chat answers right now -> what it does: built in, added by modules, and yours. Built from
    the saved settings each time, so a command made in Settings shows up at once."""
    s = s if s is not None else load()
    out = {c: d for c, d in COMMANDS.items()}
    out.update({c: d for c, (d, _) in _extra.items()})
    for c, v in custom_commands(s).items():
        out[c] = v.get("about") or (ACTIONS[v["action"]][0] if v.get("action") in ACTIONS else f'replies "{v.get("reply", "")}"')
    return out


def commands_text() -> str:
    s = load()
    mine = custom_commands(s)
    built = {c: d for c, d in all_commands(s).items() if c not in mine}
    lines = ["📖 Your commands", "", "Built in:"] + [f"{c} — {d}" for c, d in built.items()]
    lines += ["", "Made by you:"] + ([f"{c} — {d}" for c, d in all_commands(s).items() if c in mine] or
                                     ["none yet (Settings > Phone alerts > Make or change a command)"])
    kb = [b for b in (s.get("telegram_keyboard") or []) if isinstance(b, str)]
    if kb:
        lines += ["", "Buttons: " + "  ".join(kb)]
    return "\n".join(lines)


def sync_menu(s: dict | None = None) -> bool:
    """Tell Telegram the current list, so the "/" menu in the chat matches (called on start and after every change)."""
    s = s if s is not None else load()
    token = s.get("telegram_token", "")
    if not (token and ":" in token):
        return False
    cmds = [{"command": c[1:], "description": d[:256] or c} for c, d in all_commands(s).items()
            if c != "/start" and re.fullmatch(r"/[a-z0-9_]{1,32}", c)]
    try:
        _call(token, "setMyCommands", commands=cmds[:100])
        return True
    except ValueError as e:
        _cmd["error"] = f"menu: {e}"
        return False


def command_reply(text: str):
    """A reply for a command from your chat: a string, a {"text", "html"} card, or None (not a command we know)."""
    raw = (text or "").strip()
    cmd = raw.split()[0].split("@")[0].lower() if raw else ""
    args = raw[len(raw.split()[0]):].strip() if raw else ""

    if cmd in _extra:                                   # a module took this one over
        try:
            return _extra[cmd][1](args)
        except Exception as e:                          # noqa: BLE001 - never kill the poll loop
            return f"⚠ {cmd} failed: {type(e).__name__}: {e}"
    mine = custom_commands()
    if cmd in mine:                                     # one you made in Settings
        c = mine[cmd]
        if c.get("reply") and not c.get("action"):
            return str(c["reply"])
        try:
            return ACTIONS[c["action"]][1](args)
        except Exception as e:                          # noqa: BLE001
            return f"⚠ {cmd} failed: {type(e).__name__}: {e}"

    if cmd == "/commands":
        return commands_text()
    if cmd in ("/help", "/start"):
        allcmds = {**COMMANDS, **{c: d for c, (d, _) in _extra.items()},
                   **{c: v.get("about") or (ACTIONS[v["action"]][0] if v.get("action") in ACTIONS else "your own reply")
                      for c, v in mine.items()}}
        return "Commands:\n" + "\n".join(f"{c} — {d}" for c, d in allcmds.items())
    if cmd not in ("/prof", "/loss", "/total"):
        return None
    return money_text(cmd[1:])


def _commands_loop():
    while True:
        s = load()
        token, chat = s.get("telegram_token", ""), str(s.get("telegram_chat_id") or "").strip()
        if not (s.get("telegram_commands", True) and token and ":" in token and chat):
            threading.Event().wait(15)
            continue
        try:
            ups = _call(token, "getUpdates", offset=_cmd["offset"], timeout=25, allowed_updates=["message"])
            _cmd["error"] = ""
        except ValueError as e:
            _cmd["error"] = str(e)
            threading.Event().wait(20)
            continue
        for u in ups:
            _cmd["offset"] = max(_cmd["offset"], u["update_id"] + 1)
            msg = u.get("message") or {}
            if str((msg.get("chat") or {}).get("id")) != chat:
                continue                                # only you: other chats can't read your money
            reply = command_reply(msg.get("text", ""))
            if reply:
                card = reply if isinstance(reply, dict) else {"text": reply}
                extra = {"parse_mode": "HTML"} if card.get("html") else {}
                kb = keyboard(s)
                if kb:
                    extra["reply_markup"] = kb
                try:
                    _call(token, "sendMessage", chat_id=chat, text=card["text"], **extra)
                    _cmd["answered"] += 1
                    _cmd["last"] = msg.get("text", "")
                except ValueError as e:
                    _cmd["error"] = str(e)


def start_commands():
    threading.Thread(target=sync_menu, name="telegram-menu", daemon=True).start()
    if _cmd["thread"] is None or not _cmd["thread"].is_alive():
        _cmd["thread"] = threading.Thread(target=_commands_loop, name="telegram-commands", daemon=True)
        _cmd["thread"].start()


def commands_status() -> dict:
    return {"on": bool(load().get("telegram_commands", True)), "listening": bool(_cmd["thread"] and _cmd["thread"].is_alive()),
            "answered": _cmd["answered"], "last": _cmd["last"], "error": _cmd["error"], "commands": COMMANDS,
            "custom": list(custom_commands().values()), "keyboard": load().get("telegram_keyboard") or [],
            "actions": {k: d for k, (d, _) in ACTIONS.items()}}
