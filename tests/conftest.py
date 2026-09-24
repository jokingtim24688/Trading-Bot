"""Test set-up: a fake MetaTrader5 package and a throw-away data folder for every test.

Nothing here touches your real data/ folder, logs, skills or a real MT5 terminal. Run with `python -m pytest`.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).parent / "fake_mt5"))     # before the real MetaTrader5 (Windows only)
sys.path.insert(0, str(ROOT))

import MetaTrader5 as fake_mt5  # noqa: E402


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    """Point every file the app and the agent write at tmp_path, and reset all in-memory state."""
    from agent import learn, ledger, news, progression
    from app import (backup, brain, jobs, manual, memory, mt5_service, review, server, settings, sounds, tools, watch,
                     watchdog)
    data = tmp_path / "data"
    data.mkdir()
    for mod, name, value in [
            (settings, "DATA", data), (settings, "PATH", data / "settings.json"), (settings, "BACKUPS", data / "backups"),
            (backup, "DATA", data), (backup, "ROOT", tmp_path), (watchdog, "DATA", data),
            (memory, "FILE", data / "hermes_memory.json"), (memory, "OLD_DB", data / "memory.db"),
            (review, "DIR", data / "reviews"), (sounds, "DIR", data / "sounds"),
            (sounds, "INDEX", data / "sounds" / "index.json"), (tools, "NOTES", data / "notes"),
            (watch, "RULES_FILE", data / "manual_auto.json"), (watch, "LEVELS_FILE", data / "closed_levels.json"),
            (ledger, "DB", data / "trades.db"), (learn, "RULES_PATH", data / "learned_rules.json"),
            (learn, "MISTAKES_PATH", data / "mistakes.json"), (learn, "SKILL_DIR", tmp_path / "skill"),
            (progression, "PATH", data / "progression.json"), (news, "CACHE", data / "news_calendar.json"),
            (server, "REPLAY_CONTROL", data / "replay_control.json"), (server, "REPLAY_STATE", data / "replay_state.json"),
            (server, "BACKTEST_REPORT", data / "backtest.json"), (server, "BACKTEST_STATE", data / "backtest_state.json"),
            (brain, "GATEWAY_LOG", tmp_path / "hermes_gateway.log")]:
        monkeypatch.setattr(mod, name, value)
    for job in jobs.jobs.jobs.values():
        monkeypatch.setattr(job, "log_path", tmp_path / f"{job.name}.log")
    monkeypatch.setattr(news, "ensure_fresh", lambda: None)          # never go online from a test
    fake_mt5.reset()
    watch._events.clear()
    watch._seen_deals.clear()
    monkeypatch.setattr(watch, "_next_id", 1)
    monkeypatch.setattr(watch, "_known", None)
    monkeypatch.setattr(watch, "_rules", None)
    monkeypatch.setattr(watch, "_closed_levels", None)
    manual._seen.clear()
    monkeypatch.setattr(memory, "_mem", None)
    mt5_service._sync["t"] = 0.0
    yield data
    for job in jobs.jobs.jobs.values():
        job.stop()


@pytest.fixture
def mt5():
    return fake_mt5


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app import server
    return TestClient(server.app)                                    # no `with`: background threads stay off
