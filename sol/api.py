"""Routes for the Solana tab (/api/sol/*), the trenching quiz (/api/trench/*) and the agents desk (/api/agents)."""
import threading
import time

from fastapi import APIRouter, Body, HTTPException

from app import settings

from . import agents, engine, feeds, model, store, trench, wallet

router = APIRouter()
EXIT = {"tp": "take_profit", "trail": "trailing_stop", "stop": "stop_loss", "timeout": "timeout", "manual": "manual",
        "kill": "kill"}
_jobs = {"dataset": None}


def _bg(fn, *a):
    def run():
        try:
            fn(*a)
        except Exception:                               # noqa: BLE001 - the error is in the job's own state
            pass
    threading.Thread(target=run, daemon=True).start()


@router.get("/api/sol/state")
def sol_state():
    c = engine.cfg()
    m = model.meta()
    cnt = store.counts()
    dl, tr = trench.state["download"], trench.state["train"]
    info = trench.dataset_info()
    return {
        "scanner": {"running": engine.state["running"], **cnt, "last_scan": engine.state["last_scan"],
                    "error": engine.state["error"]},
        "mode": engine.state["mode"], "auto_trade": engine.state["auto_trade"],
        "wallet": wallet.info() if engine.state["mode"] == "live" else {"key_loaded": bool(wallet._env().get("SOL_PRIVATE_KEY")),
                                                                       "pubkey": None, "sol_balance": None},
        "paper": {"balance_sol": round(engine.paper_balance(c), 6), "start_sol": c["paper_start"]},
        "model": {"loaded": model.loaded(), "merged": model.state["merged"] and not model.state["training"],
                  "trained_at": m.get("trained_at"), "n_samples": m.get("n_samples"),
                  "synthetic": m.get("synthetic", 0) > 0.5, "synthetic_share": m.get("synthetic"),
                  "device": "cpu", "method": "stacking (split to train, merged into one bot)",
                  "metrics": m.get("metrics"), "members": model.state["members"], "available": model.available(),
                  "problems": model.problems()},
        "training": {"running": model.state["training"] or tr["running"], "progress": model.state["progress"],
                     "stage": model.state["stage"] or tr["stage"], "error": tr["error"] or model.state["error"]},
        "dataset": {"running": dl["running"], "progress": dl["progress"], "stage": dl["stage"],
                    "wallets_checked": dl["pools"], "wallets_skilled": None, "samples": info["samples"],
                    "real": info["real"], "starter": info["starter"], "error": dl["error"]},
        "apis": {"helius": bool(wallet._env().get("SOL_RPC_URL")), "dexscreener": feeds.status["geckoterminal"],
                 "rugcheck": feeds.status["rugcheck"], "jupiter": feeds.status["jupiter"]},
        "config": {k: c[k] for k in ("trade_size_sol", "max_open", "tp_pct", "trail_pct", "timeout_min",
                                     "buy_threshold", "model_floor")},
        "bots": engine.bots_view(),
        "crew": {"merged": model.state["merged"] and not model.state["training"], "training": model.state["training"]},
        "debate": {"max_rounds": 3, "last_ms": engine.state["last_debate_ms"]},
    }


@router.get("/api/sol/feed")
def sol_feed(limit: int = 60):
    out = []
    for r in store.feed(limit):
        row = {"mint": r["mint"], "symbol": r["symbol"], "name": r["name"], "seen": r["t"], "liquidity_usd": r["liq_usd"],
               "age_min": r["age_min"], "buys_5m": r["buys5"], "sells_5m": r["sells5"],
               "status": "passed" if r["passed"] else "blocked", "reasons": r["why"]}
        if r["passed"]:
            d = store.get_debate(r["mint"])
            if d and d.get("probs"):
                p = d["probs"]
                row["ensemble"] = {**{f"{k}_prob": v for k, v in p.items() if k != "bot"},
                                   "ensemble_score": d["consensus"]["score"], "bot_prob": p.get("bot"),
                                   "signal": d["consensus"]["verdict"], "latency_ms": d.get("predict_ms")}
                row["debate"] = {"verdict": (d.get("review") or {}).get("final", d["consensus"]["verdict"]),
                                 "consensus": d["consensus"]["score"]}
        out.append(row)
    return out


@router.get("/api/sol/debate/{mint}")
def sol_debate(mint: str):
    d = store.get_debate(mint)
    if not d:
        raise HTTPException(404, "No debate for this coin.")
    return d


def _pos_view(p):
    stop = None
    if p["entry_px"]:
        stop = (p["peak_px"] * (1 - p["trail_pct"] / 100) / p["entry_px"] - 1) * 100
    return {"id": p["id"], "mint": p["mint"], "symbol": p["symbol"], "mode": p["mode"], "size_sol": p["size_sol"],
            "entry_price": p["entry_px"], "last_price": p["last_px"], "pnl_pct": p.get("pnl_pct"),
            "pnl_sol": p.get("pnl_sol"), "stop_pct": stop, "tp_pct": p["tp_pct"],
            "timeout_at": p["opened"] + p["timeout_min"] * 60, "opened_at": p["opened"], "debate": p.get("debate")}


@router.get("/api/sol/positions")
def sol_positions():
    return [_pos_view(p) for p in store.positions("open")]


@router.get("/api/sol/trades")
def sol_trades(limit: int = 200):
    return [{"id": p["id"], "symbol": p["symbol"], "mint": p["mint"], "mode": p["mode"], "size_sol": p["size_sol"],
             "entry_price": p["entry_px"], "exit_price": p["exit_px"], "pnl_pct": p["pnl_pct"], "pnl_sol": p["pnl_sol"],
             "exit_reason": EXIT.get(p["reason"], p["reason"]), "closed_at": p["closed"], "opened_at": p["opened"]}
            for p in store.positions("closed", limit)]


@router.get("/api/sol/pnl")
def sol_pnl():
    mode = engine.state["mode"]
    r = store.realized(mode)
    opens = [_pos_view(p) for p in store.positions("open") if p["mode"] == mode]
    return {"points": store.pnl_curve(mode), "wins": r["wins"], "losses": r["n"] - r["wins"],
            "win_rate": r["wins"] / r["n"] if r["n"] else None, "realized_sol": r["prof"] + r["loss"],
            "open_sol": sum(p["pnl_sol"] or 0 for p in opens)}


@router.post("/api/sol/scanner")
def sol_scanner(body: dict = Body(...)):
    return {"running": engine.set_scanner(bool(body.get("run")))}


@router.post("/api/sol/autotrade")
def sol_autotrade(body: dict = Body(...)):
    engine.state["auto_trade"] = bool(body.get("on"))
    return {"auto_trade": engine.state["auto_trade"]}


@router.post("/api/sol/mode")
def sol_mode(body: dict = Body(...)):
    try:
        return {"mode": engine.set_mode(body.get("mode", ""), body.get("confirm", ""))}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/api/sol/train")
def sol_train():
    if model.state["training"] or trench.state["train"]["running"]:
        raise HTTPException(409, "Training is already running.")
    _bg(trench.train_quiz)
    return {"started": True}


@router.post("/api/sol/dataset")
def sol_dataset(body: dict = Body(default={})):
    if trench.state["download"]["running"]:
        raise HTTPException(409, "The download is already running.")
    _bg(trench.download, int(body.get("pools") or 24))
    return {"started": True}


@router.post("/api/sol/positions/{pid}/close")
def sol_close(pid: int):
    try:
        p = engine.close(pid, "manual")
    except ValueError as e:
        raise HTTPException(404, str(e))
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    return {"id": pid, "exit_price": p.get("exit_px"), "pnl_pct": p.get("pnl_pct"), "pnl_sol": p.get("pnl_sol")}


# ---------- one agent's profile (the expand button on its avatar) ----------
_candles = {}


def _candles_for(mint: str) -> list:
    """1-minute candles of a coin's pool for a profile chart (cached 30 s: GeckoTerminal allows ~30 calls a minute)."""
    pool = store.seen_snap(mint).get("pool")
    if not pool:
        return []
    hit = _candles.get(pool)
    if hit and time.time() - hit[0] < 30:
        return hit[1]
    cs = feeds.candles(pool, 120)
    _candles[pool] = (time.time(), cs)
    for k in sorted(_candles, key=lambda k: _candles[k][0])[:-40]:
        _candles.pop(k, None)
    return cs


@router.get("/api/sol/agent/{name}")
def sol_agent(name: str):
    bots = {b["model"]: b for b in engine.bots_view()}
    if name not in bots and name not in model.MEMBERS:
        raise HTTPException(404, "No agent with that name.")
    b = bots.get(name) or {"model": name, "score": 0, "trade_score": 0, "quiz_score": 0, "last_win": 0, "doing": ""}
    ranked = sorted(bots.values(), key=lambda x: -(x.get("score") or 0))
    rank = next((i + 1 for i, x in enumerate(ranked) if x["model"] == name), len(ranked) + 1)
    c = engine.cfg()
    vs = store.votes(name, 40)
    opens = {p["id"]: p for p in store.positions("open")}
    focus = next((v for v in vs if v["position_id"] in opens and v["stance"] == "BUY"), vs[0] if vs else None)
    chart = None
    if focus:
        mint = focus["mint"]
        trades = [p for p in list(opens.values()) + store.positions("closed", 60) if p["mint"] == mint]
        marks = []
        for p in trades:
            marks.append({"t": p["opened"], "kind": "buy", "price": p["entry_px"], "text": "Bought"})
            if p["status"] == "closed":
                marks.append({"t": p["closed"], "kind": "sell", "price": p["exit_px"], "text": f"Sold {p['pnl_pct']:+.0f}%"})
        live = opens.get(focus["position_id"])
        chart = {"mint": mint, "symbol": focus["symbol"], "markers": sorted(marks, key=lambda m: m["t"]),
                 "candles": [r[:5] for r in _candles_for(mint)],
                 "position": None if not live else {"entry": live["entry_px"], "last": live["last_px"],
                                                     "pnl_pct": live.get("pnl_pct"), "tp_pct": live["tp_pct"]}}
    meta = model.meta().get("metrics") or {}
    status = lambda v: ("open" if v["position_id"] in opens else "closed" if v["closed"] else
                        "traded" if v["position_id"] else "passed")          # noqa: E731
    return {
        "model": name, "score": b.get("score"), "trade_score": b.get("trade_score"), "quiz_score": b.get("quiz_score"),
        "last_win": b.get("last_win"), "rank": rank, "of": len(ranked), "doing": b.get("doing"),
        "stats": store.vote_stats(name),
        "confidence": {"last": vs[0]["final_prob"] if vs else None, "last_symbol": vs[0]["symbol"] if vs else None,
                       "last_stance": vs[0]["stance"] if vs else None, "need": c["buy_threshold"], "floor": c["model_floor"],
                       "series": [{"t": v["t"], "p": v["final_prob"], "open": v["open_prob"], "symbol": v["symbol"],
                                   "stance": v["stance"]} for v in reversed(vs)]},
        "activity": [{**{k: v[k] for k in ("t", "symbol", "mint", "stance", "open_prob", "final_prob", "verdict",
                                            "position_id", "points")},
                      "pnl_pct": v["pnl_pct"] if v["closed"] else (opens[v["position_id"]].get("pnl_pct")
                                                                    if v["position_id"] in opens else None),
                      "status": status(v)} for v in vs[:25]],
        "chart": chart,
        "model_info": {"auc": (meta.get("members") or {}).get(name), "weight": (meta.get("weights") or {}).get(name)},
    }


# ---------- trenching quiz ----------
@router.get("/api/trench/state")
def trench_state():
    return {"mode": settings.load().get("quiz_mode", "trenching"), **trench.dataset_info(),
            "creators": trench.creators.status(), "download": trench.state["download"], "train": trench.state["train"],
            "model": {"loaded": model.loaded(), "merged": model.state["merged"] and not model.state["training"],
                      "training": model.state["training"], "progress": model.state["progress"],
                      "stage": model.state["stage"], "members": model.state["members"],
                      "metrics": model.meta().get("metrics"), "problems": model.problems()},
            "bots": engine.bots_view()}


@router.get("/api/trench/question")
def trench_question(i: int | None = None):
    q = trench.sample_question(i)
    if not q:
        raise HTTPException(404, "No questions yet: the question creators are still writing them.")
    return q


@router.post("/api/trench/train")
def trench_train():
    return sol_train()


@router.post("/api/trench/download")
def trench_download(body: dict = Body(default={})):
    return sol_dataset(body)


@router.post("/api/quiz/mode")
def quiz_mode(body: dict = Body(...)):
    m = body.get("mode")
    if m not in ("stocks", "trenching", "combined"):
        raise HTTPException(400, "mode must be stocks, trenching or combined")
    settings.save({"quiz_mode": m})
    return {"mode": m}


# ---------- agents desk ----------
@router.get("/api/agents")
def agents_desk():
    d = agents.desk()
    now = time.time()
    for rows in d.values():
        for r in rows:
            r["age_s"] = round(now - r["t"], 1)
    return d


def startup():
    model.load()
    engine.start_monitor()
    trench.keep_alive()
