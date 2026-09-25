"""Bot tab live card: no stop loss anywhere, co-pilot approve/skip, mode and symbol switching, plain-words card."""
import json
import time

import pytest
from fastapi.testclient import TestClient

from agent import ledger, livecard
from app import botlive, jobs, mt5_service, server, settings


class _Alive:
    """A stand-in process that looks like a running agent."""
    def poll(self):
        return None

    def terminate(self):
        pass

    def wait(self, timeout=None):
        return 0


@pytest.fixture
def running(monkeypatch):
    monkeypatch.setattr(jobs.jobs.jobs["agent"], "proc", _Alive())


def _has_sl(obj):
    if isinstance(obj, dict):
        return any(k in ("sl", "sl0", "stop", "stop_loss") or _has_sl(v) for k, v in obj.items())
    if isinstance(obj, list):
        return any(_has_sl(v) for v in obj)
    return False


def test_live_card_never_shows_a_stop_loss(sandbox, running):
    ledger.open_trade("paper", "XAUUSD", "buy", 0.01, 2649.0, 2640.0, 2670.0)
    prop = {"id": "1", "status": "pending", "symbol": "XAUUSD", "side": "buy", "entry": 2650.25, "tp": 2670.0,
            "sl": 2640.0, "reason": "x", "expires": time.time() + 30}
    (sandbox / "agent_status.json").write_text(json.dumps({"symbol": "XAUUSD", "proposal": prop,
                                                           "time_utc": "2026-09-25T10:00:00+00:00"}))
    (sandbox / "copilot.json").write_text(json.dumps(prop))
    r = TestClient(server.app).get("/api/bot/live").json()
    assert not _has_sl(r)
    pos = r["positions"][0]
    assert pos["entry"] == 2649.0 and pos["tp"] == 2670.0 and pos["points"] is not None
    assert 0 <= pos["progress_pct"] <= 100
    assert r["proposal"]["seconds_left"] > 0 and r["heartbeat"]["broker"]["ok"]
    assert r["points"]["open_trades"] == 1


def test_copilot_approve_writes_decision_and_rejects_stale_ids(sandbox, running):
    c = TestClient(server.app)
    assert c.post("/api/copilot/decide", json={"id": "9", "action": "approve"}).status_code == 409   # none waiting
    (sandbox / "copilot.json").write_text(json.dumps({"id": "7", "status": "pending", "expires": time.time() + 20}))
    assert c.post("/api/copilot/decide", json={"id": "6", "action": "approve"}).status_code == 409   # replaced
    assert c.post("/api/copilot/decide", json={"id": "7", "action": "maybe"}).status_code == 400
    assert c.post("/api/copilot/decide", json={"id": "7", "action": "approve"}).json()["ok"]
    assert json.loads((sandbox / "copilot_decision.json").read_text())["action"] == "approve"


def test_mode_switch_is_saved(sandbox):
    c = TestClient(server.app)
    assert c.post("/api/bot/mode", json={"mode": "copilot"}).json()["bot_mode"] == "copilot"
    assert settings.load()["bot_mode"] == "copilot"
    assert c.post("/api/bot/mode", json={"mode": "yolo"}).status_code == 400


def test_symbol_switch_needs_a_model(sandbox, monkeypatch):
    c = TestClient(server.app)
    monkeypatch.setattr(mt5_service, "model_exists", lambda s: s == "NAS100")
    assert c.post("/api/bot/symbol", json={"symbol": "AAPL"}).status_code == 400
    r = c.post("/api/bot/symbol", json={"symbol": "NAS100"}).json()
    assert r["ok"] and r["symbol"] == "NAS100" and settings.load()["symbol"] == "NAS100"


def test_card_words():
    row = {"h1_structure": 3, "slope_ema200": 0.2, "rsi14": 0.62, "ret_15": 0.001, "atr_rel": 1.0}
    pills = {p["key"]: p for p in livecard.confluence(row, "buy", True, "all checks passed")}
    assert pills["trend"]["state"] == "good" and pills["momentum"]["state"] == "good"
    assert pills["volatility"]["state"] == "good" and pills["ready"]["state"] == "good"
    assert {p["key"]: p for p in livecard.confluence(row, "sell", False, "x")}["trend"]["state"] == "bad"
    assert livecard.confidence_pct([0.01] * 90 + [0.2] * 10, 0.1) == 90
    h = livecard.headline("XAUUSD", row, "buy", "waiting for a strong setup", "", 0, None, 0.07, False)
    assert h.startswith("Scanning XAUUSD: H1 trend is bullish")
    assert "sell" in livecard.reason("sell", ["Bearish fair value gap"], row, 0.096, 0.07, 95)
