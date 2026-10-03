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


def test_replay_rewinds_one_week_to_an_open_market():
    from app.server import rewind_start
    day, now = 86400, 1_700_000_000
    week_ago = now - 7 * day
    times = list(range(week_ago - 3 * day, week_ago - 2 * day, 60))     # market only open 2-3 days before "a week ago"
    got = rewind_start(times, now)
    assert got is not None and abs(got - (week_ago - 2 * day)) <= 300
    on = list(range(week_ago - day, week_ago + day, 60))                # open at that moment: start right there
    assert abs(rewind_start(on, now) - week_ago) <= 60
    assert rewind_start([], now) is None and rewind_start([now], now) is None


def test_replay_has_no_speed_control(client):
    from app import server
    r = client.post("/api/replay/control", json={"speed": 500, "paused": True}).json()
    assert r.get("paused") is True and r.get("speed") != 500
    assert json.loads(server.REPLAY_CONTROL.read_text()).get("speed") != 500
