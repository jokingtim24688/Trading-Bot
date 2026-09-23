# Trading-Bot Knowledge Graph: Wiki Index

> Hand-built map in graphify's wiki layout (the `graphify` CLI couldn't be installed in the cloud session).
> To regenerate automatically on your PC: `pip install graphifyy`, then run graphify on the repo (use its `--wiki` option).
> Start here for any question about this repo, and open the linked page for detail.

## Communities (subsystems)
| Community | Page | Core nodes |
|---|---|---|
| Desktop app | [app.md](app.md) | `app/main.py`, `app/server.py`, `app/static/*` |
| Hermes assistant + memory | [hermes.md](hermes.md) | `app/brain.py`, `app/memory.py`, `app/tools.py`, `hermes/` |
| M1 trading agent | [agent.md](agent.md) | `agent/run.py`, `agent/features.py`, `agent/model.py`, `agent/risk.py`, `agent/broker.py` |
| MT5 MCP bridge | [mcp.md](mcp.md) | `mcp_server/mt5_mcp.py` |
| mt5-trading skill + Claude subagent | [skill.md](skill.md) | `.claude/skills/mt5-trading/`, `.claude/agents/mt5-m1-trader.md` |

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
- **Chat**: Hermes tab → `/api/chat` → `brain.chat` → Hermes Agent (:8642) *or* Ollama `hermes3:8b` + `tools.py` → `data/memory.db`.
- **Follow the bot**: `agent.run` → `ledger` (`data/trades.db`) ← `sync_ledger` (agent every 1s, app every refresh) → `/api/bot/trades` → Market *Bot trade* card, chart lines/markers, alerts; Agent *Bot trades* table; Hermes `get_bot_trades`.
- **Kill**: hold button → `/api/kill` → STOP file → agent flattens → `close_all(magic 260923)`.

## Files on disk (not RAM)
`data/` settings.json, memory.db, trades.db (bot ledger), notes/, SYMBOL_M1.parquet · `logs/` job logs + journals · `models/` XGBoost JSON + meta.

## Other
- `simulation/bot-simulation.html`: standalone simulated trading session (synthetic prices, real stake rules); published artifact https://claude.ai/artifact/2NHXbvdi3XurmF51kRbEzw
- [Progress.md](../../Progress.md): session log of work done.
- Hardware: Ryzen 5 7600 (6C/12T, AVX-512), RTX 4060 8 GB. See [agent.md](agent.md#hardware).

- 2026-09-23: extra history (agent/history.py, Train-tab download) and practice-cutoff display, see agent.md / app.md.
- 2026-09-23: Quiz school (agent/quiz.py, Quiz tab): reinforcement learning on real pro setups, reward = points.
