# Desktop app (`app/`)
- **main.py**: picks port 8420 (or free), runs uvicorn in a thread, opens a pywebview window (browser fallback), autostarts the MCP bridge, and stops all jobs on close.
- **server.py**: FastAPI. Routes: `/api/status` (settings, jobs, model/data ready, RAM/VRAM via psutil + nvidia-smi), `/api/settings`, `/api/account`, `/api/positions`, `/api/bars` (M1), `/api/size`, `/api/positions/{ticket}/close`, `/api/kill`, `/api/agent/start`, `/api/{job}/stop`, `/api/fetch`, `/api/train`, `/api/mcp/start`, `/api/jobs/{name}/log`, `/api/journal`, `/api/progress` (+ /promote, /demote: stage ladder, auto Paper→Demo, drawdown demotion, learning trigger), `/api/learn`, `/api/replay/start|control|state`, `/api/plan` (per-trade stake plan for paper/demo/real), `/api/bot/trades` (sync + open with live P/L + recent + stats per mode), `/api/assistant/status`, `/api/chat`, `/api/chat/history`, `/api/memory`. MT5Unavailable → 503; ValueError → 400.
- **manual.py** (Manual tab backend, Chat A): `/api/manual/quote`, `/quotes`, `/order` (market + buy/sell limit/stop, GTC/today, magic 0 = "you", real accounts need `confirm_real`, SL/TP side + stop-level checks, volume clamped to the lot step), `/close` (tickets, partial `volume`, filter all/profit/loss/buys/sells, owner, symbol; bot trades get the ledger hint "manual (app)" then `sync_bot_ledger`), `/modify` (SL/TP, 0 removes, BE), `/orders`, `/orders/cancel`, `/history?days=` (closed deals, open price and owner from the entry deal).
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

## Design review (2026-09-24, Chat B)
- Screenshots without Windows/MT5: run `uvicorn app.server:app` from a copy of the repo with a fake `MetaTrader5`
  module on `PYTHONPATH` (namedtuples with `_asdict()`; `copy_rates_from_pos` returns a numpy structured array), seed
  trades with `agent.ledger.open_trade/close_trade` and chat with `app.memory`, then drive headless Chromium at
  1440x900 and click `.rail-btn[data-tab=dash|agent|train|quiz|chat|settings]`. Inner panels scroll (not the page), so
  grow the viewport by the scroller's hidden height for full-length shots. Route `fonts.googleapis.com` /
  `fonts.gstatic.com` through a client that trusts the proxy CA, or IBM Plex falls back to system fonts.
- Findings: 2 of 9 anti-vibe tells (identical rounded panels; middle-dot meta strings). Layout bugs: Train step 2 text
  column collapses; Market bot card title wraps and its trades run together; Agent stat grid leaves an orphan tile;
  Settings has native blue checkboxes, ~60% width, Save only at the bottom; Quiz primary button ignores the no-quiz
  state; "Replay history" sits among the symbol chips; gold is overloaded (brand, primary, selected, bot, buy).

## UI (2026-09-24, Chat B)
- Chart: `wireChartAuto`/`realignChart` (Auto button `#chart-auto`, 10 s realign after `chartTouched`, dblclick, resize);
  lazy history `state.win` + `loadLatestWindow`/`loadOlder`/`loadNewer`/`trimOldest` (HIST: FIRST 300, CHUNK 500, MAX
  1800), fed by `subscribeVisibleLogicalRangeChange`; live poll `/api/bars?count=3` + `series.update`.
- Agent: calendar `renderCalendar`/`loadCalendar` (fetches `/api/bot/trades?limit=3000` once a minute
  on the Agent tab; `state.cal`), day filter `#bt-day`.
- Motion helpers at the top of app.js: `motionOK`, `setHTML` (skip unchanged markup), `flash`, `tweenNum`, `setNum`;
  `moveRailInd`; `tradeMoment`. CSS tokens `--ease-out`, `--ease-spring`; reduced motion via the OS or
  `html.reduce-motion` (Settings > Display, localStorage `reduceMotion`).
- Empty states: `.empty-state` cards (consoles `#agent-empty`/`#train-empty`, board, mistake panel, points chart, bot
  card, positions). Hermes: `brainStatus` reads `local`/`next_step`/`download_pct`/`installing`/`device`; `#brain-setup`
  posts `/api/assistant/setup`; leaving the tab posts `/api/assistant/sleep`.

## UI, round 2 (2026-09-24, Chat B)
- Top bar: `#acct-mode` chip, `#bot-today-top`, `#open-count` (positions polled every 3 s on every tab), `#sessions`
  (`renderSessions`, server time = New York + 7 h), `#sys-pop` popover with RAM/VRAM/free margin.
- Chart overlay: `#chart-layer` inside `.chart-wrap`; `drawSessions`/`scheduleSessions` (Asia 01–09, London 10:00,
  New York 16:30 server time, like agent/pro.py), prior-day lines `updatePriorDay` (`state.pd`), pref `sessions`.
- Agent: `#ladder` path (`.path li.done|current`, `--prog`), `#gate`, `#plan` (4-column grid), `renderLeaderboard`
  (`#leaderboard`, from `state.cal.trades`), log drawer `#log-drawer` (`openLog`/`closeLog`, unread `.log-dot`).
- Settings: `#set-nav` + IntersectionObserver spy, `formValues`/`updateDirty`/`#savebar`, units `.u[data-u]`, prefs
  `#pref-motion`, `#pref-sessions`; `web_sites` textarea (one per line).
- Manual tab `#tab-manual` (`man` state, `openManual`, 1 s loop while open): quote from `/api/manual/quote` or
  `/api/bars?count=1`; orders `/api/manual/order`; closes `/api/positions/{t}/close` or `/api/manual/close`; edits
  `/api/manual/modify`; pending `/api/manual/orders(+/cancel)`; history `/api/manual/history`. A 404 on
  `/api/manual/quote` shows the "needs its backend" banner.
