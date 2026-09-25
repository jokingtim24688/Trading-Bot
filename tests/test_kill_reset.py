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
