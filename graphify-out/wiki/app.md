# Desktop app (`app/`)
- **main.py**: picks port 8420 (or free), runs uvicorn in a thread, opens a pywebview window (browser fallback), autostarts the MCP bridge, and stops all jobs on close.
- **server.py**: FastAPI. Routes: `/api/status` (settings, jobs, model/data ready, RAM/VRAM via psutil + nvidia-smi), `/api/settings`, `/api/account`, `/api/positions`, `/api/bars` (M1), `/api/size`, `/api/positions/{ticket}/close`, `/api/kill`, `/api/agent/start`, `/api/{job}/stop`, `/api/fetch`, `/api/train`, `/api/mcp/start`, `/api/jobs/{name}/log`, `/api/journal`, `/api/progress` (+ /promote, /demote: stage ladder, auto Paper→Demo, drawdown demotion, learning trigger), `/api/learn`, `/api/replay/start|control|state`, `/api/plan` (per-trade stake plan for paper/demo/real), `/api/bot/trades` (sync + open with live P/L + recent + stats per mode), `/api/assistant/status`, `/api/chat`, `/api/chat/history`, `/api/memory`. MT5Unavailable → 503; ValueError → 400.
- **mt5_service.py**: locked MetaTrader5 wrapper (margin_per_lot via order_calc_margin, trade_plan, model_meta, account, positions tagged owner bot/hermes/you by magic, sync_bot_ledger, floating_for, m1_bars, symbol_spec, close_position, close_all, lots_for_risk, model_exists).
- **jobs.py**: `Job`/`JobManager` subprocesses (agent, train, fetch, mcp), logs to `logs/<job>.log`, tail reader.
- **settings.py**: DEFAULTS + load/save to `data/settings.json`.
- **static/**: `index.html` (tabs Market, Agent, Train, Hermes, Settings), `app.css` (graphite + brass gold palette, IBM Plex, glass only on rail/strip/toast), `app.js` (polling, bot trade card with Size mine / Copy levels, chart price lines + markers for bot trades, open/close alerts with WebAudio beep, Bot trades table + stats, chart via vendored lightweight-charts 4.2.0, hold-to-flatten, sizing calculator, chat, memory).
- Tested: API via TestClient; UI screenshots with mocked MT5 data.

## Extra history + clearer bot card (2026-09-23)
- Train tab: "Add years of extra history" step (1/3/5/8/All) -> `POST /api/history/download {years}` -> job "history"
  (`agent.history`); log shows in Train output. Train accepts history alone (no MT5 file needed).
- Bot card: the needed % is the practice cutoff (`need` in agent_status.json / replay_state.json) instead of the 0.8
  threshold; "no signal" renamed "waiting for a strong setup" with a reason.
- Replay bar: period optgroups (unseen / recent / everything), speed presets incl. 2000/s and Max, ETA; smooth chart via
  `rpAnim` queue + requestAnimationFrame (`queueReplayBars`, `replayFrame`), poll 400 ms.
- Quiz tab (layout A): /api/quiz/build, /api/quiz/train {resume|focus}, /api/quiz/control, /api/quiz/state,
  /api/quiz/labels, /api/quiz/question/{id}, /api/quiz/ask; canvas mastery board with picking; job "quiz";
  settings `quiz_filter`, `quiz_speed` (0 = max).
- Quiz tab Weak spots panel: GET/POST /api/quiz/report; Copy report for Claude; Work on these (focus ids).
