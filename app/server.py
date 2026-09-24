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
from agent.pro import SETUP_NAMES

from . import backup, brain, manual, memory, mt5_service, review, settings, sounds, stats, telegram, watch, watchdog
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


@app.post("/api/settings/backup")
def settings_backup():
    """Save a copy of the settings to data/backups/ (the window can't download files, so the app writes them)."""
    return settings.backup()


@app.get("/api/settings/backups")
def settings_backups():
    return settings.backups()


@app.post("/api/settings/restore")
def settings_restore(body: dict = Body(...)):
    """{name} restores a backup; {settings: {...}} restores from a file you picked. Backs up the current ones first."""
    return settings.restore(body.get("name"), body.get("settings"))


# ---------- your own alert sounds (Sounds page) ----------
@app.get("/api/sounds")
def sounds_list():
    return sounds.listing()


@app.post("/api/sounds")
def sounds_add(body: dict = Body(...)):
    """{name, type, data (base64)} -> the new sound. 413 over 5 MB, 415 if it isn't wav/mp3/ogg/m4a/aac/flac/webm."""
    try:
        return sounds.add(body.get("name"), body.get("type") or "", body.get("data"))
    except sounds.TooBig as e:
        raise HTTPException(413, str(e))
    except sounds.NotAudio as e:
        raise HTTPException(415, str(e))


def _sound(sid: str):
    try:
        return sounds.file(sid)
    except KeyError:
        raise HTTPException(404, "no such sound")


@app.get("/api/sounds/{sid}")
def sounds_get(sid: str):
    path, ctype = _sound(sid)
    return FileResponse(path, media_type=ctype)


@app.post("/api/sounds/{sid}/rename")
def sounds_rename(sid: str, body: dict = Body(...)):
    _sound(sid)
    return sounds.rename(sid, body.get("name"))


@app.delete("/api/sounds/{sid}")
def sounds_delete(sid: str):
    _sound(sid)
    return sounds.delete(sid)


# ---------- Telegram alerts ----------
@app.get("/api/telegram/status")
def telegram_status():
    return telegram.status()


@app.post("/api/telegram/detect")
def telegram_detect():
    """After you message your bot: find your chat id, save it, and send a hello."""
    return telegram.detect()


@app.post("/api/telegram/test")
def telegram_test():
    return telegram.test()


# ---------- full data backup ----------
@app.get("/api/backup/data")
def backup_status():
    return backup.status()


@app.post("/api/backup/data")
def backup_make():
    """Zip the trade ledger, memory, lessons, notes, reviews, sounds and models now."""
    return backup.make()


# ---------- first-run checklist ----------
@app.get("/api/setup/checklist")
def setup_checklist():
    s = settings.load()
    sym = s["symbol"]
    items = []

    def add(id_, label, ok, detail="", action=None, optional=False):
        items.append({"id": id_, "label": label, "ok": bool(ok), "detail": detail, "action": None if ok else action,
                      **({"optional": True} if optional else {})})

    try:
        acct = mt5_service.account()
        add("mt5", "MetaTrader 5 connected", acct["connected"],
            f"{acct['server']}, ping {acct['ping_ms']} ms" if acct["connected"] else "terminal open but not connected to the broker")
        add("account", "Logged in to an account", bool(acct["login"]), "demo" if acct["demo"] else "real")
    except Exception as e:                          # noqa: BLE001 - MT5 missing or closed
        add("mt5", "MetaTrader 5 connected", False, str(e))
        add("account", "Logged in to an account", False, "open MetaTrader 5 and log in")
    data = ROOT / "data" / f"{sym}_M1.parquet"
    add("data", f"{sym} M1 candles downloaded", data.exists(),
        time.strftime("%Y-%m-%d", time.localtime(data.stat().st_mtime)) if data.exists() else "", "/api/fetch")
    hist = ROOT / "data" / f"{sym}_M1_history.parquet"
    add("history", "Extra years of history", hist.exists(), "" if hist.exists() else "optional, gold only",
        "/api/history/download", optional=True)
    add("model", "Model trained", mt5_service.model_exists(sym), "", "/api/train")
    try:
        st = brain.status()
        ready = st["hermes_agent"] if s["assistant_backend"] == "hermes_agent" else st.get("local") == "ready"
        add("hermes", "Hermes ready", ready, st.get("next_step") or st.get("local") or "", "/api/assistant/setup")
    except Exception as e:                          # noqa: BLE001
        add("hermes", "Hermes ready", False, str(e), "/api/assistant/setup")
    add("mcp", "MCP bridge running", jobs.jobs["mcp"].running, f"port {s['mcp_http_port']}", "/api/mcp/start")
    try:
        from agent import quiz as q
        good = int(q._load_json(q.BANK_META, {}).get("good") or 0)
    except Exception:                               # noqa: BLE001
        good = 0
    add("quiz", "Quiz question bank", good > 0, f"{good:,} questions" if good else "being made in the background",
        None, optional=True)
    return {"done": sum(i["ok"] for i in items), "total": len(items), "items": items}


# ---------- MT5 ----------
@app.get("/api/account")
def account():
    return mt5_service.account()


@app.get("/api/positions")
def positions():
    return mt5_service.positions()


@app.get("/api/bars")
def bars(symbol: str, count: int = 240, before: int | None = None):
    return mt5_service.m1_bars(symbol, min(count, 2000), before)   # before: only candles older than this (chart history)


@app.get("/api/size")
def size(symbol: str, entry: float, stop: float, risk: float = 0.5):
    return mt5_service.lots_for_risk(symbol, entry, stop, risk)


@app.post("/api/positions/{ticket}/close")
def close(ticket: int):
    for t in ledger.open_trades():                  # a bot trade you close from the app is scored as a manual close
        if t["ticket"] == ticket:
            ledger.set_close_hint(t["id"], "manual (app)")
    return mt5_service.close_position(ticket)


# ---------- manual trading (Manual tab): what the MT5 mobile app does ----------
@app.get("/api/manual/quote")
def manual_quote(symbol: str):
    return manual.quote(symbol)


@app.get("/api/manual/quotes")
def manual_quotes(symbols: str):
    return manual.quotes([x.strip() for x in symbols.split(",") if x.strip()][:50])


@app.post("/api/manual/order")
def manual_order(body: dict = Body(...)):
    keys = ("symbol", "side", "type", "volume", "price", "sl", "tp", "deviation", "expiration", "confirm_real",
            "sl_points", "tp_points", "be_points", "trail_points", "ignore_spread",
            "note", "tags")
    return manual.order(**{k: body[k] for k in keys if k in body and body[k] is not None})


@app.post("/api/manual/close")
def manual_close(body: dict = Body(default={})):
    return manual.close(body.get("tickets"), body.get("volume"), body.get("filter") or "all",
                        body.get("owner") or "any", body.get("symbol"))


@app.post("/api/manual/modify")
def manual_modify(body: dict = Body(...)):
    return manual.modify(int(body["ticket"]), body.get("sl"), body.get("tp"))


@app.get("/api/manual/orders")
def manual_orders():
    return manual.orders()


@app.post("/api/manual/orders/cancel")
def manual_cancel(body: dict = Body(default={})):
    return manual.cancel(body.get("tickets"), bool(body.get("all")))


@app.get("/api/manual/history")
def manual_history(days: float = 1):
    return manual.history(min(max(days, 0.01), 90))


@app.get("/api/manual/notes")
def manual_notes():
    """Your notes on trades: {"<ticket>": {note, tags, time}}."""
    return manual.notes()


@app.post("/api/manual/notes")
def manual_note_set(body: dict = Body(...)):
    if "ticket" not in body:
        raise HTTPException(400, "ticket is required")
    return manual.set_note(body["ticket"], body.get("note"), body.get("tags"))


@app.get("/api/manual/auto")
def manual_auto_get():
    """Trailing stop / auto break-even: the defaults and the rule on each open position or pending order."""
    return watch.rules_state()


@app.post("/api/manual/auto")
def manual_auto_set(body: dict = Body(...)):
    if "ticket" not in body:
        raise HTTPException(400, "ticket is required")
    return watch.set_rule(body["ticket"], body.get("be_points"), body.get("trail_points"))


# ---------- alerts, stats, weekly review ----------
@app.get("/api/watchdog")
def watchdog_status():
    return watchdog.status()


@app.get("/api/events")
def events(since: int | None = None):
    """Trades opened, TP/SL hits, closes and automatic stop moves, for every owner. Poll with the last id you saw."""
    return watch.events(since)


@app.get("/api/stats/compare")
def stats_compare(days: float = 30, mode: str | None = None):
    if mode not in (None, "", "paper", "live", "all", "demo", "real", "replay"):
        raise HTTPException(400, "mode must be paper, live or all")
    return stats.compare(max(days, 0), mode or None)


@app.get("/api/stats/quiz")
def stats_quiz(days: float = 0, mode: str = "all"):
    """Does the quiz agent's second opinion help? Bot trades split by agree / disagree / no opinion, and a verdict."""
    if mode not in ("paper", "live", "all", "demo", "real", "replay"):
        raise HTTPException(400, "mode must be paper, live, replay or all")
    return stats.quiz_agreement(max(days, 0), mode)


@app.get("/api/news")
def news_calendar():
    """Upcoming high-impact news, and whether the bot is paused for news right now."""
    from agent import news
    return news.summary(settings.load())


@app.get("/api/review/weekly")
def review_weekly(week: str | None = None):
    return review.get(week)


@app.post("/api/review/weekly")
def review_weekly_make(body: dict = Body(default={})):
    return review.regenerate(body.get("week"))


@app.get("/api/review/weeks")
def review_weeks():
    return review.weeks()


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
        mt5_service.sync_bot_ledger(force=True)
    except mt5_service.MT5Unavailable:
        closed = []
    return {"stopped": True, "closed": closed}


# ---------- the bot's own trades ----------
def bot_trades_payload(limit: int = 100, symbol: str | None = None) -> dict:
    scoring.SL_MULT = float(settings.load().get("sl_score_mult", 1.5))
    try:
        mt5_service.sync_bot_ledger()           # at most every 2 s; closes mark it stale so they show at once
    except Exception:
        pass                                    # MT5 offline: show the ledger as last recorded
    open_ = ledger.open_trades(symbol=symbol)
    try:
        floating = mt5_service.floating_for(open_)
    except Exception:
        floating = {}
    for t in open_:
        t.update(floating.get(t["id"], {"pnl": None, "price": None}))
    recent = ledger.recent(limit, symbol=symbol)
    for t in open_ + recent:                    # the names the History replay uses; server-time epochs like /api/bars
        t.update(entry_time=t["open_bar"], exit_time=t["close_bar"])
    status = None
    if jobs.jobs["agent"].running:
        try:
            status = json.loads((ROOT / "data" / "agent_status.json").read_text())
        except (OSError, ValueError):
            status = {"decision": "starting", "reason": "waiting for the next 1-minute candle to close"}
    return {"open": open_, "recent": recent,
            "stats": {m: ledger.stats(m) for m in ("replay", "paper", "demo", "real")}, "agent": status,
            "setup_names": SETUP_NAMES}


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
    if s.get("quiz_filter"):
        args.append("--quiz-filter")
    if s.get("news_pause", True):
        args += ["--news-before", str(s.get("news_before_min", 15)), "--news-after", str(s.get("news_after_min", 15)),
                 "--news-currencies", ",".join(s.get("news_currencies") or ["USD"]),
                 "--news-impact", ",".join(s.get("news_impact") or ["High"])]
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
    if not data.exists() and not (ROOT / "data" / f"{s['symbol']}_M1_history.parquet").exists():
        raise HTTPException(400, "No M1 history yet. Train tab -> Fetch data or Download history first.")
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
    if s.get("quiz_filter"):
        args.append("--quiz-filter")
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


# ---------- quiz school: reinforcement learning on real pro setups ----------
QUIZ_DIR = ROOT / "data"


@app.post("/api/quiz/build")
def quiz_build(body: dict = Body(default={})):
    s = settings.load()
    n = int(body.get("questions", 40) or 0)            # no maximum; 0 = every usable question in the bank
    n = 0 if n <= 0 else max(34, n)
    try:
        (QUIZ_DIR / "quiz_build.json").unlink(missing_ok=True)
        jobs.start("quiz", ["-m", "agent.quiz", "build", "--symbol", s["symbol"], "--questions", str(n), "--point", str(s["point"]),
                            "--workers", str(int(s.get("quiz_workers", 0) or 0))])
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return {"started": True}


@app.post("/api/quiz/train")
def quiz_train(body: dict = Body(default={})):
    s = settings.load()
    if not (QUIZ_DIR / "quiz.json").exists():
        raise HTTPException(400, "Build the quiz first.")
    speed = body.get("speed", s.get("quiz_speed", 0))
    (QUIZ_DIR / "quiz_control.json").write_text(json.dumps({"speed": speed, "stop": False}))
    args = ["-m", "agent.quiz", "train"]
    focus = [int(v) for v in body.get("focus") or []]
    if focus:                                          # work only on the questions picked on the board
        args += ["--focus", ",".join(map(str, focus))]
    elif body.get("resume"):
        args.append("--resume")
    else:                                              # Start over: fresh agent and fresh progress
        (QUIZ_DIR / "quiz_progress.npz").unlink(missing_ok=True)
    if not s.get("quiz_refresh", True):
        args.append("--no-refresh")
    (QUIZ_DIR / "quiz_state.json").unlink(missing_ok=True)
    try:
        jobs.start("quiz", args)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return {"started": True}


@app.post("/api/quiz/control")
def quiz_control(body: dict = Body(default={})):
    p = QUIZ_DIR / "quiz_control.json"
    try:
        ctl = json.loads(p.read_text())
    except (OSError, ValueError):
        ctl = {"speed": 100, "stop": False}
    ctl.update({k: v for k, v in body.items() if k in ("speed", "stop")})
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps(ctl))
    if "speed" in body:
        settings.save({"quiz_speed": body["speed"]})
    return ctl


@app.get("/api/quiz/state")
def quiz_state():
    from agent import quiz as q
    st = q._load_json(q.STATE, {})
    qz = q._load_json(q.QUIZ, None)
    pol = q.load_policy()
    return {"state": st, "control": q.read_control(), "job_running": jobs.jobs["quiz"].running,
            "build": q._load_json(q.BUILD_STATE, None),
            "bank": {**q._load_json(q.BANK_META, {}), **q._load_json(q.BANK_STATUS, {}), "mean": None, "std": None,
                     "columns": None, "slices": None, "watcher": jobs.jobs["bank"].running},
            "quiz": None if not qz else {"built": qz["built"], "count": len(qz["questions"]), "points": qz["points"],
                                         "practice": sum(x["set"] == "practice" for x in qz["questions"])},
            "policy": pol.meta if pol else None}


@app.get("/api/quiz/labels")
def quiz_labels():
    """Setup + answer per practice question (compact), for the mastery board's hover labels."""
    from agent import quiz as q
    qz = q._load_json(q.QUIZ, None)
    if not qz:
        return {"built": None, "names": [], "ids": [], "setups": [], "answers": [], "difficulty": []}
    prac = [x for x in qz["questions"] if x["set"] == "practice"]
    label = [q.setup_name(x["setup"], x.get("trap")) for x in prac]
    names = sorted(set(label))
    where = {nm: k for k, nm in enumerate(names)}
    return {"built": qz["built"], "names": names, "ids": [x["id"] for x in prac], "setups": [where[nm] for nm in label],
            "answers": [x["answer"] for x in prac], "difficulty": [x.get("difficulty", "") for x in prac]}


@app.post("/api/quiz/wipe")
def quiz_wipe():
    """Delete every quiz question and its progress (stops a running quiz first). The trained agent is kept."""
    from agent import quiz as q, quiz_report as rp
    jobs.stop("quiz")
    removed = 0
    for f in (q.QUIZ, q.QX, q.QBARS, q.QTIMES, q.QC, q.PROGRESS, q.STATE, q.CONTROL, q.BUILD_STATE,
              rp.REPORT_JSON, rp.REPORT_MD, *q.DATA.glob("quiz_build_w*.json")):      # the finder cache is kept
        if f.exists():
            f.unlink()
            removed += 1
    return {"wiped": True, "files": removed}


@app.get("/api/quiz/report")
def quiz_report_get():
    """The weak-spot report: what the quiz agent gets stuck on (made by the quiz every 5 minutes and after each run)."""
    from agent import quiz as q, quiz_report as rp
    stale = not rp.REPORT_JSON.exists() or (q.PROGRESS.exists() and not jobs.jobs["quiz"].running
                                            and rp.REPORT_JSON.stat().st_mtime < q.PROGRESS.stat().st_mtime)
    if stale:
        try:
            rp.make_report()
        except Exception:                               # noqa: BLE001 - a missing or old quiz just means no report yet
            pass
    return {"report": q._load_json(rp.REPORT_JSON, None),
            "markdown": rp.REPORT_MD.read_text(encoding="utf-8") if rp.REPORT_MD.exists() else ""}


@app.post("/api/quiz/report")
def quiz_report_make():
    from agent import quiz_report as rp
    try:
        rep = rp.make_report()
    except Exception as e:                              # noqa: BLE001
        raise HTTPException(500, f"Couldn't make the report: {e}")
    if rep is None:
        raise HTTPException(400, "No quiz progress yet: build a quiz and run it first.")
    return {"report": rep, "markdown": rp.REPORT_MD.read_text(encoding="utf-8")}


@app.get("/api/quiz/question/{qid}")
def quiz_question(qid: int):
    from agent import quiz as q
    v = q.question_view(qid)
    if not v:
        raise HTTPException(404, "No such question.")
    return v


@app.post("/api/quiz/ask")
def quiz_ask():
    """Show the quiz agent the live market and ask what it would do."""
    import pandas as pd
    from agent import quiz as q
    from agent.features import build_features
    from agent.pro import SETUP_NAMES, active_setups
    pol = q.load_policy()
    if not pol:
        raise HTTPException(400, "Train the quiz agent first.")
    s = settings.load()
    d = mt5_service.m1_bars(s["symbol"], 4000)
    df = pd.DataFrame(d["bars"])
    if len(df) < 300:
        raise HTTPException(400, "Not enough M1 candles from MT5 yet.")
    df.index = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.rename(columns={"volume": "tick_volume"})
    row = build_features(df, d["point"]).iloc[-1].to_dict()
    ans = pol.answer_row(row, df[["open", "high", "low", "close"]].to_numpy()[-90:])
    return {**ans, "setups": [SETUP_NAMES[k] for k in active_setups(row)], "bar_time": int(df["time"].iloc[-1]),
            "price": d["bid"], "bars": d["bars"][-90:]}


@app.post("/api/history/download")
def history_download(body: dict | None = None):
    """Years of free XAUUSD M1 candles (HistData) so the model trains on far more than MT5 keeps."""
    s = settings.load()
    years = max(1, min(17, int((body or {}).get("years", 5))))
    try:
        jobs.start("history", ["-m", "agent.history", "--symbol", s["symbol"], "--years", str(years)])
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return jobs.status()["history"]


@app.post("/api/train")
def train():
    s = settings.load()
    data = ROOT / "data" / f"{s['symbol']}_M1.parquet"
    if not data.exists() and not (ROOT / "data" / f"{s['symbol']}_M1_history.parquet").exists():
        raise HTTPException(400, f"No M1 history for {s['symbol']} yet. Click Fetch data or Download history first.")
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


@app.post("/api/assistant/sleep")
def assistant_sleep():
    """Unload Hermes's model from RAM/VRAM now (called when you leave the Hermes tab). Memory stays on disk."""
    return brain.sleep()


@app.post("/api/assistant/setup")
def assistant_setup(body: dict = Body(default={})):
    """Set up the local model: install Ollama (winget) if missing, start it, download the model."""
    return brain.setup(install=bool(body.get("install", True)))


@app.on_event("startup")
def _watchers():
    """The 1 s watcher (trailing stop, break-even, alerts) and the weekly review, both inside the app."""
    watch.start()
    review.start()
    backup.start()
    watchdog.start()


@app.on_event("startup")
def _question_bank():
    """One question creator keeps the quiz question bank up to date at all times (below normal priority)."""
    s = settings.load()
    if s.get("quiz_bank_auto", True) and not jobs.jobs["bank"].running:
        try:
            jobs.start("bank", ["-m", "agent.quiz", "bank", "--watch", "--symbol", s["symbol"], "--point", str(s["point"])])
        except RuntimeError:
            pass


@app.on_event("startup")
def _assistant_warmup():
    """Start Ollama and fetch the model in the background as the app opens, so Hermes is ready when you need it."""
    import threading
    s = settings.load()
    if s.get("assistant_autosetup", True) and s["assistant_backend"] != "hermes_agent":
        threading.Thread(target=lambda: brain.prepare(s), daemon=True).start()
    if s["assistant_backend"] != "local" and s.get("hermes_agent_autostart", True):     # the full Hermes app, if installed
        threading.Thread(target=lambda: brain.start_hermes_agent(s), daemon=True).start()


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
