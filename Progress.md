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
