"""Sim: the Replay engine on real history at a live pace, with its own control/state files and its own ledger."""
import json


def test_sim_routes_without_history_or_model(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import server
    monkeypatch.setattr(server, "ROOT", tmp_path)                  # no history here: the Sim must refuse to start
    c = TestClient(server.app)
    r = c.post("/api/sim/start", json={})
    assert r.status_code == 400 and "history" in r.json()["detail"].lower()
    st = c.get("/api/sim/state").json()
    assert st["job_running"] is False and st["trades_open"] == [] and st["trades_closed"] == [] and st["control"]["speed"] == 1
    assert c.post("/api/sim/control", json={"paused": True, "speed": 5}).json() == {"speed": 5, "paused": True, "stop": False}
    assert json.loads(server.SIM_CONTROL.read_text())["paused"] is True


def test_sim_reads_its_own_ledger(monkeypatch):
    from agent import ledger
    from app import server
    monkeypatch.setattr(ledger, "DB", server.SIM_DB)               # write two trades the way the engine would
    a = ledger.open_trade("replay", "XAUUSD", "buy", 0.1, 2650, 2645, 2660)
    ledger.close_trade(a, 2660, "tp", 100.0)
    ledger.open_trade("replay", "XAUUSD", "sell", 0.1, 2655, 2660, 2645)
    got = server.sim_trades()
    assert [t["side"] for t in got["trades_open"]] == ["sell"] and got["trades_closed"][0]["pnl"] == 100.0
