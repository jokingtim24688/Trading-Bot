"""Local HTTP API + static UI for the desktop app. Bound to 127.0.0.1 only."""
import csv
import shutil
import subprocess
import time
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from agent import ledger

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
    return {"settings": s, "jobs": jobs.status(), "model_ready": mt5_service.model_exists(s["symbol"]),
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
    try:
        closed = mt5_service.close_all(AGENT_MAGIC)
        time.sleep(0.5)
        mt5_service.sync_bot_ledger()
    except mt5_service.MT5Unavailable:
        closed = []
    return {"stopped": True, "closed": closed}


# ---------- the bot's own trades ----------
def bot_trades_payload(limit: int = 100, symbol: str | None = None) -> dict:
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
    return {"open": open_, "recent": ledger.recent(limit, symbol=symbol),
            "stats": {m: ledger.stats(m) for m in ("paper", "demo", "real")}}


@app.get("/api/bot/trades")
def bot_trades(limit: int = 100, symbol: str | None = None):
    return bot_trades_payload(limit, symbol)


# ---------- jobs ----------
@app.post("/api/agent/start")
def agent_start(body: dict = Body(default={})):
    mode = body.get("mode", "paper")
    s = settings.load()
    if not mt5_service.model_exists(s["symbol"]):
        raise HTTPException(400, f"No trained model for {s['symbol']}. Go to Train and run Fetch data, then Train.")
    (ROOT / "STOP").unlink(missing_ok=True)
    args = ["-m", "agent.run", "--symbol", s["symbol"], "--threshold", str(s["threshold"]), "--risk", str(s["risk_pct"])]
    if s.get("terminal_path"):
        args += ["--terminal", s["terminal_path"]]
    if mode in ("demo", "real"):
        args.append("--live")
    if mode == "real":
        args.append("--allow-real")
    try:
        jobs.start("agent", args)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return jobs.status()["agent"]


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
    try:
        jobs.start("train", ["-m", "agent.train", str(data), "--symbol", s["symbol"], "--point", str(s["point"])])
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
