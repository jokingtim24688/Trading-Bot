# Trading-Bot Knowledge Graph: Wiki Index

> Hand-built map in graphify's wiki layout (the `graphify` CLI couldn't be installed in the cloud session).
> To regenerate automatically on your PC: `pip install graphifyy`, then run graphify on the repo (use its `--wiki` option).
> Start here for any question about this repo, and open the linked page for detail.

**Two chats work on this repo at once.** Read [TWO_CHATS.md](../../TWO_CHATS.md) before changing anything: lanes
(A / chat 1 = backend & skills, B / chat 2 = UI & polish), the shared branch `claude/laughing-bell-3vt2c7`, and the git routine.

## Communities (subsystems)
| Community | Page | Core nodes | Lane |
|---|---|---|---|
| Desktop app | [app.md](app.md) | `app/main.py`, `app/server.py`, `app/static/*` | B: static + window · A: server, jobs, settings |
| Hermes assistant + memory | [hermes.md](hermes.md) | `app/brain.py`, `app/memory.py`, `app/tools.py`, `hermes/` | A |
| M1 trading agent | [agent.md](agent.md) | `agent/run.py`, `agent/features.py`, `agent/model.py`, `agent/risk.py`, `agent/broker.py` | A |
| MT5 MCP bridge | [mcp.md](mcp.md) | `mcp_server/mt5_mcp.py` | A |
| mt5-trading skill + Claude subagent | [skill.md](skill.md) | `.claude/skills/mt5-trading/`, `.claude/agents/mt5-m1-trader.md` | A |

## God nodes (most connected)
1. **MetaTrader5 terminal** (external): used by `app/mt5_service.py`, `agent/broker.py`, `mcp_server/mt5_mcp.py`, `scripts/fetch_m1.py`, `scripts/position_size.py`
2. **`app/settings.py` → `data/settings.json`**: read by server, jobs, brain, tools, mt5_service
3. **`agent/ledger.py`**: bot trade ledger read/written by agent brokers, app server, Hermes tool
4. **`agent/features.py`**: `build_features`/`triple_barrier`/`atr` used by train and run
5. **`app/jobs.py` JobManager**: runs agent, train, fetch, and mcp subprocesses for the UI and the Hermes tools
6. **M1 lock**: `TIMEFRAME = "M1"` (agent/config.py), `TF = mt5.TIMEFRAME_M1` (mcp), `PERIOD_M1` (MQL5 docs)

## Key flows
- **Launch**: `Trading Bot.bat` (git pull, pip only if requirements changed, pythonw, window closes) → `.venv` → `app.main` → uvicorn (127.0.0.1:8420) + pywebview window → auto-start MCP bridge (:8765).
- **Train**: Train tab → `/api/fetch` → `fetch_m1.py` → `data/SYMBOL_M1.parquet` → `/api/train` → `agent.train` → `models/SYMBOL_M1.json`.
- **Trade**: Agent tab → `/api/agent/start` → `agent.run` → closed-bar poll → features → XGBoost proba → `RiskGate` → Paper/LiveBroker → `logs/journal_*.csv`.
- **Chat**: Hermes tab → `/api/chat` → `brain.chat` → Hermes Agent (:8642) *or* Ollama `llama3.2:3b` (CPU) + `tools.py` → `data/hermes_memory.json`.
- **Follow the bot**: `agent.run` → `ledger` (`data/trades.db`) ← `sync_ledger` (agent every 1s, app every refresh) → `/api/bot/trades` → Market *Bot trade* card, chart lines/markers, alerts; Agent *Bot trades* table; Hermes `get_bot_trades`.
- **Kill**: hold button → `/api/kill` → STOP file → agent flattens → `close_all(magic 260923)`.

## Files on disk (not RAM)
`data/` settings.json, hermes_memory.json, trades.db (bot ledger), notes/, SYMBOL_M1.parquet · `logs/` job logs + journals · `models/` XGBoost JSON + meta.

## Other
- `simulation/bot-simulation.html`: standalone simulated trading session (synthetic prices, real stake rules); published artifact https://claude.ai/artifact/2NHXbvdi3XurmF51kRbEzw
- [Progress.md](../../Progress.md): session log of work done; since 2026-09-24 one section per chat at the end.
- [TWO_CHATS.md](../../TWO_CHATS.md): how the two chats split the work and share the branch; `CLAUDE.md` points every
  new chat to it.
- Hardware: Ryzen 5 7600 (6C/12T, AVX-512), RTX 4060 8 GB. See [agent.md](agent.md#hardware).

- 2026-09-23: extra history (agent/history.py, Train-tab download) and practice-cutoff display, see agent.md / app.md.
- 2026-09-23: Quiz school (agent/quiz.py, Quiz tab): reinforcement learning on real pro setups, reward = points.

## Recent changes, by chat
Each chat adds lines only to its own list, just above its marker line.

### Chat A (Backend & Skills)
- 2026-09-24: two-chat setup: `TWO_CHATS.md`, `CLAUDE.md`, per-chat sections in `Progress.md` and here.
- 2026-09-24: Quiz builds no longer cap near 18k (look-alike majority vote, top-ups until target, capped back-fill, shortfall note in Quiz tab).
- 2026-09-24: Hermes sets itself up: auto-start Ollama, auto-download the model, `/api/assistant/setup`, status `local`/`next_step` (UI handed to Chat B).
- 2026-09-24: Hermes memory -> `data/hermes_memory.json` (plain file); model unloads after each reply (keep_alive 0) and via `POST /api/assistant/sleep`.
- 2026-09-24: Hermes chat model -> `llama3.2:3b` on CPU only (`ollama_cpu_only`, `num_gpu` 0), no VRAM.
<!-- Chat A: add new lines above this marker -->

### Chat B (UI & Polish)
- 2026-09-24: design review of all six tabs (screenshots + findings), see app.md "Design review".
<!-- Chat B: add new lines above this marker -->
