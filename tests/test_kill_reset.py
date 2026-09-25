"""Hold to flatten = reset the bot: leftover paper trades closed, status card cleared; the slider drives the agent."""
from fastapi.testclient import TestClient

from agent import ledger
from app import server, settings


def test_flatten_closes_leftover_paper_trades_and_clears_status(sandbox):
    tid = ledger.open_trade("paper", "XAUUSD", "buy", 0.01, 2000.0, 1990.0, 2020.0)
    (sandbox / "agent_status.json").write_text("{}")
    r = TestClient(server.app).post("/api/kill").json()
    assert r["reset"] and r["paper_closed"] == [tid]
    assert ledger.get(tid)["status"] == "closed" and ledger.get(tid)["exit_reason"] == "kill"
    assert not ledger.open_trades() and not (sandbox / "agent_status.json").exists()


def test_agent_gets_settings_path_for_live_threshold():
    args = server.agent_args(settings.load(), "paper")
    assert args[args.index("--settings") + 1] == str(settings.PATH)


def test_trading_hours_default_all_day_and_wrap():
    from datetime import datetime

    from agent.config import RiskConfig
    from agent.risk import RiskGate

    def ok(start, end, hour):
        g = RiskGate(RiskConfig(session_start_hour=start, session_end_hour=end, rollover_blackout=(0, 0)))
        return g.check(datetime(2026, 9, 25, hour, 5), 10000, 0.25, 0.25, 2.0)[0]
    assert all(ok(0, 24, h) for h in range(24))                       # default: every hour
    assert ok(9, 22, 10) and not ok(9, 22, 7)
    assert ok(22, 6, 23) and ok(22, 6, 3) and not ok(22, 6, 12)      # a window that wraps midnight
    assert "trading hours" in RiskGate(RiskConfig(session_start_hour=9, session_end_hour=22)).check(
        datetime(2026, 9, 25, 7, 5), 10000, 0.25, 0.25, 2.0)[1]


def test_hours_setting_reaches_agent_and_is_clamped():
    s = {**settings.load(), "trade_hours_start": 9, "trade_hours_end": 99}
    args = server.agent_args(s, "paper")
    assert args[args.index("--hours") + 1] == "9-24"
