# Desktop App & Hermes

The user prefers the app over typing commands. Describe actions as "tab → button".

## Launch
Double-click `Trading Bot.bat` in the repo folder. The first run creates `.venv` and installs `requirements.txt`
(a few minutes). After that it opens a native window (pywebview) or the default browser at `http://127.0.0.1:8420`.
MetaTrader 5 must be open and logged in, with Algo Trading on (Ctrl+E) for demo/real agent modes.

## Tabs
| Tab | What's there | Maps to |
|---|---|---|
| Market | M1 candle chart for the watchlist, live quote and spread, "Size a trade" calculator, open positions with Close buttons, **hold-to-flatten** kill switch | `app/mt5_service.py`, `/api/kill` |
| Agent | Paper / Demo / Real (Real locked until unlocked in Settings), threshold and risk sliders, Start/Stop, live log, journal table | `python -m agent.run` |
| Train | Fetch data (M1 history → `data/<SYMBOL>_M1.parquet`), Train (XGBoost on the RTX 4060, prints out-of-sample table), then Open Agent | `fetch_m1.py`, `python -m agent.train` |
| Hermes | Chat assistant with memory, suggested prompts, Memory panel (add/forget facts) | `app/brain.py`, `app/memory.py`, `app/tools.py` |
| Settings | Symbol, watchlist, terminal path, point size, history days, Hermes backend/URLs/key/model, VRAM idle unload, web access, MCP bridge autostart | `data/settings.json` |

Top bar: demo/real badge, equity (counts up on open), floating P/L, free margin, RAM and VRAM meters, agent state.

## Hermes backends
- **Local**: `hermes3:8b` in Ollama on the 4060. Tools: account, positions, M1 market summary, position size,
  agent status/start/stop, remember/recall, web_fetch, notes, calculate, time. No order placement (by design).
- **Hermes Agent** (Nous Research, runs in WSL2): OpenAI-compatible API server on :8642 with its own persistent
  memory and skills, plus the MT5 MCP bridge (`http://localhost:8765/mcp`) for full trading tools, including orders with a risk guard.
- **Auto**: Hermes Agent if reachable, else local.
Setup steps: `hermes/SETUP.md`. Seed memory: `hermes/user_seed.md`.

## Disk vs RAM
Running code must be in RAM. Everything persistent is on disk: `data/` (settings, memory.db, notes, M1 history),
`logs/` (job logs, journals), `models/`. The Hermes model sits in VRAM and unloads after the idle time in Settings.

## Troubleshooting
| Symptom | Fix |
|---|---|
| Badge says "MT5 offline" | Open MT5 and log in; set the terminal path in Settings if you have several installs |
| "No trained model" on Start | Train tab → Fetch data → Train |
| Hermes pill "Ollama not running" | Start Ollama; `ollama pull hermes3:8b` |
| Hermes pill "Hermes Agent not running" | In WSL: `hermes gateway`; check API key in Settings |
| Agent log shows retcode 10027 | Algo Trading button off in MT5 (Ctrl+E) |
