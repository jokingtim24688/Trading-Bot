"""The 1 s watcher: break-even, trailing stop, events feed, sync throttle, watchdog."""
import os
import time

from app import jobs, manual, mt5_service, settings, watch, watchdog


def test_break_even_then_trailing(mt5, client):
    settings.save({"manual_be_points": 80})
    watch.tick()
    last = client.get("/api/events").json()["last_id"]
    o = manual.order("XAUUSD", "buy", volume=0.1, sl_points=80, tp_points=400)
    tk = o["ticket"]
    watch.tick()
    mt5.S.update(bid=2650.90, ask=2651.15)                  # +65 points: too early
    watch.tick()
    assert mt5.POS[tk].sl == 2649.45
    mt5.S.update(bid=2651.10, ask=2651.35)                  # +85: break-even = entry + 2 points
    watch.tick()
    assert mt5.POS[tk].sl == 2650.27
    client.post("/api/manual/auto", json={"ticket": tk, "trail_points": 50})
    mt5.S.update(bid=2652.00, ask=2652.25)
    watch.tick()
    assert mt5.POS[tk].sl == 2651.50
    mt5.S.update(bid=2651.60, ask=2651.85)                  # price falls back: the stop never loosens
    watch.tick()
    assert mt5.POS[tk].sl == 2651.50
    mt5.trigger(tk, mt5.DEAL_REASON_TP, 2654.25)
    watch.tick()
    kinds = [e["kind"] for e in client.get("/api/events", params={"since": last}).json()["events"]]
    assert kinds == ["open", "be", "trail", "tp"]
    assert client.get("/api/manual/auto").json()["tickets"] == {}      # closed: rule forgotten


def test_first_poll_does_not_replay_old_events(client):
    watch.add_event("tp")
    assert client.get("/api/events").json()["events"] == []
    assert client.get("/api/events", params={"since": 10 ** 6}).json()["events"] == []


def test_ledger_sync_is_throttled(monkeypatch, client):
    import agent.broker as br
    calls = []
    monkeypatch.setattr(br, "sync_ledger", lambda *a, **k: calls.append(1) or [])
    for _ in range(10):
        client.get("/api/bot/trades")
    assert len(calls) == 1
    mt5_service.mark_ledger_stale()
    client.get("/api/bot/trades")
    assert len(calls) == 2


def test_watchdog_restarts_a_crashed_bot_three_times(monkeypatch):
    seen = []
    monkeypatch.setattr(watchdog, "_alert", lambda kind, msg: seen.append(kind))
    monkeypatch.setitem(watchdog._state, "restarts", [])
    monkeypatch.setitem(watchdog._state, "gave_up", False)
    jobs.jobs.start("agent", ["-c", "import sys; print('boom'); sys.exit(3)"])
    for _ in range(40):
        time.sleep(0.25)
        watchdog.check_agent()
        if "agent_failed" in seen:
            break
    assert seen == ["agent_restart"] * 3 + ["agent_failed"]


def test_watchdog_leaves_a_clean_exit_or_your_stop_alone(monkeypatch):
    seen = []
    monkeypatch.setattr(watchdog, "_alert", lambda kind, msg: seen.append(kind))
    jobs.jobs.start("agent", ["-c", "pass"])
    jobs.jobs.jobs["agent"].proc.wait(10)
    watchdog.check_agent()
    jobs.jobs.start("agent", ["-c", "import time; time.sleep(30)"])
    jobs.jobs.stop("agent")
    watchdog.check_agent()
    assert seen == []


def test_watchdog_mt5_down_and_up(mt5, monkeypatch):
    seen = []
    monkeypatch.setattr(watchdog, "_alert", lambda kind, msg: seen.append(kind))
    for k, v in (("mt5_ok_since", None), ("mt5_bad_since", None), ("mt5_alerted", False)):
        monkeypatch.setitem(watchdog._state, k, v)
    watchdog.check_mt5(1000)
    mt5.S["connected"] = False
    watchdog.check_mt5(1010)
    watchdog.check_mt5(1080)
    mt5.S["connected"] = True
    watchdog.check_mt5(1090)
    assert seen == ["mt5_down", "mt5_up"]


def test_watchdog_stuck(mt5, monkeypatch, sandbox):
    seen = []
    monkeypatch.setattr(watchdog, "_alert", lambda kind, msg: seen.append(kind))
    monkeypatch.setitem(watchdog._state, "stuck", False)
    jobs.jobs.start("agent", ["-c", "import time; time.sleep(30)"])
    jobs.jobs.jobs["agent"].started -= 400
    status = sandbox / "agent_status.json"
    status.write_text('{"symbol": "XAUUSD"}')
    os.utime(status, (time.time() - 360,) * 2)
    watchdog.check_agent()
    assert seen == ["agent_stuck"]
