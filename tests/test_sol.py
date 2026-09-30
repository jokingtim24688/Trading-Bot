"""Solana trenching bot: rug filter, instant debate, main agents + subagents, Telegram commands, question creators,
the model crew (split to train, merged after) and the routes. Everything writes under the test's temp data folder."""
import json
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


def test_rank_ladder_rules_and_hysteresis():
    from sol import ranks
    f = ranks.rank_for
    assert f(0, 0, None) == 0 and f(30, 0, None) == 1                 # the quiz grade alone makes a Junior
    assert f(80, 5, None) == 2 and f(80, 4, None) == 1                 # Trader needs 5 closed trades
    assert f(160, 15, 0.56) == 3 and f(160, 15, 0.50) == 2             # Senior needs 55 % right
    assert f(5000, 500, 0.9) == 6                                      # Legend is the top
    assert f(140, 15, 0.54, current=3) == 3                            # a little under Senior: keeps it
    assert f(130, 15, 0.54, current=3) == 2                            # clearly under: drops one rung
    assert f(10, 0, None, current=3) == 0                              # and all the way down when it has to
    p = ranks.progress(2, 120, 9, 0.6)
    assert p["name"] == "Senior Trader" and p["frac"] == pytest.approx(0.6, abs=0.01)   # trades 9/15 is the slowest
    assert ranks.progress(6, 9999, 999, 0.9) is None


def test_quiz_grade_replaces_instead_of_adding():
    from sol import store
    store.add_score("xgb", 36.0, quiz=True)
    store.add_score("xgb", 40.0, quiz=True)
    store.add_score("xgb", 12.5)
    b = store.bots()["xgb"]
    assert b["quiz"] == 40.0 and b["score"] == 12.5 and b["rank"] == 0


def test_promotion_is_logged_announced_and_weights_the_debate():
    from sol import debate, ranks, store
    said = []
    store.add_score("lgbm", 36.0, quiz=True)                          # quiz grade: Intern -> Junior Trader
    store.add_score("rf", 5.0, quiz=True)
    ch = ranks.update(["lgbm", "rf"], say=said.append)
    assert [c["model"] for c in ch] == ["lgbm"] and ch[0]["to"]["name"] == "Junior Trader" and ch[0]["up"]
    assert said and store.rank_log("lgbm")[0]["rank"] == 1 and store.bots()["lgbm"]["rank"] == 1
    assert ranks.update(["lgbm"]) == []                                 # nothing new: no duplicate log rows
    w = ranks.weights()
    assert w["lgbm"] == 1.1 and w["rf"] == 1.0
    even = debate.run({"xgb": 0.9, "lgbm": 0.6, "rf": 0.7}, weights={"xgb": 1.0, "lgbm": 1.0, "rf": 1.0})
    heavy = debate.run({"xgb": 0.9, "lgbm": 0.6, "rf": 0.7}, weights={"xgb": 2.0, "lgbm": 1.0, "rf": 1.0})
    assert heavy["consensus"]["score"] > even["consensus"]["score"]     # a Legend's vote pulls the crew its way
    assert heavy["weights"]["xgb"] == 2.0


def test_ranks_route_and_career_in_profile():
    from fastapi.testclient import TestClient
    from app import server
    from sol import ranks, store
    store.add_score("xgb", 40.0, quiz=True)
    store.add_score("xgb", 60.0)
    ranks.update(["xgb"])
    c = TestClient(server.app)
    d = c.get("/api/sol/ranks").json()
    assert [r["name"] for r in d["ranks"]][0] == "Intern" and len(d["ranks"]) == 7
    top = d["agents"][0]
    assert top["model"] == "xgb" and top["rank"]["name"] == "Junior Trader" and top["points"] == 100.0
    assert top["next"]["name"] == "Trader" and 0 <= top["pct"] < 100          # 100/75 pts but 0/5 trades
    assert "xgb" in d["ranks"][1]["agents"] and d["log"][0]["model"] == "xgb"
    prof = c.get("/api/sol/agent/xgb").json()
    assert prof["career"]["rank"]["name"] == "Junior Trader" and prof["career"]["history"]


# ---------- every agent's own tweet monitor (sol/tweets.py) ----------
def _posts(now=None):
    now = now or time.time()
    return [
        {"id": "1", "text": "just launched $FROGGY on pump.fun, 9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin",
         "t": now - 120, "url": "https://x.com/alpha/status/1", "author": "alpha", "followers": 42000,
         "account_t": now - 500 * 86400, "verified": True, "likes": 320, "rts": 40, "views": 90000,
         "links": [], "tags": ["FROGGY"]},
        {"id": "2", "text": "free airdrop! claim your bag now, dm me", "t": now - 60, "url": "u2",
         "author": "spambot", "followers": 30, "account_t": now - 2 * 86400, "verified": False,
         "likes": 0, "rts": 0, "views": 5, "links": [], "tags": []},
        {"id": "3", "text": "$FROGGY sending", "t": now - 200, "url": "u3", "author": "beta", "followers": 8000,
         "account_t": now - 900 * 86400, "verified": False, "likes": 60, "rts": 5, "views": 12000,
         "links": ["https://pump.fun/coin/9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin"], "tags": []},
    ]


def test_tweet_monitor_reads_a_mint_and_filters_the_spam(monkeypatch):
    from app import settings
    from sol import store, tweets
    settings.save({"x_provider": "twitterapi", "x_api_key": "k", "x_min_voices": 1})
    monkeypatch.setattr(tweets, "pull", lambda q, n, c: _posts())
    monkeypatch.setattr(tweets, "crew", lambda: ["xgb", "lgbm", "rf", "cat"])
    monkeypatch.setattr(tweets.feeds, "token_pools",
                        lambda m: [{"mint": m, "symbol": "FROGGY", "liq_usd": 9000, "price_usd": 0.001}])
    seen = []
    monkeypatch.setattr(tweets.engine, "evaluate",
                        lambda snap, c=None, trade=True: seen.append(snap) or
                        {"mint": snap["mint"], "verdict": "PASS", "gate": {"passed": True, "why": []}})
    r = tweets.round_once()
    assert r["reads"] == 12 and r["checked"] == 1                  # four beats x three posts, one coin between them
    find = r["found"][0]
    assert find["mint"] == "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin" and not find["why"]
    assert "spambot" not in {p["author"] for p in find["posts"]}   # the airdrop post never became a candidate
    assert seen and seen[0]["found_via"] == "x" and seen[0]["found_by"] == "alpha"
    assert store.tweet_finds(5)[0]["status"] == "blocked"          # PASS from the crew, so no trade


def test_a_tweet_find_still_has_to_pass_the_rug_filter(monkeypatch):
    """The whole point: a coin everyone is posting about is still thrown out by rug.check."""
    from app import settings
    from sol import engine, store, tweets
    settings.save({"x_provider": "twitterapi", "x_api_key": "k", "x_min_voices": 1, "sol_min_liq_usd": 5000})
    monkeypatch.setattr(tweets, "pull", lambda q, n, c: _posts())
    monkeypatch.setattr(tweets, "crew", lambda: ["xgb"])
    monkeypatch.setattr(tweets.feeds, "token_pools", lambda m: [{
        "mint": m, "symbol": "FROGGY", "liq_usd": 40000, "price_usd": 0.001, "age_min": 5, "buys_5m": 80,
        "sells_5m": 10, "vol_5m": 9000, "chg_5m": 40}])
    monkeypatch.setattr(engine.feeds, "rug_facts", lambda mint: {                # the mint authority is still alive
        "mint_authority": "SomeoneKeptIt", "freeze_authority": None, "lp_locked_pct": 100.0,
        "top10_pct": 12.0, "dev_pct": 1.0})
    engine.state["auto_trade"] = True
    tweets.round_once()
    row = store.tweet_finds(5)[0]
    assert row["status"] == "blocked" and "mint authority" in row["why"].lower()
    assert not store.positions("open")                                          # nothing was bought


def test_every_agent_gets_its_own_beat_and_the_key_never_leaves(monkeypatch):
    from app import settings
    from fastapi.testclient import TestClient
    from app import server
    from sol import tweets
    monkeypatch.setattr(tweets, "crew", lambda: ["xgb", "lgbm", "rf", "cat"])
    c = TestClient(server.app)
    c.post("/api/sol/tweets/key", json={"provider": "twitterapi", "key": "super-secret"})
    d = c.get("/api/sol/tweets").json()
    assert [b["model"] for b in d["beats"]] == ["xgb", "lgbm", "rf", "cat"]
    assert len({b["id"] for b in d["beats"]}) == 4                  # four different beats, not four of the same
    assert d["key_set"] is True and "super-secret" not in json.dumps(d)
    assert settings.load()["x_api_key"] == "super-secret"           # saved, just never handed back
    assert "super-secret" not in json.dumps(c.get("/api/status").json())
    assert c.get("/api/status").json()["settings"]["x_api_key"] == settings.KEPT
    settings.save({"x_api_key": settings.KEPT})                     # the app sending the placeholder back
    assert settings.load()["x_api_key"] == "super-secret"           # doesn't wipe the real one
    # one agent's monitor can be switched off on its own
    d = c.post("/api/sol/tweets/beat", json={"model": "rf", "on": False}).json()
    assert [b["on"] for b in d["beats"]] == [True, True, False, True]
    assert c.get("/api/sol/agent/xgb").json()["tweets"]["beat"]["id"] == "launches"


def test_monitor_filters_quiet_posts_and_lonely_coins():
    from app import settings
    from sol import tweets
    settings.save({"x_min_likes": 10, "x_min_followers": 1000, "x_min_account_days": 30, "x_max_age_min": 45})
    c, beat = tweets.cfg(), tweets.BEATS[0]
    now = time.time()
    base = {"text": "nice coin", "likes": 500, "followers": 90000, "account_t": now - 900 * 86400,
            "t": now - 60, "author": "a", "verified": False, "views": 10}
    assert tweets.grade(base, c, beat) == ""
    assert "likes" in tweets.grade({**base, "likes": 1}, c, beat)
    assert "followers" in tweets.grade({**base, "followers": 20}, c, beat)
    assert "days old" in tweets.grade({**base, "account_t": now - 3 * 86400}, c, beat)
    assert "min ago" in tweets.grade({**base, "t": now - 3 * 3600}, c, beat)
    assert "spam" in tweets.grade({**base, "text": "claim your free airdrop"}, c, beat)
    # louder, fresher, more voices and a higher-ranked finder all score higher
    lonely, crowd = tweets.heat(base, beat, 1), tweets.heat(base, beat, 4)
    assert crowd > lonely and tweets.heat(base, beat, 4, 1.5) > crowd
    assert tweets.heat(base, beat, 4, 1.0, 3) > crowd               # two beats found it, not one


def test_monitor_needs_a_key_and_reports_what_it_costs():
    from app import settings
    from sol import tweets
    settings.save({"x_provider": "off", "x_api_key": ""})
    with pytest.raises(ValueError):
        tweets.set_monitor(True)
    assert tweets.round_once()["reads"] == 0                        # no key: it never calls anyone
    settings.save({"x_provider": "twitterapi", "x_api_key": "k", "x_scan_s": 300, "x_per_beat": 15})
    cost = tweets.cost()
    assert cost["rate"] == 0.00015 and cost["posts_per_day"] == cost["monitors"] * 15 * 288
    assert cost["usd_per_day"] == round(cost["posts_per_day"] * 0.00015, 2)


def test_mints_are_read_out_of_links_and_text():
    from sol import tweets
    p = {"text": "ape $WIF now", "tags": [],
         "links": ["https://dexscreener.com/solana/EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm"]}
    mints, tags = tweets.candidates(p)
    assert mints == ["EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm"] and tags == ["WIF"]
    sol_ = {"text": "So11111111111111111111111111111111111111112 is just SOL", "tags": [], "links": []}
    assert tweets.candidates(sol_)[0] == []                         # wrapped SOL and the stables are never candidates
