"""Assistant backends.

hermes_agent: Nous Research Hermes Agent's OpenAI-compatible API server (default :8642). Hermes keeps its own
              persistent memory, skills and tools (web, terminal, files, schedules, MCP). The MT5 MCP bridge gives
              it trading tools.
local:        a Hermes model (default hermes3:8b) served by Ollama on the RTX 4060, with this app's SQLite memory
              and the tools in tools.py.
auto:         hermes_agent if it answers, otherwise local.
"""
import datetime as dt

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


def status() -> dict:
    s = load()
    return {"backend_setting": s["assistant_backend"], "hermes_agent": hermes_agent_alive(s),
            "ollama": ollama_alive(s), "model": s["ollama_model"], "facts": len(memory.all_facts())}


def _ask_hermes_agent(s: dict, text: str) -> str:
    headers = {"X-Hermes-Session-Id": SESSION_ID, "X-Hermes-Session-Key": SESSION_ID}
    if s.get("hermes_key"):
        headers["Authorization"] = f"Bearer {s['hermes_key']}"
    body = {"model": "hermes-agent", "messages": [{"role": "user", "content": text}]}
    r = httpx.post(f"{s['hermes_url']}/v1/chat/completions", json=body, headers=headers, timeout=300)
    if r.status_code != 200:
        raise BackendError(f"Hermes Agent returned {r.status_code}: {r.text[:300]}")
    return r.json()["choices"][0]["message"]["content"]


def _ask_local(s: dict, text: str, trace: list) -> str:
    facts = memory.relevant_facts(text) or ["(nothing saved yet)"]
    system = SYSTEM.format(facts="\n".join(f"- {f}" for f in facts),
                           now=dt.datetime.now().strftime("%Y-%m-%d %H:%M (%A)"))
    past = memory.recent_messages(13)[:-1]      # the newest row is this message; it's appended below
    history = [{"role": m["role"], "content": m["content"]} for m in past if m["role"] in ("user", "assistant")]
    messages = [{"role": "system", "content": system}, *history, {"role": "user", "content": text}]

    for _ in range(6):                           # tool-use loop
        body = {"model": s["ollama_model"], "messages": messages, "tools": tools.schemas(), "stream": False,
                "keep_alive": s["ollama_keep_alive"], "options": {"num_ctx": 8192, "temperature": 0.4}}
        try:
            r = httpx.post(f"{s['ollama_url']}/api/chat", json=body, timeout=300)
        except httpx.HTTPError as e:
            raise BackendError(f"Can't reach Ollama at {s['ollama_url']} ({e}). Start Ollama, then run: ollama pull {s['ollama_model']}")
        if r.status_code == 404:
            raise BackendError(f"Model {s['ollama_model']} isn't downloaded. Run: ollama pull {s['ollama_model']}")
        if r.status_code != 200:
            raise BackendError(f"Ollama error {r.status_code}: {r.text[:300]}")
        msg = r.json()["message"]
        calls = msg.get("tool_calls") or []
        messages.append({"role": "assistant", "content": msg.get("content", ""), "tool_calls": calls} if calls
                        else {"role": "assistant", "content": msg.get("content", "")})
        if not calls:
            return msg.get("content", "").strip()
        for c in calls:
            name, args = c["function"]["name"], c["function"].get("arguments", {})
            result = tools.call(name, args)
            trace.append({"tool": name, "args": args, "result": result[:400]})
            messages.append({"role": "tool", "content": result, "tool_name": name})
    return "I stopped after several tool calls without a final answer. Try asking more specifically."


def chat(text: str) -> dict:
    s = load()
    choice = s["assistant_backend"]
    if choice == "auto":
        choice = "hermes_agent" if hermes_agent_alive(s) else "local"
    trace: list = []
    memory.add_message("user", text)
    try:
        reply = _ask_hermes_agent(s, text) if choice == "hermes_agent" else _ask_local(s, text, trace)
    except BackendError as e:
        reply = f"⚠ {e}"
    memory.add_message("assistant", reply)
    return {"reply": reply, "backend": choice, "tools": trace}
