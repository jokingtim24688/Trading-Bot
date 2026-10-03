# Trading-Bot Knowledge Graph: Wiki Index

> Hand-built map in graphify's wiki layout (the `graphify` CLI couldn't be installed in the cloud session).
> To regenerate automatically on your PC: `pip install graphifyy`, then run graphify on the repo (use its `--wiki` option).
> Start here for any question about this repo, and open the linked page for detail.

**Two chats work on this repo at once.** Read [TWO_CHATS.md](../../TWO_CHATS.md) before changing anything: lanes
(A / chat 1 = backend & skills, B / chat 2 = UI & polish), the shared branch `claude/laughing-bell-3vt2c7`, and the git routine.

## Communities (subsystems)
| Community | Page | Core nodes | Lane |
|---|---|---|---|
| Desktop app (rail: Bot [Live / Agent details / Hub], Manual, Settings [General / Keybinds / Sounds], More: Review, Train, Quiz) | [app.md](app.md) | `app/main.py`, `app/server.py`, `app/static/*` | B: static + window · A: server, jobs, settings |
| M1 trading agent | [agent.md](agent.md) | `agent/run.py`, `agent/features.py`, `agent/model.py`, `agent/risk.py`, `agent/broker.py` | A |
| Mac / Linux support (installer, MT5 bridge, Mac pop-ups) | [mac.md](mac.md) | `Trading Bot.command`, `agent/mt5_remote.py`, `MT5 Bridge.bat`, `app/platform_info.py` | B (2026-09-30) |
| MT5 MCP bridge | [mcp.md](mcp.md) | `mcp_server/mt5_mcp.py` | A |
| mt5-trading skill + Claude subagent | [skill.md](skill.md) | `.claude/skills/mt5-trading/`, `.claude/agents/mt5-m1-trader.md` | A |

## God nodes (most connected)
1. **MetaTrader5 terminal** (external): used by `app/mt5_service.py`, `agent/broker.py`, `mcp_server/mt5_mcp.py`, `scripts/fetch_m1.py`, `scripts/position_size.py`
2. **`app/settings.py` → `data/settings.json`**: read by server, jobs, telegram, mt5_service
3. **`agent/ledger.py`**: bot trade ledger read/written by agent brokers and the app server (the Sim keeps its own `data/sim.db`)
4. **`agent/features.py`**: `build_features`/`triple_barrier`/`atr` used by train and run
5. **`app/jobs.py` JobManager**: runs agent, train, fetch, replay, sim, backtest, quiz and mcp subprocesses for the UI
6. **M1 lock**: `TIMEFRAME = "M1"` (agent/config.py), `TF = mt5.TIMEFRAME_M1` (mcp), `PERIOD_M1` (MQL5 docs)

## Key flows
- **Launch (Mac)**: `Trading Bot.command` / `Trading Bot.app` (detects macOS, chip, Homebrew, Python, libomp, git; installs what's missing; same update + pip + launch) → MT5 through `agent/mt5_remote.py` to a Windows PC/VM running `MT5 Bridge.bat`. See [mac.md](mac.md).
- **Launch**: `Trading Bot.bat` (git pull, pip only if requirements changed, pythonw, window closes) → `.venv` → `app.main` → uvicorn (127.0.0.1:8420) + pywebview window → auto-start MCP bridge (:8765).
- **Train**: Train tab → `/api/fetch` → `fetch_m1.py` → `data/SYMBOL_M1.parquet` → `/api/train` → `agent.train` → `models/SYMBOL_M1.json`.
- **Trade**: Agent tab → `/api/agent/start` → `agent.run` → closed-bar poll → features → XGBoost proba → `RiskGate` → Paper/LiveBroker → `logs/journal_*.csv`.
- **Telegram**: alerts from `app/watch.py` events → `telegram.for_event` (layouts, `telegram_layouts`) → closes within a few seconds batched; more than `telegram_batch_over` (3) → one HTML summary card. Commands: built-ins + your own (`telegram_custom_commands`, from `app/telegram_maker.py`) + chat buttons (`telegram_keyboard`).
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
- 2026-10-01: `ea/CandleSenseICT.mq5` - one advanced single-file ICT EA for gold (FVG + Order Block scoring, killzones, liquidity sweep, `OrderCalcProfit` sizing, self-learning setup weights), replacing the multi-file ML pipeline approach; researched from real MIT-licensed gold EAs, see `ea/README.md`.
- 2026-10-01: `ea/CandleSenseSwing.mq5` - a simpler trend-direction stacking EA (EMA slope, fixed SL/TP in points, up to 60 concurrent trades, total-risk-capped sizing split across all open trades), alongside CandleSenseICT for a different style; both have the Trades/Earned/Lost/Subtotal HUD.
- 2026-10-01: `ea/CandleSenseSwing.mq5` v2: trades every swing both ways (M1 swing highs/lows instead of the EMA-slope filter), HUD shows swing + win rate.
- 2026-10-01: `ea/CandleSenseStart.mq5` - small-account ($100) gold EA: trend pullback, 1:2.5 targets, auto-GMT sessions, compounding lots, hard loss protection. Parameters derived from the studies in `ea/*.py`.
- 2026-10-01: `ninjatrader/SmallAccountProNT.cs` - SmallAccountPro as a NinjaTrader 8 strategy for CME 1-Ounce Gold (1OZ) on 30-min candles, the US/CFTC route; mirrors `ea/futures_replay.py` (+486% on $400 Mar-Sep 2026 with the entry candle checked). Setup/testing in `ninjatrader/README.md`.
- 2026-10-02: simpler app (Chat A, in B's lane on request): rail Solana/Bot/Manual/Hermes/Settings + More; Bot = Live | Agent details, Settings = General | Keybinds | Sounds (`RAIL_PARENT`); Solana tab is a plain dashboard; the Solana engine trades only with a bot trained on real coins (`engine.model_is_real`, `PAPER_COST` 2%, `trench.REAL_ONLY_FROM` 300, `rug.UNCHECKED`). See sol.md / app.md.
- 2026-10-01: fleet launcher `agent/fleet.py` (+ `agent/FLEET.md`): one bot process per symbol, spread/model scan, ledger-fed terminal dashboard, Telegram control (/stop /start /pause /status /bots) via a new `register_command()` hook in `app/telegram.py`. /stop drains - no new trades, open ones run to SL/TP.
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
- 2026-09-25: Bot tab (default, full screen): live card, co-pilot proposals with Approve / Skip, symbol switch, clock in any time zone, points, gauge, pills; see app.md "Bot tab".
- 2026-09-26: Market merged into the Bot tab (chart left, live card right, no SL on its chart), notifications below the Bot header; see app.md "Market merged into the Bot tab".
- 2026-09-30: Solana trenching backend `sol/` (see [sol.md](sol.md)), Bongo Cat avatars + preview board, Quiz Stocks/Trenching/Combined, Telegram /prof /loss /total, MT5 main agent + subagents review (7793203).
- 2026-09-30: Mac support (b7787c0): installer `Trading Bot.command` that detects the Mac, MT5 bridge (`agent/mt5_remote.py`, `MT5 Bridge.bat`), Mac pop-ups/notifications, see [mac.md](mac.md). Agent profiles in the Solana tab: expand button on each avatar, `/api/sol/agent/{model}`, votes table in sol.db.
- 2026-09-30: Rank system for the Solana crew (Intern -> Legend; rank = suit + vote weight) and a Ranks tab, see [sol.md](sol.md) and app.md.
- 2026-09-30: every agent has its own tweet monitor (`sol/tweets.py`, four beats, twitterapi.io or the X API);
  finds still go through the rug rules, the model floor, the debate and the subagents. Tweet radar panel + per-agent
  section in the profile. See [sol.md](sol.md#tweet-radar).
- 2026-09-30: one-line installers `install.ps1` (PowerShell) and `install.sh` (bash, macOS + Linux); links at the
  top of the README. See [mac.md](mac.md).
- 2026-09-30: secrets stay in the backend: `settings.SECRETS` + `settings.public()`; `/api/status` and
  `/api/settings` return `__saved__` for the X key, and sending it back doesn't overwrite the real one.
- 2026-10-01: app-wide simplicity pass: the rail folds Ranks/Review/Train/Quiz/Keys/Sounds behind one "More"
  toggle (collapsed by default); the Solana control bar drops to 3 always-visible controls (the data/train buttons
  moved into a "Data & training" disclosure, now that both happen automatically); the tweet radar's per-agent beat
  cards collapse behind a summary. See app.md "Simplicity pass".
- 2026-10-01: the trenchers get continuous, wider real data (`sol/trench.py download()` reads four pool lists on a
  recurring timer, not one list once) and training now retrains itself as real data grows, logged to a new
  `training_log` table with a real "AUC over time" chart + plain-English improvement sentence in the Quiz tab. See
  sol.md "Trenching data & training that actually shows improvement". 85 tests passing.
<!-- Chat B: add new lines above this marker -->

- 2026-10-03: Solana and Hermes removed (sol/, hermes/, brain/memory/tools, their tabs, settings and tests); the MT5 main agent + checkers moved to `agent/desk.py` (`GET /api/agents`). Bot tab: Live | Agent details | **Hub** (cats for the bot and its checkers, market, balance, gain/loss/subtotal, chart, recent trades) and **Sim** next to Replay (`/api/sim/*`, replay engine on its own files + `data/sim.db`, 1 candle/s). Telegram: command maker (`app/telegram_maker.py`, `/api/telegram/maker[/apply]`), layouts, chat buttons, one summary card when more than 3 trades close. See app.md.
