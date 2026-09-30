"""The trenching bot's loop: scan -> rug gate -> models -> instant debate -> main agent + subagents -> trade -> exits.

Paper mode by default. Exits: take profit (+30 %, or the debate's compromise), trailing stop (-10 % from the peak),
timeout (20 min). Every step is bounded: one scan never waits on the models, the debate or the review for more than
a few milliseconds; only the network calls take time, and those have short timeouts.
"""
import threading
import time

import numpy as np

from app import settings

from . import agents, debate, feeds, model, ranks, rug, store, wallet
from .features import vector

state = {"running": False, "auto_trade": False, "mode": "paper", "last_scan": None, "error": "", "doing": {},
         "last_debate_ms": None}
_thread: threading.Thread | None = None
_mon: threading.Thread | None = None
_stop = threading.Event()
_mode_lock = threading.Lock()


def cfg() -> dict:
    s = settings.load()
    return {"trade_size_sol": float(s["sol_trade_size_sol"]), "max_open": int(s["sol_max_open"]),
            "tp_pct": float(s["sol_tp_pct"]), "trail_pct": float(s["sol_trail_pct"]),
            "timeout_min": float(s["sol_timeout_min"]), "buy_threshold": float(s["sol_buy_threshold"]),
            "model_floor": float(s["sol_model_floor"]), "min_liq_usd": float(s["sol_min_liq_usd"]),
            "scan_s": max(5.0, float(s["sol_scan_s"])), "paper_start": float(s["sol_paper_start"])}


def paper_balance(c=None) -> float:
    c = c or cfg()
    r = store.realized("paper")
    locked = sum(p["size_sol"] for p in store.positions("open") if p["mode"] == "paper")
    return c["paper_start"] + r["prof"] + r["loss"] - locked


def _say(text, kind="close"):
    try:
        from app import telegram
        telegram.notify_text(text, kind)
    except Exception:                                   # noqa: BLE001 - alerts never break trading
        pass


def evaluate(snap: dict, c=None, trade=True) -> dict:
    """One token through the whole pipeline. Returns what happened (also saved for the feed and debate views)."""
    c = c or cfg()
    snap = {**snap, **feeds.rug_facts(snap["mint"])} if "mint_authority" not in snap else snap
    gate = rug.check(snap, c["min_liq_usd"])
    out = {"mint": snap["mint"], "symbol": snap.get("symbol"), "gate": gate, "verdict": "BLOCKED"}
    if not gate["passed"] or not model.loaded():
        store.record_seen(snap, gate, None, "BLOCKED" if not gate["passed"] else "NO MODEL")
        return out
    t0 = time.perf_counter()
    probs = model.predict(vector(snap))
    predict_ms = (time.perf_counter() - t0) * 1000
    d = debate.run(probs, None, c["buy_threshold"], c["model_floor"], c["trade_size_sol"], c["tp_pct"], c["trail_pct"],
                   weights=ranks.weights())
    state["last_debate_ms"] = d["ms"]
    cons = d["consensus"]
    for m in probs:
        if m != "bot":
            state["doing"][m] = f"debating {snap.get('symbol')}"
    opens = [p for p in store.positions("open") if p["mode"] == state["mode"]]
    comp = cons.get("compromise") or {}
    size = comp.get("size_sol", c["trade_size_sol"])
    bal = paper_balance(c) if state["mode"] == "paper" else (wallet.info().get("sol_balance") or 0)
    fresh = None
    if cons["verdict"] == "BUY":
        fresh = feeds.prices([snap["mint"]]).get(snap["mint"])
    review = agents.review("sol", snap.get("symbol") or snap["mint"][:6], cons["verdict"], cons["score"],
                           agents.sol_subagents(snap, gate, d, len(opens), c["max_open"], bal, size, fresh),
                           {"mint": snap["mint"]})
    d["review"] = review
    d["probs"], d["predict_ms"] = probs, round(predict_ms, 3)
    store.save_debate(snap["mint"], {**d, "symbol": snap.get("symbol"), "mint": snap["mint"], "t": time.time(), "time": time.time()})
    store.record_seen(snap, gate, cons["score"], review["final"])
    store.record_votes(snap["mint"], snap.get("symbol"), d["rounds"], review["final"])
    out.update(verdict=review["final"], debate=d)
    if trade and review["final"] == "BUY" and state["auto_trade"] and not any(p["mint"] == snap["mint"] for p in opens):
        open_trade(snap, fresh or snap.get("price_usd"), size, comp.get("tp_pct", c["tp_pct"]),
                   comp.get("trail_pct", c["trail_pct"]), c["timeout_min"], d)
    return out


def open_trade(snap, px, size, tp, trail, timeout, d):
    if not px:
        return None
    tx = None
    if state["mode"] == "live":
        tx = wallet.buy(snap["mint"], size)             # raises = no position recorded
    pid = store.open_position(snap["mint"], snap.get("symbol"), state["mode"], size, px, tp, trail, timeout,
                              {"consensus": d["consensus"], "ms": d["ms"]}, tx)
    store.link_votes(snap["mint"], pid)
    for m in model.meta().get("metrics", {}).get("members", {}) or {}:
        state["doing"][m] = f"trading {snap.get('symbol')}"
    _say(f"🟢 Bought {snap.get('symbol')} ({state['mode']}) {size:g} SOL — crew {d['consensus']['score']:.0%}", "open")
    return pid


def close(pid: int, reason="manual", px=None) -> dict:
    p = store.get_position(pid)
    if not p or p["status"] != "open":
        raise ValueError("No open position with that id.")
    px = px or feeds.prices([p["mint"]]).get(p["mint"]) or p["last_px"]
    tx = wallet.sell_all(p["mint"]) if p["mode"] == "live" else None
    done = store.close_position(pid, px, reason, tx)
    pct = done.get("pnl_pct") or 0
    settled = store.settle_votes(pid, pct)              # right to buy a winner / right to doubt a loser
    if not settled:                                     # a trade from before votes were kept: use its debate
        try:
            body = store.get_debate(p["mint"]) or {}
            settled = {s["model"]: round(pct if s["stance"] == "BUY" else -pct, 2)
                       for s in (body.get("rounds") or [{}])[-1].get("stances", [])}
        except (KeyError, IndexError, TypeError):
            settled = {}
    for m, pts in settled.items():
        store.add_score(m, pts, win=pts > 0)
    ranks.update(list(settled), say=announce_rank)
    _say(f"{'✅' if pct >= 0 else '🛑'} Sold {p['symbol']} ({reason}) {pct:+.1f}% = {done.get('pnl_sol', 0):+.4f} SOL",
         "tp" if reason == "tp" else ("sl" if reason in ("trail", "timeout") else "close"))
    return done


def announce_rank(ch: dict):
    name = {"xgb": "XGBoost", "lgbm": "LightGBM", "rf": "RandomForest", "cat": "CatBoost"}.get(ch["model"], ch["model"])
    if ch["up"]:
        _say(f"🎖 {name} promoted to {ch['to']['name']} — {ch['to']['perk']}", "close")
    else:
        _say(f"⬇ {name} dropped to {ch['to']['name']}", "close")


def _monitor():
    while not _stop.is_set():
        try:
            opens = store.positions("open")
            px = feeds.prices([p["mint"] for p in opens]) if opens else {}
            for p in opens:
                now_px = px.get(p["mint"])
                if now_px:
                    store.update_price(p["id"], now_px)
                    peak = max(p["peak_px"], now_px)
                else:
                    now_px, peak = p["last_px"], p["peak_px"]
                gain = (now_px / p["entry_px"] - 1) * 100
                if gain >= p["tp_pct"]:
                    close(p["id"], "tp", now_px)
                elif peak > p["entry_px"] and (now_px / peak - 1) * 100 <= -p["trail_pct"]:
                    close(p["id"], "trail", now_px)
                elif gain <= -p["trail_pct"] * 1.5:
                    close(p["id"], "stop", now_px)
                elif (time.time() - p["opened"]) / 60 >= p["timeout_min"]:
                    close(p["id"], "timeout", now_px)
        except Exception as e:                          # noqa: BLE001
            state["error"] = f"monitor: {e}"
        _stop.wait(5)


def _scan_loop():
    seen_mem = set()
    while state["running"] and not _stop.is_set():
        c = cfg()
        try:
            fresh = [s for s in feeds.new_pools(1) if s["mint"] not in seen_mem]
            for s in fresh[:12]:
                seen_mem.add(s["mint"])
                evaluate(s, c)
            state.update(last_scan=time.time(), error="" if fresh or feeds.status["geckoterminal"] else
                         "GeckoTerminal didn't answer (offline or blocked)")
        except Exception as e:                          # noqa: BLE001
            state["error"] = str(e)
        for m in list(state["doing"]):
            if not state["doing"][m].startswith("trading"):
                state["doing"][m] = "watching"
        _stop.wait(c["scan_s"])


def start_monitor():
    global _mon
    if _mon is None or not _mon.is_alive():
        _stop.clear()
        _mon = threading.Thread(target=_monitor, name="sol-monitor", daemon=True)
        _mon.start()


def set_scanner(on: bool):
    global _thread
    state["running"] = bool(on)
    start_monitor()
    if on and (_thread is None or not _thread.is_alive()):
        _thread = threading.Thread(target=_scan_loop, name="sol-scanner", daemon=True)
        _thread.start()
    if not on:
        for m in state["doing"]:
            state["doing"][m] = "resting"
    return state["running"]


def set_mode(mode: str, confirm: str = "") -> str:
    if mode not in ("paper", "live"):
        raise ValueError("mode must be paper or live")
    with _mode_lock:
        if mode == "live":
            if confirm != "LIVE":
                raise ValueError('Type LIVE to trade real SOL.')
            if not wallet.info()["key_loaded"]:
                raise ValueError("No wallet key: put SOL_PRIVATE_KEY in .env first.")
        state["mode"] = mode
    return mode


def bots_view() -> list[dict]:
    b = store.bots()
    names = list(model.meta().get("metrics", {}).get("members", {}) or {}) or model.available()
    out = []
    for m in names:
        r = b.get(m, {})
        doing = "training" if model.state["training"] else state["doing"].get(m, "watching" if state["running"] else "resting")
        out.append({"model": m, "score": round((r.get("score") or 0) + (r.get("quiz") or 0), 1),
                    "trade_score": round(r.get("score") or 0, 1), "quiz_score": round(r.get("quiz") or 0, 1),
                    "doing": doing, "last_win": r.get("last_win") or 0,
                    "rank": {**ranks.info(r.get("rank") or 0), "since": r.get("rank_t") or 0}})
    return out
