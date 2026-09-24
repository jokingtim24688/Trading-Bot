"""Watchdog, every 10 s inside the app: keeps the bot running and tells you when something breaks.

- The bot's process died with an error while you had it running: start it again with the same settings (at most 3
  times an hour; after that it stays stopped and says so). Stopping it yourself or the kill switch never counts.
- The bot looks stuck: running, the market is moving, but it hasn't reported for 5 minutes.
- MT5 closed, or lost its connection to the broker, for over a minute (and when it's back).

Each goes to the events feed (the app's pop-ups) and to Telegram when "watchdog" is in `telegram_events`.
"""
import json
import threading
import time

from . import mt5_service as ms
from . import watch
from .jobs import jobs
from .settings import DATA, load

CHECK_S = 10
MAX_RESTARTS_PER_HOUR = 3
STUCK_S = 300
MT5_DOWN_S = 60
_state = {"restarts": [], "gave_up": False, "stuck": False, "mt5_ok_since": None, "mt5_bad_since": None,
          "mt5_alerted": False, "last_error": ""}
_thread: threading.Thread | None = None


def _alert(kind: str, message: str):
    watch.add_event(kind, message=message, owner="bot" if kind.startswith("agent") else None)


def _last_log_line() -> str:
    lines = [x for x in jobs.jobs["agent"].tail(20).splitlines() if x.strip()]
    return lines[-1][:200] if lines else ""


def check_agent(now: float | None = None):
    now = now or time.time()
    job = jobs.jobs["agent"]
    if job.running:
        _state["gave_up"] = False
        _check_stuck(now)
        return
    if not getattr(job, "wanted", False) or job.proc is None:
        return
    code = job.proc.returncode
    if code == 0:                                   # it finished by itself (kill switch STOP file): leave it
        job.wanted = False
        return
    _state["restarts"] = [t for t in _state["restarts"] if now - t < 3600]
    if len(_state["restarts"]) >= MAX_RESTARTS_PER_HOUR:
        if not _state["gave_up"]:
            _state["gave_up"] = True
            job.wanted = False
            _alert("agent_failed", f"The bot stopped with an error {MAX_RESTARTS_PER_HOUR} times in an hour, so it "
                                   f"was left stopped. Last line: {_last_log_line() or 'see logs/agent.log'}")
        return
    why = _last_log_line()
    args = list(job.args)
    try:
        job.start(args)
        job.wanted = True
        _state["restarts"].append(now)
        _alert("agent_restart", f"The bot stopped with an error (code {code}) and was started again."
                                + (f" Last line: {why}" if why else ""))
    except Exception as e:                          # noqa: BLE001
        _state["last_error"] = str(e)


def _check_stuck(now: float):
    """Running, but no status for 5 min while the market moves (weekends and closed markets don't count)."""
    p = DATA / "agent_status.json"
    job = jobs.jobs["agent"]
    try:
        age = now - p.stat().st_mtime
    except OSError:
        age = now - (job.started or now)
    if age < STUCK_S or now - (job.started or now) < STUCK_S:
        if _state["stuck"]:
            _state["stuck"] = False
        return
    if _state["stuck"]:
        return
    try:
        status = json.loads(p.read_text())
        symbol = status.get("symbol") or load()["symbol"]
    except (OSError, ValueError):
        symbol = load()["symbol"]
    try:
        from .manual import tick_age
        with ms._lock:
            ms._ensure()
            t = ms.mt5.symbol_info_tick(symbol)
            fresh = t is not None and tick_age(symbol, t) < 120
    except Exception:                               # noqa: BLE001 - MT5 down is reported separately
        fresh = False
    if fresh:
        _state["stuck"] = True
        _alert("agent_stuck", f"The bot hasn't reported for {int(age // 60)} minutes while {symbol} is trading. "
                              "Check the Agent tab log; stop and start it if it stays quiet.")


def check_mt5(now: float | None = None):
    now = now or time.time()
    try:
        with ms._lock:
            ms._ensure()
            ok = bool(ms.mt5.terminal_info().connected)
    except ms.MT5Unavailable:
        ok = False
    except Exception:                               # noqa: BLE001
        ok = False
    if ok:
        if _state["mt5_alerted"]:
            _alert("mt5_up", "MT5 is connected to the broker again.")
        _state.update(mt5_ok_since=_state["mt5_ok_since"] or now, mt5_bad_since=None, mt5_alerted=False)
        return
    if _state["mt5_ok_since"] is None:              # never connected this session: nothing to report
        return
    _state["mt5_bad_since"] = _state["mt5_bad_since"] or now
    if not _state["mt5_alerted"] and now - _state["mt5_bad_since"] >= MT5_DOWN_S:
        _state["mt5_alerted"] = True
        _alert("mt5_down", "MT5 is closed or has lost its connection to the broker. Trades keep their SL/TP on the "
                           "broker's server, but the bot and the app can't act until it's back.")


def _loop():
    while True:
        try:
            check_mt5()
            check_agent()
        except Exception as e:                      # noqa: BLE001 - the watchdog must keep running
            _state["last_error"] = str(e)
        time.sleep(CHECK_S)


def status() -> dict:
    return {"restarts_last_hour": len([t for t in _state["restarts"] if time.time() - t < 3600]),
            "gave_up": _state["gave_up"], "stuck": _state["stuck"], "mt5_down": _state["mt5_alerted"],
            "error": _state["last_error"]}


def start():
    global _thread
    if _thread is None or not _thread.is_alive():
        _thread = threading.Thread(target=_loop, name="watchdog", daemon=True)
        _thread.start()
