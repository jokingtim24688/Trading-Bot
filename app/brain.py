"""Assistant backends.

hermes_agent: Nous Research Hermes Agent's OpenAI-compatible API server (default :8642). Hermes keeps its own
              persistent memory, skills and tools (web, terminal, files, schedules, MCP). The MT5 MCP bridge gives
              it trading tools.
local:        a small model (default llama3.2:3b) served by Ollama on the CPU (no VRAM), with this app's file memory
              and the tools in tools.py.
auto:         hermes_agent if it answers, otherwise local.
"""
import datetime as dt
import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

import httpx

from . import memory, tools
from .settings import load

SESSION_ID = "trading-bot-app"

SYSTEM = """You are the user's trading assistant inside their Trading Bot desktop app on Windows.
The user trades MetaTrader 5 on M1 (1-minute) candles only, on a PC with a Ryzen 5 7600 and an RTX 4060.
You also help with anything else they ask: research, notes, planning, maths, explanations.

Rules:
- Use tools for live facts (account, positions, prices) instead of guessing.
- Risk first: every trade idea needs a stop; size with position_size at 0.5-1% risk.
- Explain setups and mechanics; don't promise profits or make confident buy/sell calls. Say "not financial advice" when you analyse markets.
- web_fetch only opens trading and market sites (central banks, economic calendars, gold/forex news, MT5 docs); use it
  for market research, not other topics.
- When the user tells you something worth keeping (preferences, rules, broker details, lessons), call remember.
- Be concise and specific.

What you remember about the user:
{facts}

Current time: {now}"""


class BackendError(RuntimeError):
    pass


def hermes_agent_alive(s: dict) -> bool:
    try:
        r = httpx.get(f"{s['hermes_url']}/v1/models", timeout=1.5,
                      headers={"Authorization": f"Bearer {s['hermes_key']}"} if s.get("hermes_key") else {})
        return r.status_code == 200
    except httpx.HTTPError:
        return False


def ollama_alive(s: dict) -> bool:
    try:
        return httpx.get(f"{s['ollama_url']}/api/tags", timeout=1.5).status_code == 200
    except httpx.HTTPError:
        return False


# ---------- the Hermes Agent app: start its API server by itself (in WSL on Windows) ----------

_agent = {"installed": None, "checked": 0.0, "starting": False, "error": "", "proc": None, "tried": 0.0}
AGENT_RETRY_S = 600             # after a failed start, chats don't wait on it again for 10 min (Set up retries now)


def _agent_cmd(s: dict, shell_cmd: str) -> list[str] | None:
    """How to run a shell command where Hermes Agent lives: inside WSL on Windows (optionally a named distro),
    directly elsewhere. None when there's no WSL on this Windows PC."""
    if os.name != "nt":
        return ["bash", "-lc", shell_cmd]
    wsl = shutil.which("wsl.exe") or shutil.which("wsl")
    if not wsl:
        return None
    distro = (s.get("hermes_wsl_distro") or "").strip()
    return [wsl, *(["-d", distro] if distro else []), "-e", "bash", "-lc", shell_cmd]


def hermes_agent_installed(s: dict) -> bool:
    """Is the `hermes` command there (in WSL on Windows)? Checked at most every 10 minutes (WSL is slow to ask)."""
    if _agent["installed"] is not None and time.time() - _agent["checked"] < 600:
        return _agent["installed"]
    cmd = _agent_cmd(s, "command -v hermes")
    ok = False
    if cmd:
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            ok = r.returncode == 0 and bool(r.stdout.strip())
        except (OSError, subprocess.TimeoutExpired):
            ok = False
    _agent.update(installed=ok, checked=time.time())
    return ok


def start_hermes_agent(s: dict | None = None, wait: float = 45, force: bool = False) -> bool:
    """Start Hermes Agent's gateway (its API server, the MCP tools and its own memory) in the background if it isn't
    answering. True once it answers on hermes_url."""
    s = s or load()
    if hermes_agent_alive(s):
        return True
    if force:
        _agent.update(installed=None, error="")
    elif _agent["error"] and time.time() - _agent["tried"] < AGENT_RETRY_S:
        return False
    if not hermes_agent_installed(s):
        return False
    _agent["tried"] = time.time()
    with _lock:
        running = _agent["proc"] is not None and _agent["proc"].poll() is None
        if not running:
            log = Path(__file__).resolve().parent.parent / "logs" / "hermes_gateway.log"
            log.parent.mkdir(exist_ok=True)
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            _agent.update(starting=True, error="")
            _agent["proc"] = subprocess.Popen(_agent_cmd(s, s.get("hermes_agent_cmd") or "hermes gateway"),
                                              stdout=open(log, "ab"), stderr=subprocess.STDOUT,
                                              stdin=subprocess.DEVNULL, creationflags=flags,
                                              start_new_session=os.name != "nt")
    t0 = time.time()
    try:
        while time.time() - t0 < wait:
            if hermes_agent_alive(s):
                return True
            p = _agent["proc"]
            if p is not None and p.poll() is not None:
                _agent["error"] = (f"`{s.get('hermes_agent_cmd') or 'hermes gateway'}` stopped (code {p.returncode}); "
                                   "see logs/hermes_gateway.log. Is API_SERVER_ENABLED=true in ~/.hermes/.env?")
                return False
            time.sleep(1)
        _agent["error"] = ("Hermes Agent started but its API server doesn't answer on "
                           f"{s['hermes_url']}. Check API_SERVER_ENABLED=true in ~/.hermes/.env (hermes/SETUP.md).")
        return False
    finally:
        _agent["starting"] = False


def agent_state(s: dict) -> dict:
    """The Hermes Agent app in one word: ready / starting / stopped / not_installed / error / off."""
    if hermes_agent_alive(s):
        return {"agent": "ready", "agent_step": ""}
    if s["assistant_backend"] == "local":
        return {"agent": "off", "agent_step": ""}
    if _agent["starting"]:
        return {"agent": "starting", "agent_step": "Starting Hermes Agent…"}
    if _agent["error"]:
        return {"agent": "error", "agent_step": _agent["error"]}
    if _agent["installed"] is False:
        return {"agent": "not_installed", "agent_step": "Hermes Agent isn't installed (in WSL). The small local model "
                                                        "answers instead. To use the full Hermes, see hermes/SETUP.md."}
    return {"agent": "stopped", "agent_step": "Hermes Agent isn't running. Press Set up to start it."}


# ---------- getting the local model ready by itself: start Ollama, download the model ----------

_setup = {"stage": "", "pct": 0.0, "error": "", "busy": False}
_lock = threading.Lock()


def ollama_exe() -> str | None:
    """Where Ollama is installed (PATH, or the Windows installer's default folders)."""
    found = shutil.which("ollama")
    if found:
        return found
    for base in (os.environ.get("LOCALAPPDATA"), os.environ.get("ProgramFiles")):
        if base:
            for sub in (("Programs", "Ollama", "ollama.exe"), ("Ollama", "ollama.exe")):
                p = Path(base, *sub)
                if p.exists():
                    return str(p)
    return None


def _same_model(a: str, b: str) -> bool:
    norm = lambda m: m if ":" in m else f"{m}:latest"          # noqa: E731
    return norm(a) == norm(b)


def model_ready(s: dict) -> bool:
    try:
        r = httpx.get(f"{s['ollama_url']}/api/tags", timeout=3)
        return r.status_code == 200 and any(_same_model(m.get("name", ""), s["ollama_model"])
                                            for m in r.json().get("models", []))
    except (httpx.HTTPError, ValueError):
        return False


def start_ollama(s: dict, wait: float = 20) -> bool:
    """Start `ollama serve` in the background (no window) if it isn't answering. True once it answers."""
    if ollama_alive(s):
        return True
    exe = ollama_exe()
    if not exe:
        return False
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    env = dict(os.environ)
    host = s["ollama_url"].split("://", 1)[-1].rstrip("/")
    env.setdefault("OLLAMA_HOST", host)
    subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                     creationflags=flags, env=env, start_new_session=os.name != "nt")
    t0 = time.time()
    while time.time() - t0 < wait:
        if ollama_alive(s):
            return True
        time.sleep(0.5)
    return False


def _pull(s: dict):
    """Download the model through Ollama, recording progress for the app."""
    try:
        with httpx.stream("POST", f"{s['ollama_url']}/api/pull", json={"model": s["ollama_model"], "stream": True},
                          timeout=httpx.Timeout(60, read=600)) as r:
            if r.status_code != 200:
                raise BackendError(f"Ollama couldn't download {s['ollama_model']} ({r.status_code}): {r.read()[:200]!r}")
            for line in r.iter_lines():
                if not line.strip():
                    continue
                d = json.loads(line)
                if d.get("error"):
                    raise BackendError(d["error"])
                if d.get("total"):
                    _setup["pct"] = d.get("completed", 0) / d["total"]
                _setup["stage"] = f"downloading {s['ollama_model']}"
        _setup.update(stage="ready", pct=1.0)
    except (httpx.HTTPError, BackendError, ValueError) as e:
        _setup.update(stage="", error=f"Download of {s['ollama_model']} stopped: {e}")
    finally:
        _setup["busy"] = False


def prepare(s: dict | None = None, pull: bool = True) -> dict:
    """Make the local model usable: start Ollama if it's installed, and download the model in the background if it's
    missing. Returns right away with where things stand."""
    s = s or load()
    with _lock:
        if _setup["busy"]:
            return local_state(s)
        if not ollama_alive(s):
            if not ollama_exe():
                return local_state(s)
            _setup.update(stage="starting Ollama", error="")
            if not start_ollama(s):
                _setup.update(stage="", error="Ollama is installed but didn't start. Open the Ollama app once, then try again.")
                return local_state(s)
            _setup["stage"] = ""
        if pull and not model_ready(s):
            _setup.update(busy=True, stage=f"downloading {s['ollama_model']}", pct=0.0, error="")
            threading.Thread(target=_pull, args=(s,), daemon=True).start()
    return local_state(s)


def local_state(s: dict) -> dict:
    """The local backend in one word, plus the next step for the user."""
    alive = ollama_alive(s)
    ready = alive and model_ready(s)
    model = s["ollama_model"]
    if ready:
        state, step = "ready", ""
    elif _setup["busy"] or _setup["stage"].startswith("starting"):
        state = "downloading" if _setup["busy"] else "starting"
        step = (f"Downloading {model}: {_setup['pct']:.0%}. Hermes answers as soon as it's done." if _setup["busy"]
                else "Starting Ollama…")
    elif _setup["error"]:
        state, step = "error", _setup["error"]
    elif not alive and not ollama_exe():
        state, step = "not_installed", ("Ollama isn't installed. Press Set up to install it (Windows winget), or get it "
                                       "from https://ollama.com/download, then press Set up.")
    elif not alive:
        state, step = "stopped", "Ollama isn't running. Press Set up to start it."
    else:
        size = MODEL_SIZES.get(model)
        state, step = "no_model", (f"{model} isn't downloaded yet. Press Set up to download it"
                                   + (f" (about {size}, once)." if size else " (once)."))
    return {"local": state, "next_step": step, "download_pct": round(_setup["pct"], 3) if _setup["busy"] else None}


def install_ollama() -> str:
    """Install Ollama with winget (Windows). Runs in the background; prepare() finishes the job afterwards."""
    if ollama_exe():
        return "Ollama is already installed."
    winget = shutil.which("winget")
    if not winget:
        return "winget isn't available here. Install Ollama from https://ollama.com/download, then press Set up."

    def run():
        _setup.update(busy=True, stage="installing Ollama", pct=0.0, error="")
        try:
            r = subprocess.run([winget, "install", "-e", "--id", "Ollama.Ollama", "--silent",
                                "--accept-package-agreements", "--accept-source-agreements"],
                               capture_output=True, text=True, timeout=900,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            _setup["busy"] = False
            if not ollama_exe():
                _setup.update(stage="", error=f"Installing Ollama didn't finish (winget exit {r.returncode}). "
                                              "Get it from https://ollama.com/download.")
                return
            prepare()
        except (OSError, subprocess.SubprocessError) as e:
            _setup.update(busy=False, stage="", error=f"Installing Ollama failed: {e}")

    threading.Thread(target=run, daemon=True).start()
    return "Installing Ollama in the background…"


def setup(install: bool = True) -> dict:
    """The Set up button: start the Hermes Agent app if it's installed; install Ollama if needed (and allowed), start
    it, download the model (the fallback when Hermes Agent isn't there)."""
    s = load()
    _setup["error"] = ""
    note = ""
    if s["assistant_backend"] != "local" and s.get("hermes_agent_autostart", True):
        threading.Thread(target=lambda: start_hermes_agent(s, force=True), daemon=True).start()
    if not ollama_exe() and install:
        note = install_ollama()
    else:
        prepare(s)
    return {**status(), "note": note}


def sleep() -> dict:
    """Unload the model from memory now (leaving the Hermes tab). Its memory file stays; the next message reloads it."""
    s = load()
    if not ollama_alive(s):
        return {"unloaded": False, "reason": "Ollama isn't running, so nothing is loaded"}
    try:
        httpx.post(f"{s['ollama_url']}/api/generate", json={"model": s["ollama_model"], "keep_alive": 0}, timeout=10)
        return {"unloaded": True}
    except httpx.HTTPError as e:
        return {"unloaded": False, "reason": str(e)}


def status() -> dict:
    s = load()
    agent = hermes_agent_alive(s)
    return {"backend_setting": s["assistant_backend"], "hermes_agent": agent, "ollama": ollama_alive(s),
            "model": s["ollama_model"], "device": "CPU" if s.get("ollama_cpu_only", True) else "GPU", "facts": len(memory.all_facts()),
            "installing": _setup["busy"] and _setup["stage"] == "installing Ollama", **local_state(s), **agent_state(s)}


def _ask_hermes_agent(s: dict, text: str) -> str:
    headers = {"X-Hermes-Session-Id": SESSION_ID, "X-Hermes-Session-Key": SESSION_ID}
    if s.get("hermes_key"):
        headers["Authorization"] = f"Bearer {s['hermes_key']}"
    body = {"model": "hermes-agent", "messages": [{"role": "user", "content": text}]}
    r = httpx.post(f"{s['hermes_url']}/v1/chat/completions", json=body, headers=headers,
                   timeout=httpx.Timeout(30, read=1800))   # a real task (web, terminal, files) can take a while
    if r.status_code != 200:
        raise BackendError(f"Hermes Agent returned {r.status_code}: {r.text[:300]}")
    return r.json()["choices"][0]["message"]["content"]


MODEL_SIZES = {"llama3.2:3b": "2 GB", "llama3.2:1b": "1.3 GB", "hermes3:8b": "4.7 GB", "qwen2.5:3b": "1.9 GB"}


def _options(s: dict) -> dict:
    """Model options: CPU only (num_gpu 0) keeps the RTX 4060's VRAM free for everything else."""
    opts = {"num_ctx": 8192, "temperature": 0.4}
    if s.get("ollama_cpu_only", True):
        opts["num_gpu"] = 0
    return opts


def _keep_alive(s: dict):
    """Ollama takes 0 (unload right after the reply) as a number; other values as durations like "1m"."""
    v = str(s.get("ollama_keep_alive", "0")).strip()
    return 0 if v in ("0", "0s", "0m", "") else v


def _ask_local(s: dict, text: str, trace: list) -> str:
    facts = memory.relevant_facts(text) or ["(nothing saved yet)"]
    system = SYSTEM.format(facts="\n".join(f"- {f}" for f in facts),
                           now=dt.datetime.now().strftime("%Y-%m-%d %H:%M (%A)"))
    past = memory.recent_messages(21)[:-1]      # the newest row is this message; it's appended below
    history = [{"role": m["role"], "content": m["content"]} for m in past
               if m["role"] in ("user", "assistant") and not m["content"].startswith("⚠")]   # skip setup errors
    messages = [{"role": "system", "content": system}, *history, {"role": "user", "content": text}]

    use_tools = True
    for rnd in range(7):                         # tool-use loop; the last round must answer in words
        body = {"model": s["ollama_model"], "messages": messages, "stream": False,
                "keep_alive": _keep_alive(s), "options": _options(s)}
        if use_tools and rnd < 6:
            body["tools"] = tools.schemas()
        try:
            r = httpx.post(f"{s['ollama_url']}/api/chat", json=body, timeout=httpx.Timeout(30, read=600))
        except httpx.HTTPError as e:
            raise BackendError(f"Can't reach Ollama at {s['ollama_url']} ({type(e).__name__}).")
        if r.status_code == 400 and "does not support tools" in r.text and use_tools:
            use_tools = False                    # a model without tool support: plain chat instead
            continue
        if r.status_code == 404:
            raise BackendError(f"{s['ollama_model']} isn't downloaded yet.")
        if r.status_code != 200:
            raise BackendError(f"Ollama error {r.status_code}: {r.text[:300]}")
        msg = r.json().get("message") or {}
        calls = msg.get("tool_calls") or []
        messages.append({"role": "assistant", "content": msg.get("content", ""), "tool_calls": calls} if calls
                        else {"role": "assistant", "content": msg.get("content", "")})
        if not calls:
            reply = (msg.get("content") or "").strip()
            if reply:
                return reply
            if rnd == 6:
                break
            messages.append({"role": "user", "content": "Please answer my question in words now."})
            continue
        for c in calls:
            fn = c.get("function") or {}
            name, args = fn.get("name", ""), fn.get("arguments") or {}
            result = tools.call(name, args)
            trace.append({"tool": name, "args": args, "result": result[:400]})
            messages.append({"role": "tool", "content": result, "tool_name": name})
    return "I stopped after several tool calls without a final answer. Try asking more specifically."


def _local_not_ready(s: dict) -> str | None:
    """Why the local model can't answer yet (after trying to fix it), or None when it can."""
    if ollama_alive(s) and model_ready(s):
        return None
    if s.get("assistant_autosetup", True):
        prepare(s)
        if ollama_alive(s) and model_ready(s):
            return None
    return local_state(s)["next_step"] or "The local model isn't ready yet."


def chat(text: str) -> dict:
    s = load()
    choice = s["assistant_backend"]
    if choice in ("auto", "hermes_agent") and s.get("hermes_agent_autostart", True) and not hermes_agent_alive(s):
        start_hermes_agent(s)                    # the full Hermes app first, when it's installed
    if choice == "auto":
        choice = "hermes_agent" if hermes_agent_alive(s) else "local"
    trace: list = []
    memory.add_message("user", text)
    try:
        if choice == "hermes_agent":
            try:
                reply = _ask_hermes_agent(s, text)
            except (BackendError, httpx.HTTPError, KeyError, ValueError) as e:
                if s["assistant_backend"] != "auto":
                    raise BackendError(f"Hermes Agent didn't answer ({e}). Is `hermes gateway` running?")
                choice = "local"                 # auto: fall back to the local model
                reply = None
            if reply is None:
                why = _local_not_ready(s)
                if why:
                    raise BackendError(why)
                reply = _ask_local(s, text, trace)
        else:
            why = _local_not_ready(s)
            if why:
                raise BackendError(why)
            reply = _ask_local(s, text, trace)
    except BackendError as e:
        reply = f"⚠ {e}"
    memory.add_message("assistant", reply)
    return {"reply": reply, "backend": choice, "tools": trace}
