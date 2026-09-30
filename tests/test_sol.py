"""Solana trenching bot: rug filter, instant debate, main agents + subagents, Telegram commands, question creators,
the model crew (split to train, merged after) and the routes. Everything writes under the test's temp data folder."""
import time

import numpy as np
import pytest

SAFE = {"mint": "MINTSAFE", "symbol": "SAFE", "price_usd": 0.001, "liq_usd": 40000, "age_min": 12, "buys_5m": 180,
        "sells_5m": 60, "vol_5m": 20000, "chg_5m": 12, "mint_authority": "", "freeze_authority": "", "lp_locked_pct": 100,
        "top10_pct": 18, "dev_pct": 1}


def test_rug_filter_six_rules_and_fails_closed():
    from sol import rug
    assert rug.check(SAFE) == {"passed": True, "why": []}
    for key, bad in (("mint_authority", "Dev111"), ("freeze_authority", "Dev111"), ("lp_locked_pct", 40),
                     ("top10_pct", 55), ("liq_usd", 900), ("dev_pct", 12)):
        r = rug.check({**SAFE, key: bad})
        assert not r["passed"] and len(r["why"]) == 1, key
    r = rug.check({"mint": "X", "liq_usd": 50000})              # nothing checkable: every unknown rule fails
    assert not r["passed"] and len(r["why"]) == 5


def test_debate_is_bounded_and_immediate():
    from sol import debate
    d = debate.run({"xgb": 0.95, "lgbm": 0.30, "rf": 0.90, "cat": 0.40, "bot": 0.7})
    assert len(d["rounds"]) <= debate.MAX_ROUNDS + 1           # opening + at most MAX_ROUNDS, never a loop
    assert d["rounds"][0]["n"] == 0 and d["consensus"]["rounds"] == len(d["rounds"]) - 1
    assert d["ms"] < 5 and d["bot"] == 0.7
    agree = debate.run({"xgb": 0.91, "lgbm": 0.9, "rf": 0.93})
    assert agree["consensus"]["verdict"] == "BUY" and agree["consensus"]["agreed"] and len(agree["rounds"]) == 1
    assert agree["consensus"]["compromise"]["size_sol"] > 0
    floor = debate.run({"xgb": 0.99, "lgbm": 0.99, "rf": 0.2})
    assert floor["consensus"]["verdict"] == "PASS"             # one model below the floor after the talk: no trade
    t0 = time.perf_counter()
    for _ in range(1000):
        debate.run({"xgb": 0.9, "lgbm": 0.6, "rf": 0.8, "cat": 0.7})
    assert (time.perf_counter() - t0) / 1000 < 0.002           # well under 2 ms per debate


def test_main_agent_needs_every_subagent():
    from sol import agents
    ok = agents.review("sol", "SAFE", "BUY", 0.9, [("Risk", True, "fine"), ("Rug check", True, "fine")])
    assert ok["final"] == "BUY"
    no = agents.review("sol", "RUG", "BUY", 0.9, [("Risk", True, "fine"), ("Price", False, "moved +40%")])
    assert no["final"] == "PASS" and "Price" in no["says"]
    desk = agents.desk()
    assert {r["asset"] for r in desk["sol"]} == {"SAFE", "RUG"}
    subs = agents.mt5_subagents("buy", 0.62, 0.6, 2.0, 4.0, np.array([5, 4, 3, 2, 1, 0.5]), "sell")
    assert [s[0] for s in subs] == ["Confidence", "Reward/risk", "Momentum", "Quiz agent"]
    assert not subs[1][1] and not subs[2][1]                   # stop bigger than target; candles against a thin edge


def test_telegram_prof_loss_total():
    from agent import ledger
    from app import telegram
    from sol import store
    for pnl in (10.0, -4.0, 2.5):
        tid = ledger.open_trade("paper", "XAUUSD", "buy", 0.01, 2000, 1990, 2020)
        ledger.close_trade(tid, 2000 + pnl, "tp" if pnl > 0 else "sl", pnl)
    pid = store.open_position("M1", "WIF", "paper", 0.1, 1.0, 30, 10, 20, {})
    store.close_position(pid, 1.5, "tp")
    prof, loss, total = (telegram.command_reply(c) for c in ("/prof", "/loss", "/total"))
    assert "MT5 paper: +$12.50" in prof and "Solana paper: +0.0500 SOL" in prof
    assert "MT5 paper: -$4.00" in loss and "Solana paper: +0.0000 SOL" in loss
    assert "MT5 paper: +$8.50" in total and "(3 trades)" in total
    assert telegram.command_reply("/total@MyTradingBot") == total
    assert "/prof" in telegram.command_reply("/help")
    assert telegram.command_reply("hello") is None


def test_starter_set_and_two_creators_write_questions_to_disk():
    from sol import trench
    assert trench.starter_set(600) == 600
    assert trench.starter_set(600) == 0                          # written once
    c = trench.Creators()
    try:
        st = c.ensure(2)
        assert st["running"] == 2
        for _ in range(100):
            if trench.count_lines(trench.questions_path()) >= 600:
                break
            time.sleep(0.05)
    finally:
        c.stop.set()
    assert trench.count_lines(trench.questions_path()) == 600    # split between the two, nothing done twice
    q = next(trench.iter_rows(trench.questions_path()))
    assert q["answer"] in ("BUY", "PASS") and len(q["x"]) == 8 and q["mode"] == "trenching"
    info = trench.dataset_info()
    assert info["starter"] == 600 and info["questions"] == 600


def test_candle_windows_label_plus_25_before_minus_12():
    from sol.features import label_path
    assert label_path(1.0, [1.1, 1.3] + [1.0] * 28, [0.95] * 30) == 1
    assert label_path(1.0, [1.1] * 30, [0.95, 0.87] + [1.0] * 28) == 0
    assert label_path(1.0, [1.1] * 10, [0.95] * 10) is None       # not 30 minutes yet


def test_crew_splits_to_train_and_merges_into_one_fast_bot():
    pytest.importorskip("xgboost"); pytest.importorskip("lightgbm"); pytest.importorskip("sklearn")
    from sol import model, trench
    trench.starter_set(1500)
    c = trench.Creators()
    try:
        c.ensure(2)
        for _ in range(200):
            if trench.count_lines(trench.questions_path()) >= 1500:
                break
            time.sleep(0.05)
    finally:
        c.stop.set()
    meta = trench.train_quiz()
    assert model.state["merged"] and not model.state["training"] and model.loaded()
    assert (model.model_dir() / "bot.joblib").exists() and meta["metrics"]["auc"] > 0.55
    probs = model.predict(np.array(trench.load_questions(1)[0][0]))
    assert "bot" in probs and {"xgb", "lgbm", "rf"} <= set(probs)
    x = trench.load_questions(1)[0][:1]
    t0 = time.perf_counter()
    for _ in range(20):
        model.predict(x)
    assert (time.perf_counter() - t0) / 20 < 0.05                # the spec's 5 ms on a normal PC; loose for CI boxes
    import joblib
    rf = joblib.load(model.model_dir() / "bot.joblib")["members"]["rf"]
    X = trench.load_questions(200)[0]
    assert np.allclose(rf.predict_proba(X)[:, 1], model._bot["members"]["rf"].predict_proba(X)[:, 1])


def test_pipeline_opens_and_closes_a_paper_trade(monkeypatch):
    from sol import engine, feeds, model, store
    monkeypatch.setattr(feeds, "prices", lambda mints: {m: 0.00102 for m in mints})
    monkeypatch.setattr(model, "loaded", lambda: True)
    monkeypatch.setattr(model, "predict", lambda x: {"xgb": 0.93, "lgbm": 0.9, "rf": 0.95, "bot": 0.94})
    monkeypatch.setitem(engine.state, "auto_trade", True)
    monkeypatch.setitem(engine.state, "mode", "paper")
    out = engine.evaluate(dict(SAFE))
    assert out["verdict"] == "BUY" and out["debate"]["review"]["final"] == "BUY"
    [p] = store.positions("open")
    assert p["mode"] == "paper" and p["entry_px"] == pytest.approx(0.00102)
    assert store.get_debate("MINTSAFE")["consensus"]["verdict"] == "BUY"
    done = engine.close(p["id"], "tp", px=0.00102 * 1.3)
    assert done["pnl_pct"] == pytest.approx(30.0) and done["status"] == "closed"
    assert all(b["score"] > 0 and b["last_win"] > 0 for b in store.bots().values())   # all said BUY: all right
    rugged = engine.evaluate({**SAFE, "mint": "RUGGED", "freeze_authority": "Dev"})
    assert rugged["verdict"] == "BLOCKED" and len(store.positions("open")) == 0


def test_routes():
    from fastapi.testclient import TestClient
    from app import server, settings
    c = TestClient(server.app)
    st = c.get("/api/sol/state").json()
    assert {"scanner", "mode", "model", "config", "bots", "crew", "dataset"} <= set(st) and st["mode"] == "paper"
    assert "SOL_PRIVATE_KEY" not in str(st) and "private" not in str(st).lower()
    assert c.get("/api/trench/state").json()["mode"] in ("stocks", "trenching", "combined")
    assert c.post("/api/quiz/mode", json={"mode": "nope"}).status_code == 400
    assert c.post("/api/quiz/mode", json={"mode": "combined"}).json() == {"mode": "combined"}
    assert settings.load()["quiz_mode"] == "combined"
    assert c.post("/api/sol/mode", json={"mode": "live", "confirm": "yes"}).status_code == 400
    assert c.get("/api/sol/debate/NOPE").status_code == 404
    assert c.get("/api/agents").json().keys() == {"mt5", "sol"}


def test_agent_profile_votes_chart_and_activity(monkeypatch):
    from fastapi.testclient import TestClient
    from app import server
    from sol import engine, feeds, model, store
    monkeypatch.setattr(feeds, "prices", lambda mints: {m: 0.00102 for m in mints})
    t0 = int(time.time()) // 60 * 60 - 3600
    monkeypatch.setattr(feeds, "candles", lambda pool, limit=300: [[t0 + 60 * i, 1, 1.2, .9, 1.1, 5] for i in range(60)])
    monkeypatch.setattr(model, "loaded", lambda: True)
    monkeypatch.setattr(model, "predict", lambda x: {"xgb": 0.93, "lgbm": 0.74, "rf": 0.95, "bot": 0.9})
    monkeypatch.setitem(engine.state, "auto_trade", True)
    monkeypatch.setitem(engine.state, "mode", "paper")
    engine.evaluate({**SAFE, "pool": "POOL1"})
    [pos] = store.positions("open")
    votes = {v["model"]: v for v in store.votes("lgbm") + store.votes("xgb")}
    assert votes["lgbm"]["open_prob"] == pytest.approx(0.74) and votes["lgbm"]["position_id"] == pos["id"]
    c = TestClient(server.app)
    live = c.get("/api/sol/agent/lgbm").json()
    assert live["activity"][0]["status"] == "open" and live["chart"]["symbol"] == "SAFE"
    assert len(live["chart"]["candles"]) == 60 and live["chart"]["markers"][0]["kind"] == "buy"
    assert live["confidence"]["last"] > 0.74                       # it moved toward the others in the debate
    engine.close(pos["id"], "tp", px=0.00102 * 1.3)
    done = c.get("/api/sol/agent/lgbm").json()
    a = done["activity"][0]
    assert a["status"] == "closed" and a["pnl_pct"] == pytest.approx(30.0)
    assert a["points"] == pytest.approx(30.0 if a["stance"] == "BUY" else -30.0)
    assert [m["kind"] for m in done["chart"]["markers"]] == ["buy", "sell"]
    assert done["stats"]["debates"] == 1 and done["stats"]["trades"] == 1
    assert c.get("/api/sol/agent/nobody").status_code == 404
