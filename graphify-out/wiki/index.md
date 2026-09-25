# Trading-Bot Knowledge Graph: Wiki Index

> Hand-built map in graphify's wiki layout (the `graphify` CLI couldn't be installed in the cloud session).
> To regenerate automatically on your PC: `pip install graphifyy`, then run graphify on the repo (use its `--wiki` option).
> Start here for any question about this repo, and open the linked page for detail.

**Two chats work on this repo at once.** Read [TWO_CHATS.md](../../TWO_CHATS.md) before changing anything: lanes
(A / chat 1 = backend & skills, B / chat 2 = UI & polish), the shared branch `claude/laughing-bell-3vt2c7`, and the git routine.

## Communities (subsystems)
| Community | Page | Core nodes | Lane |
|---|---|---|---|
| Desktop app (tabs Market, Manual, Agent, Review, Train, Quiz, Hermes, Keys, Sounds, Settings) | [app.md](app.md) | `app/main.py`, `app/server.py`, `app/static/*` | B: static + window · A: server, jobs, settings |
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
- **Kill = reset**: hold button → `/api/kill` → STOP file → agent flattens → `close_all(magic 260923)`, then leftover paper trades are closed (reason `kill`) and `data/agent_status.json` is cleared. Stage, history and lessons stay.
- **Bot tab / Co-pilot**: `agent/run.py` reads `bot_mode` every candle. In copilot mode `propose()` writes `data/copilot.json`, and `check_proposal()` polls `data/copilot_decision.json` every 1 s (approve / skip / timeout → `copilot_auto_execute`). `app/botlive.py` backs `GET /api/bot/live` (headline, confluence, confidence rank, heartbeat, points, positions, proposal; **no SL**), `POST /api/copilot/decide`, `/api/bot/mode`, `/api/bot/symbol` (restarts the agent) and `/api/bot/symbols`. `agent/livecard.py` holds the plain-word texts.
- **Trading hours**: settings `trade_hours_start`/`trade_hours_end` (default 0-24 = all day, a start later than the end wraps midnight) → `--hours` for agent.run and replay → `RiskGate` session check. The 23-01 rollover pause stays. The status card gets `last_hour` (skip-reason counts over 60 candles).
- **Confidence slider**: the only entry bar, practice mode included. The agent gets `--settings data/settings.json` and re-reads `threshold` every candle. Practice mode only reports `top10` (where its best ~10% of readings start).

## Tests
`tests/` (pytest, `python -m pytest -q`): `conftest.py` puts `tests/fake_mt5/MetaTrader5.py` first on the path and
redirects every data file (settings, ledger, memory, lessons, news, sounds, reviews, backups, job logs) to a temp folder
per test. Files: test_manual, test_watch (BE/trail, events, sync throttle, watchdog), test_settings_files (backups,
migrations, sounds, data backup), test_stats_alerts (stats, quiz agreement, review, Telegram, news, backtest), test_hermes.
CI: `.github/workflows/tests.yml` on every push.

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
- 2026-09-24: Quiz question bank (`data/quiz_bank/`, markdown per year): one always-on creator (`bank --watch`), 10 on Build, half-year slice cache, no maximum; learns from each miss + section swaps.
- 2026-09-24: Hermes `web_fetch` limited to `web_sites` (trading/market sites, every redirect checked); new skill `quiz-setups` (20 pages) + Hermes tool `setup_guide`.
- 2026-09-24: Manual tab backend (`app/manual.py`, `/api/manual/*`); the bot learns from each losing trade (lesson, 24 h caution with floors, quiz practice question; min_confidence capped at the median).
- 2026-09-24: Manual orders: `sl_points`/`tp_points` anchor SL/TP to the real fill (market) or order price (pending).
- 2026-09-24: backend for the 11 new features: `app/watch.py` (trailing/BE, alerts feed), `app/stats.py` (you vs bot), `app/review.py` (weekly summary), settings backups, first-run checklist, connection status, replay fields.
- 2026-09-24: the Hermes tab starts the real Hermes Agent app by itself (`hermes gateway` in WSL) and uses it when installed; the small local model is the fallback.
- 2026-09-24: Windows pop-up notifications for TP/SL hits (`app/notify.py`, setting `desktop_alerts`).
- 2026-09-24: `keybinds` / `sounds` settings and your own sound files (`app/sounds.py`, `/api/sounds`).
- 2026-09-24: speed pass: `sync_bot_ledger` throttled to once per 2 s, forced/staled after closes.
- 2026-09-24: Telegram alerts (`app/telegram.py`, `/api/telegram/*`): TP/SL/open/close to your phone.
- 2026-09-24: news pause (`agent/news.py`, `/api/news`), Manual spread limit, quiz second opinion recorded per trade (`/api/stats/quiz`).
- 2026-09-24: watchdog (`app/watchdog.py`), daily data backup (`app/backup.py`), trade notes + tags.
- 2026-09-24: honest backtest (`agent/backtest.py`, `/api/backtest`): unseen months, costs, own ledger, vs the Paper gate.
- 2026-09-24: automated tests (`tests/`, 26 tests, fake MT5) + GitHub Actions CI.
- 2026-09-24: self-update fixed (`app/update.py`, run by `Trading Bot.bat`); `/api/status` reports `version`.
<!-- Chat A: add new lines above this marker -->

### Chat B (UI & Polish)
- 2026-09-24: design review of all six tabs (screenshots + findings), see app.md "Design review".
- 2026-09-24: chart auto-align + lazy history (`/api/bars?before=`), P/L calendar, Train dropdowns, copy-only Weak spots,
  animations, empty states, Hermes set-up UI; see app.md "UI (2026-09-24)".
- 2026-09-24: new Manual tab (UI; `/api/manual/*` backend specced for Chat A), top bar + session bands, Agent control bar +
  leaderboard + log drawer, Settings menu + save bar; see app.md "UI, round 2".
- 2026-09-24: Manual tab round 2: chart with SELL/BUY under it, TP 160 / SL 80 points, open-trades strip with Close all /
  profitable / negative above the chart; Latest lesson + caution chips; "Always on" rule in TWO_CHATS.md.
- 2026-09-24: 11 features UI: real-account guard, connection pill, drag SL/TP, keys, BE/trailing, TP/SL alerts, Review tab
  (you vs bot, trade replay, weekly summary), settings backup, setup checklist; see app.md "11 features".
- 2026-09-24: Hermes tab shows Hermes Agent vs local model (header + each reply), agent_step, still-working timer, 3 settings.
- 2026-09-24: Keys page (rebind everything, keyboard map), Sounds page (10 events, pitch/volume/tone/length, your own files),
  custom top-right notifications (in app + on screen), speed pass; see app.md "Keys, Sounds, notifications, speed".
- 2026-09-24: screen pop-ups above full-screen apps and while minimised (Win32 tool window, Python reads the events feed), screen picker.
- 2026-09-24: news chip + pause settings, Manual spread limit with send-anyway, quiz second-opinion panel, Telegram phone-alert settings.
- 2026-09-24: 0.9 s notification fade (also with reduced motion), backtest card + watchdog line on Agent, watchdog pop-ups, trade notes, full data backup.
- 2026-09-25: price dots on all charts (hover + drag), Manual acts on the first click, bot card last-hour reasons, trading hours, kill reset, version in Settings > About; see app.md "Dots, one-click Manual, bot card why".
<!-- Chat B: add new lines above this marker -->
