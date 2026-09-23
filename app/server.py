"""Local HTTP API + static UI for the desktop app. Bound to 127.0.0.1 only."""
import csv
import json
import shutil
import subprocess
import time
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from agent import learn, ledger, progression, score as scoring

from . import brain, memory, mt5_service, settings
from .jobs import LOGS, jobs
from .settings import ROOT

STATIC = Path(__file__).parent / "static"
AGENT_MAGIC = 260923
app = FastAPI(title="Trading Bot")


@app.exception_handler(mt5_service.MT5Unavailable)
async def _mt5_down(_, exc):
    return JSONResponse({"error": str(exc), "mt5": False}, status_code=503)


@app.exception_handler(ValueError)
async def _bad(_, exc):
    return JSONResponse({"error": str(exc)}, status_code=400)


# ---------- resources (RAM / VRAM) ----------
_res_cache = {"t": 0, "v": {}}


def _resources() -> dict:
    if time.time() - _res_cache["t"] < 2:
        return _res_cache["v"]
    out = {}
    try:
        import psutil
        vm = psutil.virtual_memory()
        procs = [psutil.Process()] + psutil.Process().children(recursive=True)
        app_rss = sum(p.memory_info().rss for p in procs if p.is_running())
        out.update(ram_used_gb=round(vm.used / 1e9, 1), ram_total_gb=round(vm.total / 1e9, 1),
                   app_ram_mb=round(app_rss / 1e6), cpu_pct=psutil.cpu_percent())
    except Exception:
        pass
    if shutil.which("nvidia-smi"):
        try:
            q = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu",
                                "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=3,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            name, used, total, util = [x.strip() for x in q.stdout.splitlines()[0].split(",")]
            out.update(gpu=name, vram_used_gb=round(int(used) / 1024, 1), vram_total_gb=round(int(total) / 1024, 1), gpu_pct=int(util))
        except Exception:
            pass
    _res_cache.update(t=time.time(), v=out)
    return out


# ---------- status & settings ----------
@app.get("/api/status")
def status():
    s = settings.load()
    meta = mt5_service.model_meta(s["symbol"]) or {}
    return {"settings": s, "jobs": jobs.status(), "model_ready": mt5_service.model_exists(s["symbol"]),
            "model": {k: meta.get(k) for k in ("suggested_threshold", "breakeven_win_pct", "exit_rule")},
            "data_ready": (ROOT / "data" / f"{s['symbol']}_M1.parquet").exists(), "resources": _resources()}


@app.post("/api/settings")
def save_settings(body: dict = Body(...)):
    return settings.save(body)


# ---------- MT5 ----------
@app.get("/api/account")
def account():
    return mt5_service.account()


@app.get("/api/positions")
def positions():
    return mt5_service.positions()


@app.get("/api/bars")
def bars(symbol: str, count: int = 240):
    return mt5_service.m1_bars(symbol, min(count, 2000))


@app.get("/api/size")
def size(symbol: str, entry: float, stop: float, risk: float = 0.5):
    return mt5_service.lots_for_risk(symbol, entry, stop, risk)


@app.post("/api/positions/{ticket}/close")
def close(ticket: int):
    for t in ledger.open_trades():                  # a bot trade you close from the app is scored as a manual close
        if t["ticket"] == ticket:
            ledger.set_close_hint(t["id"], "manual (app)")
    return mt5_service.close_position(ticket)


@app.post("/api/kill")
def kill_switch():
    """Flatten the agent's positions and stop it."""
    stop = ROOT / "STOP"
    if jobs.jobs["agent"].running:
        stop.write_text("stop")
        for _ in range(20):
            if not jobs.jobs["agent"].running:
                break
            time.sleep(0.5)
        jobs.stop("agent")
    stop.unlink(missing_ok=True)
    for t in ledger.open_trades():
        if t["mode"] != "paper":
            ledger.set_close_hint(t["id"], "kill")
    try:
        closed = mt5_service.close_all(AGENT_MAGIC)
        time.sleep(0.5)
        mt5_service.sync_bot_ledger()
    except mt5_service.MT5Unavailable:
        closed = []
    return {"stopped": True, "closed": closed}


# ---------- the bot's own trades ----------
def bot_trades_payload(limit: int = 100, symbol: str | None = None) -> dict:
    scoring.SL_MULT = float(settings.load().get("sl_score_mult", 1.5))
    try:
        mt5_service.sync_bot_ledger()
    except Exception:
        pass                                    # MT5 offline: show the ledger as last recorded
    open_ = ledger.open_trades(symbol=symbol)
    try:
        floating = mt5_service.floating_for(open_)
    except Exception:
        floating = {}
    for t in open_:
        t.update(floating.get(t["id"], {"pnl": None, "price": None}))
    status = None
    if jobs.jobs["agent"].running:
        try:
            status = json.loads((ROOT / "data" / "agent_status.json").read_text())
        except (OSError, ValueError):
            status = {"decision": "starting", "reason": "waiting for the next 1-minute candle to close"}
    return {"open": open_, "recent": ledger.recent(limit, symbol=symbol),
            "stats": {m: ledger.stats(m) for m in ("replay", "paper", "demo", "real")}, "agent": status}


@app.get("/api/bot/trades")
def bot_trades(limit: int = 100, symbol: str | None = None):
    return bot_trades_payload(limit, symbol)


# ---------- jobs ----------
def agent_args(s: dict, mode: str, max_open: int | None = None) -> list[str]:
    args = ["-m", "agent.run", "--symbol", s["symbol"], "--threshold", str(s["threshold"]),
            "--stake-pct", str(s["stake_pct"]), "--sl-pct", str(s["sl_pct_of_stake"]),
            "--tp-small", str(s["tp_pct_small"]), "--tp-large", str(s["tp_pct_large"]),
            "--small-stake", str(s["small_stake"]), "--large-stake", str(s["large_stake"]),
            "--max-open", str(int(max_open or s["max_open_trades"])), "--paper-equity", str(s["paper_balance"]),
            "--sl-score-mult", str(s["sl_score_mult"]), "--ref-leverage", str(s.get("ref_leverage", 100))]
    if not s.get("early_exit", True):
        args.append("--no-early-exit")
    if not s.get("use_learned", True):
        args.append("--no-learned")
    if s.get("practice", True) and mode == "paper":
        args.append("--practice")
    if s.get("terminal_path"):
        args += ["--terminal", s["terminal_path"]]
    if mode in ("demo", "real"):
        args.append("--live")
    if mode == "real":
        args.append("--allow-real")
    return args


def stage_args(s: dict) -> list[str]:
    """Agent arguments for the stage the bot has earned (mode + how many trades it may hold)."""
    st = progression.stage_info(progression.load()["stage"])
    cap = min(int(s["max_open_trades"]), st["max_open"]) if st["max_open"] else int(s["max_open_trades"])
    return agent_args(s, st["mode"], cap)


@app.post("/api/agent/start")
def agent_start(body: dict = Body(default={})):
    s = settings.load()
    if not mt5_service.model_exists(s["symbol"]):
        raise HTTPException(400, f"No trained model for {s['symbol']}. Go to Train and run Fetch data, then Train.")
    (ROOT / "STOP").unlink(missing_ok=True)
    try:
        jobs.start("agent", stage_args(s))
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return jobs.status()["agent"]


# ---------- stage ladder + learning ----------
def _stage_balance(mode: str, s: dict) -> float | None:
    if mode == "paper":
        return s["paper_balance"] + ledger.realized_pnl("paper")
    try:
        return mt5_service.account()["balance"]
    except Exception:
        return None


def _restart_agent_if_running(s: dict):
    if jobs.jobs["agent"].running:
        jobs.stop("agent")
        jobs.start("agent", stage_args(s))


def _maybe_learn(state: dict, s: dict, force: bool = False):
    closed = sum(ledger.stats(m)["closed"] for m in ("replay", "paper", "demo", "real"))
    if force or closed - state.get("learned_at_trades", 0) >= int(s.get("learn_every", 50)):
        learn.learn()
        state["learned_at_trades"] = closed
        progression.save(state)


@app.get("/api/progress")
def progress():
    s = settings.load()
    state = progression.load()
    mode = progression.stage_info(state["stage"])["mode"]
    if state.get("start_balance") is None:
        state["start_balance"] = _stage_balance(mode, s)
        progression.save(state)
    ev = progression.evaluate(state)
    event = None
    if ev["breach"] and ev["trades"]:
        state = progression.demote(state, f"drawdown {ev['drawdown_pct']}% passed the "
                                          f"{progression.DEFAULT_GATES[ev['stage']['id']]['max_drawdown_pct']}% limit", None)
        state["start_balance"] = _stage_balance(progression.stage_info(state["stage"])["mode"], s)
        progression.save(state)
        _restart_agent_if_running(s)
        event = {"type": "demoted", "to": progression.stage_info(state["stage"])["label"]}
    elif ev["eligible"] and not ev["needs_approval"] and s.get("auto_promote_demo", True):
        _maybe_learn(state, s, force=True)
        state = progression.promote(state, "passed the Paper gate", None)
        state["start_balance"] = _stage_balance(progression.stage_info(state["stage"])["mode"], s)
        progression.save(state)
        _restart_agent_if_running(s)
        event = {"type": "promoted", "to": progression.stage_info(state["stage"])["label"]}
    else:
        _maybe_learn(state, s)
    ev = progression.evaluate(state)
    return {**ev, "stages": progression.STAGES, "event": event, "gate": progression.DEFAULT_GATES[state["stage"]],
            "learned": learn.load_rules()}


@app.post("/api/progress/promote")
def progress_promote(body: dict = Body(default={})):
    s = settings.load()
    state = progression.load()
    ev = progression.evaluate(state)
    if not ev["eligible"]:
        raise HTTPException(400, "This stage hasn't passed its gate yet. See the checks on the Agent tab.")
    if ev["needs_approval"] and body.get("confirm") != "REAL":
        raise HTTPException(400, "Moving to real money needs your confirmation.")
    _maybe_learn(state, s, force=True)
    state = progression.promote(state, "approved by you" if ev["needs_approval"] else "passed its gate", None)
    state["start_balance"] = _stage_balance(progression.stage_info(state["stage"])["mode"], s)
    progression.save(state)
    _restart_agent_if_running(s)
    return progress()


@app.post("/api/progress/demote")
def progress_demote():
    s = settings.load()
    state = progression.demote(progression.load(), "moved back by you", None)
    state["start_balance"] = _stage_balance(progression.stage_info(state["stage"])["mode"], s)
    progression.save(state)
    _restart_agent_if_running(s)
    return progress()


# ---------- replay: run the bot on downloaded history at slider speed ----------
REPLAY_CONTROL = ROOT / "data" / "replay_control.json"
REPLAY_STATE = ROOT / "data" / "replay_state.json"


def _replay_control(update: dict | None = None) -> dict:
    try:
        ctl = json.loads(REPLAY_CONTROL.read_text())
    except (OSError, ValueError):
        ctl = {"speed": 20, "paused": False, "stop": False}
    if update:
        ctl.update({k: v for k, v in update.items() if k in ("speed", "paused", "stop")})
        REPLAY_CONTROL.parent.mkdir(exist_ok=True)
        REPLAY_CONTROL.write_text(json.dumps(ctl))
    return ctl


@app.post("/api/replay/start")
def replay_start(body: dict = Body(default={})):
    s = settings.load()
    data = ROOT / "data" / f"{s['symbol']}_M1.parquet"
    if not data.exists():
        raise HTTPException(400, "No M1 history yet. Train tab -> Fetch data first.")
    if not mt5_service.model_exists(s["symbol"]):
        raise HTTPException(400, "Train a model first (Train tab).")
    if jobs.jobs["replay"].running:
        raise HTTPException(409, "A replay is already running.")
    rate, spec = None, None
    try:
        rate = mt5_service.margin_per_lot(s["symbol"])["margin_rate"]
        spec = mt5_service.symbol_spec(s["symbol"])
    except Exception:
        pass
    args = ["-m", "agent.replay", str(data), "--symbol", s["symbol"], "--point", str(s["point"]),
            "--days", str(body.get("days", 30)), "--from", str(body.get("from", "test")),
            "--threshold", str(s["threshold"]), "--balance", str(s["paper_balance"]),
            "--stake-pct", str(s["stake_pct"]), "--sl-pct", str(s["sl_pct_of_stake"]),
            "--tp-small", str(s["tp_pct_small"]), "--tp-large", str(s["tp_pct_large"]),
            "--max-open", str(int(s["max_open_trades"])), "--ref-leverage", str(s.get("ref_leverage", 100)),
            "--sl-score-mult", str(s["sl_score_mult"])]
    if rate:
        args += ["--margin-rate", f"{rate:.6f}"]
    if spec:
        args += ["--tick-size", str(spec["tick_size"]), "--tick-value", str(spec["tick_value"]),
                 "--volume-min", str(spec["volume_min"]), "--volume-step", str(spec["volume_step"])]
    if s.get("practice", True):
        args.append("--practice")
    if not s.get("early_exit", True):
        args.append("--no-early-exit")
    if not s.get("use_learned", True):
        args.append("--no-learned")
    if body.get("fresh"):
        args.append("--fresh")
    REPLAY_STATE.unlink(missing_ok=True)
    _replay_control({"speed": body.get("speed", s.get("replay_speed", 20)), "paused": False, "stop": False})
    jobs.start("replay", args)
    return {"started": True}


@app.post("/api/replay/control")
def replay_control(body: dict = Body(default={})):
    if "speed" in body:
        settings.save({"replay_speed": body["speed"]})
    return _replay_control(body)


@app.get("/api/replay/state")
def replay_state():
    try:
        st = json.loads(REPLAY_STATE.read_text())
    except (OSError, ValueError):
        st = {"bars": []}
    st["job_running"] = jobs.jobs["replay"].running
    st["control"] = _replay_control()
    st["log"] = jobs.jobs["replay"].tail(8)
    return st


@app.post("/api/learn")
def learn_now():
    state = progression.load()
    _maybe_learn(state, settings.load(), force=True)
    return {"rules": learn.load_rules(), "analysis": learn.analyze()}


@app.get("/api/plan")
def plan(mode: str = "paper"):
    s = settings.load()
    return mt5_service.trade_plan(s["symbol"], mode, s)


@app.post("/api/{name}/stop")
def job_stop(name: str):
    if name not in jobs.jobs:
        raise HTTPException(404, "unknown job")
    jobs.stop(name)
    return jobs.status()[name]


@app.post("/api/fetch")
def fetch():
    s = settings.load()
    args = [".claude/skills/mt5-trading/scripts/fetch_m1.py", s["symbol"], "--days", str(s["days_history"]),
            "--out", f"data/{s['symbol']}_M1.parquet"]
    if s.get("terminal_path"):
        args += ["--terminal", s["terminal_path"]]
    try:
        jobs.start("fetch", args)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return jobs.status()["fetch"]


@app.post("/api/train")
def train():
    s = settings.load()
    data = ROOT / "data" / f"{s['symbol']}_M1.parquet"
    if not data.exists():
        raise HTTPException(400, f"No M1 history for {s['symbol']} yet. Click Fetch data first.")
    args = ["-m", "agent.train", str(data), "--symbol", s["symbol"], "--point", str(s["point"]),
            "--sl-pct", str(s["sl_pct_of_stake"]), "--horizon", str(int(s["label_horizon"]))]
    try:   # label with the same exits the bot will trade: needs this account's margin rate and current TP %
        p = mt5_service.trade_plan(s["symbol"], "paper", s)
        rate = 1 / float(s["ref_leverage"]) if s.get("ref_leverage") else p["margin_rate"]
        args += ["--margin-rate", f"{rate:.8f}", "--tp-pct", str(p["tp_pct"])]
    except mt5_service.MT5Unavailable:
        raise HTTPException(400, "Open MT5 first: training uses your account's margin to set the 25% stop / TP distances.")
    try:
        jobs.start("train", args)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return jobs.status()["train"]


@app.post("/api/mcp/start")
def mcp_start():
    s = settings.load()
    try:
        jobs.start("mcp", ["mcp_server/mt5_mcp.py", "--http", "--port", str(s["mcp_http_port"])])
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return jobs.status()["mcp"]


@app.get("/api/jobs/{name}/log")
def job_log(name: str, lines: int = 200):
    if name not in jobs.jobs:
        raise HTTPException(404, "unknown job")
    return {"status": jobs.status()[name], "log": jobs.jobs[name].tail(lines)}


@app.get("/api/journal")
def journal(limit: int = 200):
    s = settings.load()
    rows = []
    for mode in ("paper", "live"):
        p = LOGS / f"journal_{s['symbol']}_M1_{mode}.csv"
        if p.exists():
            with open(p, newline="") as f:
                rows += [{**r, "mode": mode} for r in csv.DictReader(f)]
    rows.sort(key=lambda r: r.get("time_utc", ""))
    return rows[-limit:]


# ---------- assistant ----------
@app.get("/api/assistant/status")
def assistant_status():
    return brain.status()


@app.post("/api/chat")
def chat(body: dict = Body(...)):
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "empty message")
    return brain.chat(text)


@app.get("/api/chat/history")
def chat_history(n: int = 60):
    return memory.recent_messages(n)


@app.delete("/api/chat/history")
def chat_clear():
    memory.clear_chat()
    return {"ok": True}


@app.get("/api/memory")
def memory_list():
    return memory.all_facts()


@app.post("/api/memory")
def memory_add(body: dict = Body(...)):
    return {"result": memory.remember(body.get("text", ""))}


@app.delete("/api/memory/{fact_id}")
def memory_del(fact_id: int):
    return {"result": memory.forget(fact_id)}


# ---------- UI ----------
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
