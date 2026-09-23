# Desktop app (`app/`)
- **main.py**: picks port 8420 (or free), runs uvicorn in a thread, opens a pywebview window (browser fallback), autostarts the MCP bridge, and stops all jobs on close.
- **server.py**: FastAPI. Routes: `/api/status` (settings, jobs, model/data ready, RAM/VRAM via psutil + nvidia-smi), `/api/settings`, `/api/account`, `/api/positions`, `/api/bars` (M1), `/api/size`, `/api/positions/{ticket}/close`, `/api/kill`, `/api/agent/start`, `/api/{job}/stop`, `/api/fetch`, `/api/train`, `/api/mcp/start`, `/api/jobs/{name}/log`, `/api/journal`, `/api/assistant/status`, `/api/chat`, `/api/chat/history`, `/api/memory`. MT5Unavailable → 503; ValueError → 400.
- **mt5_service.py**: locked MetaTrader5 wrapper (account, positions, m1_bars, symbol_spec, close_position, close_all, lots_for_risk, model_exists).
- **jobs.py**: `Job`/`JobManager` subprocesses (agent, train, fetch, mcp), logs to `logs/<job>.log`, tail reader.
- **settings.py**: DEFAULTS + load/save to `data/settings.json`.
- **static/**: `index.html` (tabs Market, Agent, Train, Hermes, Settings), `app.css` (graphite + brass gold palette, IBM Plex, glass only on rail/strip/toast), `app.js` (polling, chart via vendored lightweight-charts 4.2.0, hold-to-flatten, sizing calculator, chat, memory).
- Tested: API via TestClient; UI screenshots with mocked MT5 data.
