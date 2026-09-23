# Progress

## 2026-09-23: MT5 skill, M1 agent, desktop app, Hermes

### Requests
1. A skill covering how to fully use MT5, how to trade stocks on MT5, and trading in general. Always M1 candles.
2. An agent tuned for an RTX 4060 + Ryzen 5 7600.
3. An app instead of typing commands, with Hermes for memory, able to do other things too.
4. Question: can the agent run from the file system instead of RAM?

### Done
- **Skill** `.claude/skills/mt5-trading/`: SKILL.md + 9 references (platform, stocks, fundamentals, M1 playbook, MQL5, Python API, instruments, hardware/agent, app & Hermes) + 3 scripts. Validated and packaged as `mt5-trading.skill`.
- **Claude subagent** `.claude/agents/mt5-m1-trader.md`.
- **M1 agent** `agent/`: causal features, spread-aware triple-barrier labels, XGBoost (GPU train, CPU predict), risk gates, paper/live broker, journal, STOP kill switch. Tested on 60k synthetic M1 bars (train, save, load, predict).
- **MCP server** `mcp_server/mt5_mcp.py`: 10 tools with order guards, stdio + HTTP. mcp pinned `<2` (2.x renamed FastMCP; caught in testing).
- **Desktop app** `app/` + `Trading Bot.bat`: Market / Agent / Train / Hermes / Settings tabs, RAM and VRAM meters, hold-to-flatten, sizing calculator, vendored chart library (works offline). API tested; UI screenshot-checked with mock MT5 data.
- **Hermes**: Hermes Agent (Nous Research) via its API server on :8642 + MCP bridge, or local `hermes3:8b` in Ollama with SQLite memory and 15 tools. Setup guide `hermes/SETUP.md`.
- **RAM question**: answered. Running code must be in RAM, but all persistent state is on disk and the model lives in VRAM and unloads when idle (details in `hermes/SETUP.md`).
- **Graphify wiki**: `graphify-out/wiki/` (hand-built; the graphify install was blocked in the cloud sandbox).

### Not verified here (needs the Windows PC)
- Live MT5 connection, real order_send, CUDA training on the 4060, pywebview window, Ollama/Hermes Agent responses. All were mocked or stubbed in tests.

### Next ideas
- Run: Train tab → Fetch data → Train → Paper mode for 1–2 weeks → Demo.
- Optional: news/economic-calendar blackout feed; PyTorch sequence model if it beats XGBoost out of sample.
- Regenerate the graphify wiki locally with the real `graphify` tool.

## 2026-09-23: Bot tracks its own trades (trade alongside it)
- **Gaps found** (via the wiki): live exits made by the server (SL/TP) were never recorded, and the daily loss limit used
  account equity, so the user's manual losses would have paused the bot.
- **New** `agent/ledger.py`: SQLite `data/trades.db` covering paper/demo/real trades, with R measured from the original stop.
- **Brokers**: paper broker is ledger-backed (open trade + equity survive restarts); `sync_ledger()` reconciles with MT5
  deals (real P/L incl. commission/swap, reason sl/tp/manual/stop_out, SL/TP edits); orphan bot positions are adopted;
  ownership is by magic 260923, so the user's trades are ignored; netting-account guard.
- **Risk**: bot daily stop uses only bot P/L (3%); separate whole-account stop (6%).
- **App**: Bot/Hermes/You tags on positions; *Bot trade* card (entry/SL/TP, confidence, live P/L and R, Size mine, Copy levels);
  chart price lines + entry/exit markers; toast + sound alerts on open/close; Agent tab *Bot trades* table + stats with
  mode filter; `/api/bot/trades`; Hermes tool `get_bot_trades`; Settings toggle for sound.
- **Tested**: ledger + paper restart recovery; live sync against a simulated MT5 (SL hit, manual close, moved stop, orphan,
  user's trade ignored); risk gate cases; API with MT5 offline; UI screenshots with simulated trades.

## 2026-09-23: Stake-based money rules, 25 open trades
- **Rules**: stake = 0.1% of balance as margin (minimum lot if below it); SL at −25% of stake; TP +200% of stake at the
  minimum lot easing (log) to +50% at 1.00 lot and above; max 25 bot trades open (1 on netting); 100 new/day.
- **Training** now labels with the same exits (margin rate from the account's real leverage via `order_calc_margin`),
  prints the break-even win rate (11.1% at 8:1) and saves a suggested threshold. Default threshold 0.15; slider 0.05–0.8.
- **App**: stake slider, live *Each trade right now* plan panel (stake, lots, SL/TP money + distance, R:R, worst case if
  all 25 stop, min-lot and spread warnings), Settings → Bot money rules, real-lock explanation.
- **Tested**: stake plan across balances/leverage; multi-position paper broker incl. restart; stake-rule training; plan API
  + UI with simulated MT5 (1:100, $1,000 → min lot, 16.6% worst case warning).
- **Answered**: model = XGBoost (signals) + Hermes 3 8B / Hermes Agent (assistant); Real is locked by design.

## 2026-09-23: Trading simulation
- `simulation/bot-simulation.html`, published as a private artifact: https://claude.ai/artifact/2NHXbvdi3XurmF51kRbEzw
- Replays the app's Market screen with synthetic XAUUSD M1 prices and a momentum stand-in model (not the real XGBoost),
  using the real stake rules (same `stake_plan` maths). Shows alerts, bot card, Bot/You tagged positions, chart entry/SL/TP
  lines and markers, live log, trade table + stats, 25-open cap, spread-spike skips, hold-to-flatten.
- Controls: speed 1/4/15×, balance $1k/$10k/$100k, leverage 1:100/1:500, sound.
- First draft trended straight up (98% wins, misleading); rebalanced to a choppy market so results sit near break-even.

## 2026-09-23: Trade score + early exits
- `agent/score.py`: points = % gained/lost on the stake (full +200% target = +200); stop-loss hits ×1.5 (−25% → −37.5);
  trades closed early (bot, kill switch, manual) cost only what they lost. No stake recorded → R × 25 fallback.
- Ledger: new `stake`, `score`, `close_hint` columns (auto-migrates old DBs); stats add score, today's score, avg points,
  stop hits vs early exits.
- Early exit (default on, Settings toggle): close a trade when the opposite side's probability ≥ threshold and ≥ 2× its own.
  Live early/kill/app-closes are labelled via `close_hint` because MT5 reports them only as EA closes.
- App: Score / Today's score / Avg points / Stops vs early exits cards, Score column, points in close alerts,
  Settings for the stop-loss penalty and early exit. Hermes `get_bot_trades` includes score.
- Simulation page republished with score + early exits.
- Note: training labels still assume trades are held to SL/TP; early exit is a live rule on top.

## 2026-09-23: Real-chart replay + 10 open at once
- Real XAUUSD M1 candles (7 Jan 2026, 10:00–15:48 UTC, 349 bars) from the Hugging Face dataset fokan/xauusd-2009-2026
  (HistData, EST timestamps), saved as `simulation/xauusd_m1_2026-01-07.csv` and validated (OHLC-consistent, no gaps).
  Market-data sites and huggingface.co downloads are blocked in the cloud sandbox, so the data was read via the HF connector.
- Simulation page: new "Real 7 Jan 2026 / Made-up" price switch (default Real). Each real candle is replayed as 12 ticks
  (open→low→high→close or open→high→low→close); spread estimated (0.22–0.30, wider around the NY open); Restart at the end.
- Max open trades changed 25 → 10 (clarified: trades open at the same time, not a per-session total) in agent config,
  app settings, simulation and docs.

## 2026-09-23: Score = dollars
- 1 point = $1: score = trade P/L in account currency; stop-loss hits ×1.5, early/manual/kill closes ×1.
  Example: −$20 stop hit (−30) then +$100 (+100) = +70; if the −$20 was an early close, +80.
- Updated agent/score.py, app text/formatting, simulation, skill docs.

## 2026-09-23: Stage ladder + self-learning
- `agent/progression.py`: Paper → Demo → Real·2 → Real·5 → Real·full with gates (trades, days, points $, profit factor,
  drawdown). Paper→Demo automatic; real steps need typing REAL; drawdown breach demotes one stage. State in data/progression.json.
- `agent/learn.py`: groups the ledger by UTC hour / side / confidence / exit / stage, writes `.claude/skills/m1-bot-lessons/`
  (SKILL.md + references/history.md) and data/learned_rules.json; agent applies rules as entry filters (--no-learned to skip).
  Learns every 50 closed trades, on promotion, and on demand.
- App: stage ladder with gate progress bars, Promote/Move back, in-page REAL confirmation, "What the bot has learned" panel,
  Settings toggles (auto Paper→Demo, apply learned rules). Start uses the earned stage. Hermes tool `bot_progress`.
- Tested end to end with simulated trades: auto promotion, learned 21:00 UTC block, REAL gate, max-open 2 at Real·2,
  drawdown demotion back to Demo.
