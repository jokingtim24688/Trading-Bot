"""Trade alerts on your phone through your own Telegram bot.

Set up once: in Telegram, talk to @BotFather, send /newbot and copy the token it gives you into Settings (telegram_token).
Then send your new bot any message (e.g. "hi") and press "Find my chat" (`POST /api/telegram/detect`), which reads
that message to learn your chat id. `POST /api/telegram/test` sends a test message.

Which events are sent: `telegram_events` (default tp, sl, open, close; also possible: be, trail). Messages go out from a
background queue, so a slow or offline connection never holds up trading. Only this PC talks to api.telegram.org; the
token stays in data/settings.json.
"""
import queue
import threading

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


def send_now(text: str, s: dict | None = None) -> dict:
    s = s or load()
    if not str(s.get("telegram_chat_id") or "").strip():
        raise ValueError("No chat yet: send your bot a message in Telegram, then press Find my chat.")
    _call(s.get("telegram_token", ""), "sendMessage", chat_id=str(s["telegram_chat_id"]).strip(), text=text,
          disable_web_page_preview=True)
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
def _text(ev: dict) -> str:
    if ev["kind"] in WATCHDOG:
        icon = {"agent_restart": "🔁", "agent_failed": "⛔", "agent_stuck": "⏳", "mt5_down": "🔌", "mt5_up": "✅"}[ev["kind"]]
        return f"{icon} {ev.get('message') or ev['kind']}"
    who = {"you": "You", "bot": "Bot", "hermes": "Hermes"}.get(ev.get("owner") or "", "")
    side = (ev.get("side") or "").upper()
    sym, vol = ev.get("symbol") or "", f"{ev['volume']:g} lot" if ev.get("volume") else ""
    p = ev.get("profit")
    money = f"{'+' if p >= 0 else '-'}${abs(p):,.2f}" if p is not None else ""
    head = {"tp": f"✅ Take profit hit {money}", "sl": f"🛑 Stop loss hit {money}", "close": f"⏹ Trade closed {money}",
            "open": "▶️ Trade opened", "be": "🔒 Stop moved to break-even", "trail": "↗️ Trailing stop moved"}[ev["kind"]]
    price = {"tp": "at", "sl": "at", "close": "at", "open": "at", "be": "stop", "trail": "stop"}[ev["kind"]]
    body = " ".join(x for x in (who, sym, side, vol, f"{price} {ev['price']}" if ev.get("price") else "") if x)
    return f"{head.strip()}\n{body}"


def for_event(ev: dict):
    """Queue an alert for an event from the watcher, if Telegram is on and this kind is wanted."""
    s = load()
    kind = "watchdog" if ev.get("kind") in WATCHDOG else ev.get("kind")
    if not s.get("telegram_enabled") or kind not in (s.get("telegram_events") or []):
        return
    try:
        _q.put_nowait(_text(ev))
    except queue.Full:                                  # offline for a long time: drop the oldest-style overflow
        return
    _start()


def _worker():
    while True:
        text = _q.get()
        for attempt in range(3):
            try:
                send_now(text)
                break
            except ValueError as e:
                _last["error"] = str(e)
                if "token" in str(e).lower() or "chat" in str(e).lower():
                    break                               # setup problem: retrying won't help
                threading.Event().wait(5 * (attempt + 1))


def _start():
    global _thread
    if _thread is None or not _thread.is_alive():
        _thread = threading.Thread(target=_worker, name="telegram", daemon=True)
        _thread.start()


def notify_text(text: str, kind: str = "close"):
    """Queue a ready-made alert (the Solana bot uses this) under one of the usual event kinds."""
    s = load()
    if not s.get("telegram_enabled") or kind not in (s.get("telegram_events") or []):
        return
    try:
        _q.put_nowait(text)
    except queue.Full:
        return
    _start()


# ---------- commands: /prof /loss /total ----------
COMMANDS = {"/prof": "all the money earned (winning trades)", "/loss": "all the money lost (losing trades)",
            "/total": "profit and loss combined", "/help": "this list"}
_cmd = {"thread": None, "offset": 0, "answered": 0, "last": "", "error": ""}


def money_summary() -> dict:
    """Closed-trade profit and loss per account: MT5 (paper / demo / real, in account money) and Solana (paper / live,
    in SOL). Open trades are not counted until they close."""
    from agent import ledger
    out = {"mt5": {}, "sol": {}}
    for mode in ("paper", "demo", "real"):
        rows = [r for r in ledger.recent(100_000, mode) if r["status"] == "closed"]
        if rows:
            prof = sum(r["pnl"] for r in rows if (r["pnl"] or 0) > 0)
            loss = sum(r["pnl"] for r in rows if (r["pnl"] or 0) < 0)
            out["mt5"][mode] = {"prof": prof, "loss": loss, "total": prof + loss, "n": len(rows)}
    try:
        from sol import store
        for mode in ("paper", "live"):
            r = store.realized(mode)
            if r["n"]:
                out["sol"][mode] = {"prof": r["prof"], "loss": r["loss"], "total": r["prof"] + r["loss"], "n": r["n"]}
    except Exception:                                   # noqa: BLE001 - no Solana data yet
        pass
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


def command_reply(text: str) -> str | None:
    raw = (text or "").strip()
    cmd = raw.split()[0].split("@")[0].lower() if raw else ""
    args = raw[len(raw.split()[0]):].strip() if raw else ""

    if cmd in _extra:                                   # a module took this one over
        try:
            return _extra[cmd][1](args)
        except Exception as e:                          # noqa: BLE001 - never kill the poll loop
            return f"⚠ {cmd} failed: {type(e).__name__}: {e}"

    if cmd in ("/help", "/start"):
        allcmds = {**COMMANDS, **{c: d for c, (d, _) in _extra.items()}}
        return "Commands:\n" + "\n".join(f"{c} — {d}" for c, d in allcmds.items())
    if cmd not in ("/prof", "/loss", "/total"):
        return None
    key = cmd[1:]
    m = money_summary()
    title = {"prof": "💰 Money earned", "loss": "🔻 Money lost", "total": "📊 Profit + loss combined"}[key]
    lines = [title]
    usd = lambda v: f"{'+' if v >= 0 else '-'}${abs(v):,.2f}"
    sol = lambda v: f"{'+' if v >= 0 else '-'}{abs(v):.4f} SOL"
    for mode, r in m["mt5"].items():
        lines.append(f"MT5 {mode}: {usd(r[key])}  ({r['n']} trades)")
    for mode, r in m["sol"].items():
        lines.append(f"Solana {mode}: {sol(r[key])}  ({r['n']} trades)")
    if len(lines) == 1:
        lines.append("No closed trades yet.")
    return "\n".join(lines)


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
                try:
                    _call(token, "sendMessage", chat_id=chat, text=reply)
                    _cmd["answered"] += 1
                    _cmd["last"] = msg.get("text", "")
                except ValueError as e:
                    _cmd["error"] = str(e)


def start_commands():
    if _cmd["thread"] is None or not _cmd["thread"].is_alive():
        _cmd["thread"] = threading.Thread(target=_commands_loop, name="telegram-commands", daemon=True)
        _cmd["thread"].start()


def commands_status() -> dict:
    return {"on": bool(load().get("telegram_commands", True)), "listening": bool(_cmd["thread"] and _cmd["thread"].is_alive()),
            "answered": _cmd["answered"], "last": _cmd["last"], "error": _cmd["error"], "commands": COMMANDS}
