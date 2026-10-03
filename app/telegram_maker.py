"""The Telegram command maker (Settings > Phone alerts): say what you want in plain words, see what it understood and a
preview, then save. It runs on this PC with no AI model: it recognises the bot's actions, chat buttons, alert texts
and the summary card, and asks again when it can't tell what you meant.

    parse("make /pnl show my total and add it as a button")
    -> {"ok": True, "changes": [{"type": "command", "cmd": "/pnl", "action": "total"},
                                {"type": "button_add", "cmd": "/pnl"}], "said": [...], "preview": "..."}
    apply(changes) -> writes telegram_custom_commands / telegram_keyboard / telegram_layouts / telegram_batch_over
"""
import re

from . import settings, telegram

BUILTIN = {"/help", "/start", "/prof", "/loss", "/total"}
# which words point at which action (first match wins, so the specific ones come first)
ACTION_WORDS = [
    ("flatten", r"close (all|every|everything|my trades|them)|flatten|panic|kill"),
    ("start_bot", r"\bstart(s|ing)? (the )?bot\b|\bturn (the )?bot on\b|\bresume\b|\bbegin trading\b"),
    ("stop_bot", r"\bstop(s|ping)? (the )?bot\b|\bpause\b|\bturn (the )?bot off\b|\bstop trading\b"),
    ("today", r"\btoday\b|\bthis day\b|\bdaily\b"),
    ("open", r"\bopen (trades|positions)\b|\bwhat'?s open\b|\bopen now\b|\bpositions\b"),
    ("status", r"\bstatus\b|\brunning\b|\bhow is the bot\b|\bhow'?s the bot\b|\bcheck (on )?the bot\b"),
    ("total", r"\btotal\b|\bprofit and loss\b|\bp ?& ?l\b|\bpnl\b|\bcombined\b|\bnet\b|\boverall\b"),
    ("loss", r"\blost\b|\blosing\b|\blosses\b|\bloss\b"),
    ("prof", r"\bearned\b|\bwinning\b|\bwins\b|\bprofits?\b|\bgains?\b|\bmade\b"),
]
KIND_WORDS = [("tp", r"take ?profit|\btp\b"), ("sl", r"stop ?loss|\bsl\b"), ("be", r"break ?-?even"),
              ("trail", r"trailing"), ("open", r"\bopen(ed|s)?\b|\bentr(y|ies)\b|\bbought\b"),
              ("close", r"\bclos(e|ed|es|ing)\b")]
KIND_NAMES = {"tp": "take profit", "sl": "stop loss", "be": "break-even", "trail": "trailing stop", "open": "trade opened",
              "close": "trade closed"}
SAMPLE = {"kind": "tp", "owner": "bot", "symbol": "XAUUSD", "side": "buy", "volume": 0.01, "price": 2662.4,
          "entry": 2650.1, "profit": 12.3}


def _cmds(t: str) -> list[str]:
    found = re.findall(r"(?<![\w/])/([a-zA-Z][a-zA-Z0-9_]{0,31})", t)
    named = re.findall(r"\b(?:command|button)s? (?:called|named) ['\"]?/?([a-zA-Z][a-zA-Z0-9_]{0,31})", t, re.I)
    out = []
    for c in found + named:
        c = "/" + c.lower()
        if c not in out:
            out.append(c)
    return out


def _quoted(t: str) -> str | None:
    m = re.search(r"[\"“']([^\"”']{1,400})[\"”']", t)
    return m.group(1).strip() if m else None


def _action(t: str) -> str | None:
    low = t.lower()
    for name, pat in ACTION_WORDS:
        if re.search(pat, low):
            return name
    return None


def _kinds(t: str) -> list[str]:
    low = t.lower()
    return [k for k, pat in KIND_WORDS if re.search(pat, low)]


def _layout_text(t: str, kind: str) -> str | None:
    q = _quoted(t)
    if q:                                       # plain words for the fields people use: "profit", "symbol", ...
        for w, f in (("profit", "money"), ("money", "money"), ("symbol", "symbol"), ("side", "side"), ("lots", "lots"),
                     ("price", "price"), ("starting price", "entry"), ("start price", "entry"), ("entry", "entry")):
            q = re.sub(r"\[" + w + r"\]", "{" + f + "}", q, flags=re.I)
        return q
    low = t.lower()
    base = telegram.layout(kind)
    if re.search(r"start(ing)? (price|value)|entry|where it (started|opened)", low) and "{entry}" not in base:
        return base + " (started {entry})"
    if re.search(r"\b(reset|default|original)\b", low):
        return ""
    return None


def parse(text: str) -> dict:
    t = (text or "").strip()
    if not t:
        return {"ok": False, "error": "Type what you want, e.g. \"make /pnl show my total\"."}
    low = t.lower()
    changes, said = [], []
    removing = bool(re.search(r"\b(remove|delete|get rid of|drop|take away)\b", low))
    cmds = _cmds(t)

    # the summary card: "more than 5 trades", "5 or more trades close"
    m = re.search(r"(more than|over|above)\s+(\d+)\s+trades?", low) or re.search(r"(\d+)\s+or more\s+trades?", low)
    if m and re.search(r"summar|card|together|one message|at once|clos", low):
        n = int(m.group(2)) if m.lastindex == 2 else int(m.group(1)) - 1
        n = max(1, min(50, n))
        changes.append({"type": "batch", "over": n})
        said.append(f"When more than {n} trades close together, send one summary card instead of a message each.")

    # alert texts: "change the take profit message to '...'"
    if re.search(r"\b(message|alert|notification|text)\b", low) and not cmds:
        for k in _kinds(t) or []:
            new = _layout_text(t, k)
            if new is None:
                continue
            if new == "":
                changes.append({"type": "layout", "kind": k, "text": ""})
                said.append(f"Put the {KIND_NAMES[k]} alert back to how it was.")
            else:
                changes.append({"type": "layout", "kind": k, "text": new})
                said.append(f"The {KIND_NAMES[k]} alert will say: {new}")

    # buttons under the chat's text box
    if re.search(r"\b(button|buttons|keyboard)\b", low):
        for c in cmds:
            if removing:
                changes.append({"type": "button_remove", "cmd": c})
                said.append(f"Remove the {c} button.")
            else:
                changes.append({"type": "button_add", "cmd": c})
                said.append(f"Add a {c} button under the chat.")

    # commands: a name that only comes after the word "button(s)" is a button, not a new command
    mine = telegram.custom_commands()
    bpos = re.search(r"\b(button|buttons|keyboard)\b", low)
    for c in cmds:
        if bpos and low.find(c) > bpos.start():
            continue
        if removing:
            if not re.search(r"\b(button|buttons|keyboard)\b", low) or re.search(r"\bcommand", low):
                if c in mine:
                    changes.append({"type": "remove_command", "cmd": c})
                    said.append(f"Delete the command {c}.")
            continue
        reply = _quoted(t) if re.search(r"\b(reply|replies|say|says|answer|answers|respond|responds|send back)\b", low) else None
        act = None if reply else _action(re.sub(r"/\w+", " ", t))
        if c in BUILTIN and (act or reply):
            said.append(f"{c} is built in, so it stays as it is. Pick another name.")
            continue
        if act:
            changes.append({"type": "command", "cmd": c, "action": act})
            said.append(f"New command {c}: {telegram.ACTIONS[act][0]}.")
        elif reply:
            changes.append({"type": "command", "cmd": c, "reply": reply})
            said.append(f"New command {c}: replies \"{reply}\".")
        elif not any(ch.get("cmd") == c for ch in changes):
            said.append(f"I didn't catch what {c} should do. It can: " +
                        ", ".join(d for d, _ in telegram.ACTIONS.values()) + ", or reply with your own words in quotes.")

    # a button needs a command behind it: /today, /status, /open ... are made for you
    made = {ch["cmd"] for ch in changes if ch["type"] == "command"}
    for ch in [x for x in changes if x["type"] == "button_add"]:
        c = ch["cmd"]
        if c in BUILTIN or c in mine or c in made:
            continue
        if c[1:] in telegram.ACTIONS:
            changes.append({"type": "command", "cmd": c, "action": c[1:]})
            made.add(c)
            said.append(f"New command {c}: {telegram.ACTIONS[c[1:]][0]}.")
        else:
            said.append(f"There's no {c} command yet, so its button won't answer. Say what {c} should do too.")

    if not changes:
        return {"ok": False, "said": said, "error": " ".join(said) or
                "I didn't understand that. Try: \"make /pnl show my total\", \"add buttons for /status and /today\", "
                "\"change the take profit message to '🎉 [profit] on [symbol]'\" or \"send a summary when more than 5 "
                "trades close\"."}
    return {"ok": True, "changes": changes, "said": said, "preview": preview(changes)}


def preview(changes: list[dict]) -> str:
    """What the chat would look like after these changes (plain text; the card is shown as text)."""
    lines = []
    for ch in changes:
        if ch["type"] == "command":
            if ch.get("action"):
                r = {"prof": "💰 Money earned\nMT5 paper: +$12.30  (1 trades)",
                     "loss": "🔻 Money lost\nMT5 paper: -$4.50  (1 trades)",
                     "total": "📊 Profit + loss combined\nMT5 paper: +$7.80  (2 trades)",
                     "status": "🤖 Bot running · XAUUSD\n1 trade open\nMT5 paper: +$7.80  (2 trades)",
                     "open": "Open trades:\nBUY XAUUSD 0.01 from 2650.1", "today": "📋 Today: 2 trades closed …",
                     "start_bot": "▶️ Bot started.", "stop_bot": "⏸ Bot stopped. Open trades keep their stops and targets.",
                     "flatten": "This stops the bot and closes all its trades. Send the same command followed by yes to do it."
                     }[ch["action"]]
            else:
                r = ch["reply"]
            lines.append(f"You: {ch['cmd']}\nBot: {r}")
        elif ch["type"] == "layout" and ch["text"]:
            ev = {**SAMPLE, "kind": ch["kind"]}
            s = {"telegram_layouts": {ch["kind"]: ch["text"]}}
            lines.append("Alert: " + telegram._text(ev, s))
        elif ch["type"] == "batch":
            evs = [{**SAMPLE, "entry": 2650.1 + i, "profit": p} for i, p in enumerate((12.3, -4.5, 8.0, -1.2, 3.1)[:ch["over"] + 1])]
            card = telegram.summary_card(evs)
            lines.append(re.sub(r"</?(b|pre)>", "", card).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&"))
    btn = [c["cmd"] for c in changes if c["type"] == "button_add"]
    if btn:
        lines.append("Buttons: " + "  ".join(f"[{b}]" for b in btn))
    return "\n\n".join(lines)


def apply(changes: list[dict]) -> dict:
    s = settings.load()
    cmds = [c for c in (s.get("telegram_custom_commands") or []) if isinstance(c, dict)]
    kb = [b for b in (s.get("telegram_keyboard") or []) if isinstance(b, str)]
    lay = dict(s.get("telegram_layouts") or {})
    upd = {}
    for ch in changes or []:
        typ, cmd = ch.get("type"), str(ch.get("cmd") or "").lower()
        if typ == "command" and re.fullmatch(r"/[a-z][a-z0-9_]{0,31}", cmd) and cmd not in BUILTIN:
            entry = {"cmd": cmd}
            if ch.get("action") in telegram.ACTIONS:
                entry["action"] = ch["action"]
            elif str(ch.get("reply") or "").strip():
                entry["reply"] = str(ch["reply"]).strip()[:1000]
            else:
                continue
            cmds = [c for c in cmds if str(c.get("cmd")).lower() != cmd] + [entry]
        elif typ == "remove_command":
            cmds = [c for c in cmds if str(c.get("cmd")).lower() != cmd]
            kb = [b for b in kb if b.lower() != cmd]
        elif typ == "button_add" and cmd.startswith("/") and cmd not in kb:
            kb.append(cmd)
        elif typ == "button_remove":
            kb = [b for b in kb if b.lower() != cmd]
        elif typ == "layout" and ch.get("kind") in telegram.LAYOUTS:
            if ch.get("text"):
                lay[ch["kind"]] = str(ch["text"])[:600]
            else:
                lay.pop(ch["kind"], None)
        elif typ == "batch":
            upd["telegram_batch_over"] = max(1, min(50, int(ch.get("over") or 3)))
    upd.update(telegram_custom_commands=cmds, telegram_keyboard=kb[:12], telegram_layouts=lay)
    settings.save(upd)
    return telegram.commands_status()
