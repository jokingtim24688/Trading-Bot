"""The MT5 main agent and its checkers (moved out of the old sol/agents.py; they are the Hub's cats)."""
import numpy as np


def test_main_agent_needs_every_checker():
    from agent import desk
    ok = desk.review("mt5", "XAUUSD", "BUY", 0.7, [("Confidence", True, "fine"), ("Momentum", True, "fine")])
    assert ok["final"] == "BUY"
    no = desk.review("mt5", "EURUSD", "BUY", 0.7, [("Confidence", True, "fine"), ("Reward/risk", False, "0.5 : 1")])
    assert no["final"] == "PASS" and "Reward/risk" in no["says"]
    assert {r["asset"] for r in desk.desk()["mt5"]} == {"XAUUSD", "EURUSD"}
    subs = desk.mt5_subagents("buy", 0.62, 0.6, 2.0, 4.0, np.array([5, 4, 3, 2, 1, 0.5]), "sell")
    assert [s[0] for s in subs] == ["Confidence", "Reward/risk", "Momentum", "Quiz agent"]
    assert not subs[1][1] and not subs[2][1]                   # stop bigger than target; candles against a thin edge


def test_agents_route():
    from fastapi.testclient import TestClient
    from app import server
    from agent import desk
    desk.review("mt5", "XAUUSD", "SELL", 0.66, [("Confidence", True, "66% vs 60% needed")])
    r = TestClient(server.app).get("/api/agents").json()
    assert set(r) == {"mt5"} and r["mt5"][0]["asset"] == "XAUUSD"
