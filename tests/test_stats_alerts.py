"""You-vs-bot stats, quiz agreement, weekly review, Telegram, news pause, backtest costs + report."""
import json
import random
import time
import types
from datetime import datetime, timedelta, timezone

import pytest

from agent import backtest, ledger, learn, news
from agent.broker import PaperBroker
from agent.risk import SymbolSpec
from app import review, settings, stats, telegram


@pytest.fixture
def bot_trades(monkeypatch):
    monkeypatch.setattr(learn, "on_mistake", lambda *a: None)
    now = int(time.time())
    for i, pnl in enumerate([20, -10, 35, -12, -8]):
        tid = ledger.open_trade("paper", "XAUUSD", "buy", 0.1, 2650, 2649, 2652, prob=0.3,
                                open_bar=now - 3600 * (i + 1) - 600)
        ledger.close_trade(tid, 2651, "tp" if pnl > 0 else "sl", pnl, close_bar=now - 3600 * (i + 1))


def test_compare_bot_numbers(bot_trades):
    b = stats.compare(30, "paper")["bot"]
    assert (b["trades"], b["wins"], b["net"], b["profit_factor"], b["avg_hold_min"]) == (5, 2, 25.0, 1.83, 10.0)
    assert b["curve"][-1]["cum"] == 25 and sum(h["trades"] for h in b["by_hour"]) == 5
    assert stats.compare(30, "live")["bot"]["trades"] == 0


def test_quiz_agreement_verdict(monkeypatch):
    monkeypatch.setattr(learn, "on_mistake", lambda *a: None)
    random.seed(1)
    now = int(time.time())
    for i in range(120):
        side = random.choice(["buy", "sell"])
        q = random.choice([side, side, "wait", None])
        pnl = random.gauss(4 if q == side else -3, 10)
        tid = ledger.open_trade("replay", "XAUUSD", side, 0.1, 2650, 2649, 2652, open_bar=now - 99999, quiz=q)
        ledger.close_trade(tid, 2651, "tp" if pnl > 0 else "sl", pnl, close_bar=now - i * 60)
    r = stats.quiz_agreement(0, "all")
    assert r["agree"]["trades"] + r["disagree"]["trades"] + r["none"]["trades"] == 120
    assert r["verdict"].startswith("The quiz agent helps")
    assert stats.quiz_agreement(0, "paper")["verdict"].startswith("Not enough")


def test_weekly_review(bot_trades, client):
    week = time.strftime("%G-W%V")
    rv = client.get("/api/review/weekly", params={"week": week}).json()
    assert rv["source"] == "rules" and rv["went_well"] and rv["fix"] and rv["numbers"]["bot"]["trades"] >= 1
    assert week in client.get("/api/review/weeks").json()
    assert client.get("/api/review/weekly", params={"week": "nope"}).status_code == 400
    assert review.week_bounds("2026-W39")[1].date().isoformat() == "2026-09-21"


class FakeTelegram:
    def __init__(self):
        self.sent = []

    def post(self, url, json=None, timeout=None):
        token, method = url.split("/bot", 1)[1].split("/")
        if token != "123:ABC":
            return types.SimpleNamespace(status_code=401, headers={"content-type": "application/json"},
                                         json=lambda: {"ok": False, "description": "Unauthorized"})
        if method == "getUpdates":
            body = {"ok": True, "result": [{"message": {"chat": {"id": 42, "first_name": "Tim"}}}]}
        else:
            self.sent.append(json["text"])
            body = {"ok": True, "result": {}}
        return types.SimpleNamespace(status_code=200, headers={"content-type": "application/json"}, json=lambda: body)


def test_telegram_setup_and_alerts(monkeypatch, client):
    fake = FakeTelegram()
    monkeypatch.setattr(telegram.httpx, "post", fake.post)
    settings.save({"telegram_token": "999:bad"})
    assert "token" in client.post("/api/telegram/detect").json()["error"]
    settings.save({"telegram_token": "123:ABC"})
    assert client.post("/api/telegram/detect").json() == {"ok": True, "chat_id": "42", "name": "Tim"}
    assert client.post("/api/telegram/test").json() == {"ok": True}
    assert telegram._text({"kind": "tp", "owner": "you", "profit": 40.0, "symbol": "XAUUSD", "side": "buy",
                           "volume": 0.1, "price": 2654.25}) == "✅ Take profit hit +$40.00\nYou XAUUSD BUY 0.1 lot at 2654.25"
    assert telegram._text({"kind": "mt5_down", "message": "MT5 is closed"}) == "🔌 MT5 is closed"
    telegram.for_event({"kind": "tp", "profit": 1.0})          # off: nothing queued
    assert telegram._q.empty()


def test_news_pause(sandbox):
    now = datetime.now(timezone.utc)
    feed = [{"title": "CPI m/m", "country": "USD", "date": (now + timedelta(minutes=10)).isoformat(), "impact": "High"},
            {"title": "ECB", "country": "EUR", "date": (now + timedelta(minutes=5)).isoformat(), "impact": "High"}]
    news.CACHE.write_text(json.dumps({"fetched": int(time.time()), "events": news._parse(feed)}))
    assert "CPI" in news.pause_reason(None, 15, 15)
    assert news.pause_reason(now + timedelta(minutes=30), 15, 15) is None
    assert news.pause_reason(None, 0, 0) is None
    assert "ECB" in news.pause_reason(None, 15, 15, ("EUR",))


def test_backtest_costs_and_report(tmp_path):
    spec = SymbolSpec(point=0.01, tick_size=0.01, tick_value=1.0, volume_min=0.01, volume_step=0.01, volume_max=100)
    tick = types.SimpleNamespace(bid=2650.0, ask=2650.25)
    b = PaperBroker(10000, spec, "XAUUSD", lambda: tick, mode="replay")
    b.commission_per_lot, b.slippage_px = 7.0, 0.10
    b.open("buy", 1.0, 2650.25, 2649.45, 2651.85)
    x = b.on_bar({"open": 2650, "high": 2650.1, "low": 2649.4, "close": 2649.5}, 0.25, 0)[0]
    assert round(x["pnl"], 2) == -107.0                          # -80 move, -20 slippage, -7 commission
    b.open("sell", 1.0, 2650.0, 2650.8, 2648.4)
    x = b.on_bar({"open": 2649, "high": 2649.2, "low": 2648.0, "close": 2648.3}, 0.25, 0)[0]
    assert round(x["pnl"], 2) == 143.0                           # take profit is a limit: no slippage on the exit
    args = types.SimpleNamespace(balance=10000, symbol="XAUUSD", threshold=0.15, commission=7, slippage=10)
    r = backtest.write_report(tmp_path / "bt.json", args, "2024-10-01", "2024-10-10")
    assert r["metrics"]["trades"] == 2 and not r["passed"] and (tmp_path / "bt.md").exists()
