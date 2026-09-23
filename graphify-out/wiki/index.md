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
3. **`agent/features.py`**: `build_features`/`triple_barrier`/`atr` used by train and run
4. **`app/jobs.py` JobManager**: runs agent, train, fetch, and mcp subprocesses for the UI and the Hermes tools
5. **M1 lock**: `TIMEFRAME = "M1"` (agent/config.py), `TF = mt5.TIMEFRAME_M1` (mcp), `PERIOD_M1` (MQL5 docs)

## Key flows
- **Launch**: `Trading Bot.bat` → `.venv` → `app.main` → uvicorn (127.0.0.1:8420) + pywebview window → auto-start MCP bridge (:8765).
- **Train**: Train tab → `/api/fetch` → `fetch_m1.py` → `data/SYMBOL_M1.parquet` → `/api/train` → `agent.train` → `models/SYMBOL_M1.json`.
- **Trade**: Agent tab → `/api/agent/start` → `agent.run` → closed-bar poll → features → XGBoost proba → `RiskGate` → Paper/LiveBroker → `logs/journal_*.csv`.
- **Chat**: Hermes tab → `/api/chat` → `brain.chat` → Hermes Agent (:8642) *or* Ollama `hermes3:8b` + `tools.py` → `data/memory.db`.
- **Kill**: hold button → `/api/kill` → STOP file → agent flattens → `close_all(magic 260923)`.

## Files on disk (not RAM)
`data/` settings.json, memory.db, notes/, SYMBOL_M1.parquet · `logs/` job logs + journals · `models/` XGBoost JSON + meta.

## Other
- [Progress.md](../../Progress.md): session log of work done.
- Hardware: Ryzen 5 7600 (6C/12T, AVX-512), RTX 4060 8 GB. See [agent.md](agent.md#hardware).
