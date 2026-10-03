"""Telegram: one summary card when more than 3 trades close together, your own commands, chat buttons, layouts."""
import json
import threading
import time

from app import settings, telegram


class Sent:
    def __init__(self):
        self.msgs = []

    def post(self, url, json=None, timeout=None):
        self.msgs.append(json)

        class R:
            status_code = 200
            headers = {"content-type": "application/json"}

            @staticmethod
            def json():
                return {"ok": True, "result": {}}
        return R()


def _ev(i, profit, kind="tp"):
    return {"kind": kind, "owner": "bot", "symbol": "XAUUSD", "side": "buy", "volume": 0.01, "price": 2660 + i,
            "entry": 2650.0 + i, "profit": profit}


def _run(monkeypatch, evs, **cfg):
    sent = Sent()
    monkeypatch.setattr(telegram.httpx, "post", sent.post)
    settings.save({"telegram_enabled": True, "telegram_token": "1:A", "telegram_chat_id": "42",
                   "telegram_events": ["tp", "sl", "close", "open"], "telegram_batch_wait_s": 0.3, **cfg})
    monkeypatch.setattr(telegram, "_thread", None)
    for e in evs:
        telegram.for_event(e)
    t0 = time.time()
    while time.time() - t0 < 5 and (not telegram._q.empty() or len(sent.msgs) < 1):
        time.sleep(0.05)
    time.sleep(0.8)
    return sent.msgs


def test_more_than_three_closes_become_one_card(monkeypatch):
    msgs = _run(monkeypatch, [_ev(i, p) for i, p in enumerate((12.0, -4.5, 8.25, -1.0, 3.0))])
    assert len(msgs) == 1 and msgs[0]["parse_mode"] == "HTML"
    t = msgs[0]["text"]
    assert "5 trades closed" in t and "Gained <b>+$23.25</b>" in t and "Lost <b>-$5.50</b>" in t and "Total <b>+$17.75</b>" in t
    assert "2650" in t and "2654" in t and "-$4.50" in t               # each trade: where it started and what it made


def test_three_closes_still_go_one_by_one(monkeypatch):
    msgs = _run(monkeypatch, [_ev(i, 1.0) for i in range(3)])
    assert len(msgs) == 3 and all("parse_mode" not in m for m in msgs)


def test_custom_commands_buttons_and_layouts(monkeypatch):
    settings.save({"telegram_custom_commands": [{"cmd": "/pnl", "action": "total"}, {"cmd": "/hi", "reply": "hello!"}],
                   "telegram_keyboard": ["/status", "/pnl", "/today", "/hi"],
                   "telegram_layouts": {"tp": "🎉 {money} on {symbol} (started {entry})"}})
    assert telegram.command_reply("/hi") == "hello!"
    assert telegram.command_reply("/pnl").startswith("📊 Profit + loss combined")
    assert "/pnl" in telegram.command_reply("/help")
    kb = telegram.keyboard()
    assert kb["keyboard"] == [[{"text": "/status"}, {"text": "/pnl"}, {"text": "/today"}], [{"text": "/hi"}]]
    assert telegram._text(_ev(0, 40.0)) == "🎉 +$40.00 on XAUUSD (started 2650.0)"
    settings.save({"telegram_layouts": {"tp": "{nope}"}})                # a broken layout falls back, never crashes
    assert telegram._text(_ev(0, 40.0)).startswith("✅ Take profit hit +$40.00")
    settings.save({"telegram_custom_commands": [{"cmd": "/flat", "action": "flatten"}]})
    assert telegram.command_reply("/flat").startswith("This stops the bot")      # asks for yes first


def test_command_maker_understands_plain_words(client):
    from app import telegram_maker as tm
    r = tm.parse("make /pnl show my total and add it as a button")
    assert r["ok"] and {"type": "command", "cmd": "/pnl", "action": "total"} in r["changes"]
    assert {"type": "button_add", "cmd": "/pnl"} in r["changes"] and "You: /pnl" in r["preview"]
    assert tm.parse("make /bye stop the bot")["changes"] == [{"type": "command", "cmd": "/bye", "action": "stop_bot"}]
    assert tm.parse("make /closeall close all my trades")["changes"][0]["action"] == "flatten"
    assert tm.parse("make /gm reply 'good morning boss'")["changes"] == [{"type": "command", "cmd": "/gm", "reply": "good morning boss"}]
    lay = tm.parse("change the take profit message to '🎉 [profit] on [symbol], started at [starting price]'")
    assert lay["changes"] == [{"type": "layout", "kind": "tp", "text": "🎉 {money} on {symbol}, started at {entry}"}]
    assert "🎉 +$12.30 on XAUUSD, started at 2650.1" in lay["preview"]
    assert tm.parse("send one summary when more than 5 trades close")["changes"] == [{"type": "batch", "over": 5}]
    bad = tm.parse("make /x do a backflip")
    assert not bad["ok"] and "didn't catch what /x should do" in bad["error"]
    assert not tm.parse("make /total say hi")["ok"]                             # built-in names stay as they are
    # through the routes, then the bot answers it
    ch = client.post("/api/telegram/maker", json={"text": "make /pnl show my total and add buttons for /pnl and /today"}).json()
    st = client.post("/api/telegram/maker/apply", json={"changes": ch["changes"]}).json()
    assert st["custom"] == [{"cmd": "/pnl", "action": "total"}, {"cmd": "/today", "action": "today"}]
    assert st["keyboard"] == ["/pnl", "/today"]
    assert telegram.command_reply("/pnl").startswith("📊")
    client.post("/api/telegram/maker/apply", json={"changes": tm.parse("delete the command /pnl")["changes"]})
    assert list(telegram.custom_commands()) == ["/today"] and settings.load()["telegram_keyboard"] == ["/today"]
