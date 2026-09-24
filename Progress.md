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

## 2026-09-23: First run on the user's PC
- App launched on Windows; connected to a demo account (~$108,986); M1 history fetched.
- Fixed: training crashed with UnicodeEncodeError (cp1252 console) -> jobs now run with PYTHONIOENCODING/PYTHONUTF8=utf-8.
- Found: broker leverage on gold is 1:20 (margin rate 0.05), which made stake-based exits ~$55 stop / ~$445 target.
  User chose to size exits as if leverage were 1:100 (`ref_leverage`, Settings): stop ~$11, target ~$89 on 0.01 lot;
  lot size still from the real margin. Training labels use margin rate 1/ref_leverage.

## 2026-09-23: Practice mode, Replay, visible decisions
- User's live run: model confidence ~1% vs a 0.8 threshold, so no trades. Causes: 8:1 exits + 240-bar training
  look-ahead labelled most eventual winners "no result". Look-ahead now 1440 bars (settings auto-upgrade 240 -> 1440).
- Practice mode (`agent/practice.py`, default on for Paper/Replay): trade the model's top-10% setups over the last day of
  readings instead of the fixed threshold. Demo/Real keep the threshold.
- Replay (`agent/replay.py`): runs the bot on downloaded M1 history (default: the model's unseen test period) with a live
  speed slider (1-600 candles/s), pause/stop; trades recorded as mode "replay" (feed learning/stats, not the Paper gate);
  unfinished trades at the end are discarded. Market tab: "Replay history" panel + chart + bot card follow the replay.
- Agent prints one line per candle (buy/sell confidence vs needed, decision/skip reason) and writes data/agent_status.json;
  the Market tab's Bot trade card shows it live.
- Spread/ATR filter relaxed 0.15 -> 0.35 (stops are stake-based now; spread-vs-stop check remains).
- Bugs found in testing: replay timestamps wrong for ms-resolution parquet (fixed); end-of-replay force-closes skewed stats (now dropped).

## 2026-09-23: Years of extra training data + "no signal" fix
- `agent/history.py`: downloads free XAUUSD M1 history (HistData, 2009 to Jan 2026, public HF dataset fokan/xauusd-2009-2026,
  ~24 MB/year), converts EST to broker server time (+7h), fills spread from the MT5 median, caches in data/histdata.
  `load_bars()` merges it with the MT5 download (MT5 wins on overlap); train and replay use it automatically.
- Train tab: "Add years of extra history" (1/3/5/8/All) + Download history button (`POST /api/history/download`, job "history").
- Features: dropped the volume feature (history has no volume) and store float32 to halve RAM.
  Measured: 2 years (720k candles) trained in 32 s on CPU at 0.9 GB peak, so 5 years ≈ 2.5 GB and All ≈ 8 GB.
- "no signal" fix: in practice mode the card compared confidence with the 80% threshold even though practice enters at
  the top-10% cutoff. The agent and replay now report the cutoff as `need`; the card shows "Needs X% (practice: its best
  ~10% of readings)", and "no signal" is now "waiting for a strong setup" with a reason. Expect ~9 of 10 candles to wait.
- Fixed pandas 3 timestamp-resolution crash in replay (index normalised to ns).
- Checked: dataset file names/CSV format via the HF connector; import+merge, train, replay, API endpoint with synthetic
  data (huggingface.co downloads are blocked in the cloud sandbox, so the real download runs on the PC).

## 2026-09-23: Replay all of it, faster and smooth
- Period menu: model's unseen data 1/7/30/90 days, 1 year or **all of it** (default); last 7/30/90/365 days; or all
  downloaded history (marked as including training data). `--days 0` = to the end, `--from all` = from the first candle.
- Speed: presets 1 / 10 / 60 / 600 / **2000** / **Max** candles/s plus the custom slider (now 1 to ~18k, top = Max).
  Status line shows the real candles/s and time left. Pacing sleeps in small batches (Windows sleeps are coarse);
  control file read 5x/s and learned rules once per run instead of every candle. Measured ~2-3.5k candles/s at Max here.
- Smooth chart: new candles are queued and drawn a few per animation frame (series.update) instead of redrawing a
  300-candle snapshot every 0.7 s; state carries 1500 candles, polled every 0.4 s. Measured in Chromium: at 60/s and
  2000/s the chart advanced on every 50 ms sample with no jumps.
- Bug fixed: replay trades were stamped with today's wall-clock date, so the 3% bot daily loss limit summed ALL replay
  losses and stopped the bot for the rest of a long replay (and learn.py's hour rules saw every replay trade in the
  current hour). Replay trades now carry the replayed candle's UTC date/time (server time -2h); daily P/L is a per-day
  SQL sum (indexed) instead of loading every trade per signal. Same test period: 304 -> 1019 trades taken.
- Bot now trades in Replay: the live "spread too large vs ATR" filter blocked every in-session signal on quieter/cheaper
  years (user saw 0 open / 0 closed after 5,330 candles). Replay skips it by default (`--strict-filters` restores it);
  the spread-vs-stop cost check, session hours, daily loss limit and max open still apply. Reproduced on 2021-like
  data: strict 0 trades vs default 27. Replay status now lists the top skip reasons ("signals skipped: ...").

## 2026-09-23: What professional traders watch, as model inputs
- `agent/pro.py`: 19 causal inputs from the pro intraday playbook, in ATRs: prior-day high/low/close, day and week open,
  position in the day's range, Asian range, London/NY 30-min opening ranges, session average price (VWAP stand-in; no
  volume in history), liquidity sweeps (stop hunts) of the 60-candle high/low, fresh breaks, fair value gaps, H1
  structure, $10/$50 round numbers. Model now has 49 inputs. Checked causal (values never change when later candles
  are added); 1.8M candles build in ~13 s.
- `active_setups()` names what a pro would see (17 setups, e.g. "Liquidity sweep below lows", "Opening-range breakout
  up"); `primary_setup()` files each trade under the setup matching its direction (new ledger column `setup`).
- Learning: new "By pro setup" table in the m1-bot-lessons skill; setups that keep losing get blocked (never more
  than half). App: "Pro read" chips on the bot card (waiting and with trades open), setup on each open trade, Setup
  column in Bot trades, blocked setups in the learned panel.
- Skill: `references/pro_playbook.md` (prep, levels, sessions, the setups, risk/execution habits, what pros avoid,
  review, and how each maps to the inputs).
- Old models: a model trained before this stops with "trained with older inputs, retrain on the Train tab".
- Tested end to end on synthetic data: train -> replay (632 trades, all filed by setup) -> learn (setup table,
  blocked setups) -> app screenshots.

## 2026-09-23: App opens without a command prompt
- `Trading Bot.bat`: updates (git pull), installs packages only when requirements.txt changed, launches with
  pythonw.exe (no console) and exits, so the window closes once the app opens. CRLF line endings.
- `app/main.py`: under pythonw, output goes to logs/app.log; a startup error shows a Windows message box with the log path.
- Background jobs already run hidden (CREATE_NO_WINDOW).

## 2026-09-23: Quiz school (reinforcement learning on pro setups)
- `agent/quiz.py build`: finds questions in real downloaded XAUUSD M1 history (no public record of individual pro
  trades exists, so: moments where a pro setup from agent/pro.py appeared AND a pro-style trade (stop beyond the sweep
  wick or 1.5 ATR, target 2R, 4h) hit its target -> answer buy/sell; plus clean no-trade spots where both sides failed
  -> answer "stay out"). One question per day, round-robin over 10 setup types; 40 by default = 30 practice + 10 exam.
  Each stores the chart (90 candles + the 60 after, revealed), the inputs, and a pro explanation with entry/stop/target.
- `agent/quiz.py train`: softmax policy over buy/sell/wait trained with REINFORCE + baseline; reward = points
  (+10 right, -10 wrong way, -5 traded when it should wait, -3 missed a good trade); points are its only objective.
  Answers are sampled, runs until every practice question is right 5 times in a row, then a greedy exam on unseen
  questions. Saved to models/quiz_policy.json. Synthetic test: 30/30 mastered in 92 rounds, exam 6/10 (chance ~33%).
- App: Quiz tab (build, start/stop, speed 1/5/20/100/Max, points/mastered/round, mastery grid with 5 dots per question,
  chart with entry/stop/target and the outcome faded in, agent's answer + probabilities + points + pro answer, exam
  result, question table), "What would you do now?" on the live MT5 chart, Settings: quiz agent second opinion
  (`--quiz-filter` in agent and replay: only enter when the quiz agent picks the same side).
- Note: the policy gets very confident (e.g. 99%) after mastering; the exam score is the honest measure.

## 2026-09-24: Quiz at 100/s + layout options
- Quiz runs at 100 questions/s by default (settings v3 migration sets quiz_speed 100 for existing installs).
- Three live layout mockups for the Quiz tab at that pace, for the user to pick: A Scoreboard (big points, mastery
  board, latest mistake held on the chart, points-per-round curve), B Answer tape (streaming answers, accuracy by
  setup, total points), C Question board (30 chart cards flashing right/wrong, streak dots, click for detail).
  https://claude.ai/artifact/UhJQwNYDN4XuaAdfvH8Les (simulated data). Waiting on the user's pick.

## 2026-09-24: Quiz school v2 (layout A, up to 10,000 questions, no more unpassable questions)
- User picked layout A (Scoreboard) with small squares; Max speed is the default (settings v4).
- Build: 40 to 10,000 questions, at least an hour apart; charts/inputs stored in .npy files (quiz.json stays small).
  Cleaner questions: pro winners must reach target within 3 h without going >60% toward the stop; stay-out spots are
  where neither side would have been a clean trade (mixed through the plan, so they don't get crowded out).
  Contradictions removed: a near-twin, or 4 of the 5 closest look-alikes, with the opposite answer.
  4 years of candles hold ~5,200 clean questions; 10,000 needs most of the 2009+ history.
- Why questions were unpassable, and fixes: (1) the agent compared each answer with its global average (~+9), so a
  right answer on a question it always missed was barely a reward -> per-question expectation (REINFORCE with a
  per-question baseline); (2) once sure of a wrong answer it never tried the right one -> exploration rises from 5% to
  50% on a question it keeps missing; (3) unfinished questions asked 2 extra times a round; (4) mastery is sticky
  (5 in a row once = finished; still reviewed); (5) policy is now a small network (49 -> 64 tanh -> 3);
  (6) questions still stuck after 150 rounds are set aside as "unclear" instead of blocking.
  Synthetic tests: 1,000 questions 739/746 finished, exam 74.6%; 5,185 questions 3,781/3,889, exam 83.4%.
- Continue (saved agent + progress, saved every 20 s) and Work on picked (focus on chosen unfinished questions;
  finished ones are left out) in CLI (--resume, --focus) and app.
- App (layout A): controls + big points + points/s + stats + points-per-round curve + exam by setup on the left;
  canvas mastery board (4-12 px squares, hover label, click to pick/view, pick all unfinished, work on picked),
  latest mistake chart held 2 s, hardest-right-now table (work on these), ask-the-live-market.

## 2026-09-24: Quiz v3 - loops until done, sees the chart, skills
- User's real run: 9,438 questions, 6,936/7,078 finished; 142 stayed stuck (5% right) even with Work on picked, and
  the run quit and marked them unclear. Cause: with only 49 indicator inputs they looked like questions with the
  opposite answer.
- Added data: the agent now also sees the chart itself (last 40 candles OHLC + 90-candle outline, in ATRs from the
  close) = 227 inputs. Built from the stored quiz charts, so existing quizzes work without rebuilding. Live answers,
  the replay/agent second opinion and "What would you do now?" pass the chart too.
- Never gives up: loops until everything in play is finished or Stop. After 100 rounds without a new finish it asks
  stuck questions 7 extra times with 3x learning steps, then doubles the network (64 -> 512, keeping what it learned),
  then resets expectations/exploration on the stuck ones, and loops again. Board shows stuck squares grey
  ("stuck, looping"); the note under the points names the current tactic.
- Baby-blue square (and ring) = the question it is working on right now.
- Skills: `.claude/skills/quiz-school/` (how to run, read and un-stick the quiz) and `.claude/skills/quiz-lessons/`
  (rewritten by the quiz after every run: finished/stuck and exam accuracy per setup, which setups to trust).
- Short test (100 questions, synthetic): 75/75 finished in 58 rounds, 227 inputs, exam 68%, lessons written.

## 2026-09-24: Quiz v4 - custom size up to 100,000, advanced question builder
- Size: free number box (40 to 100,000, with suggestions); board squares shrink to 2 px above 20,000.
- Builder:
  - 18 setups: added Asian low/high raided, H1 uptrend pullback/downtrend bounce (20 EMA), held above/below the
    prior-day high/low, fade a >4 ATR stretch from the session average.
  - Traps (15%): a setup whose stop was hit within the hour -> "stay out", teaching when to skip a setup.
  - Answer mix: ~65% clean trades, 15% traps, 20% stay-out spots.
  - Best examples first (fastest, least heat), interleaved across years.
  - Spacing 60 -> 30 -> 15 min only when more are needed.
  - Contradiction/near-copy removal with automatic top-up.
  - Every question graded easy/medium/hard by look-alike agreement.
  - Outcomes computed for all candidates at once (numpy).
- Training: curriculum (easy + medium first, hard join at 90% finished or after 60 rounds); results group all traps
  in one row; lessons skill lists the question mix.
- Synthetic tests (4 years of candles): 1,000 built in 21 s with all 18 setups (337 buy / 335 sell / 328 stay out,
  102 traps; 511 easy / 282 medium / 207 hard); 20,000 requested -> 19,264 built in 64 s (history nearly full at
  15-minute spacing); training: curriculum added 158 hard, 742/750 in a 400-round test cap, exam 73.6%.

## 2026-09-24: Weak-spot report + skills from what the quiz gets stuck on
- Trainer records the wrong answer it gave per question and its exam picks (quiz_progress.npz) and runs the report
  every 5 minutes and at the end.
- `agent/quiz_report.py`:
  - Groups by setup (traps separate) plus "Traps (all setups)".
  - Ranks weak spots by practice/exam accuracy and unfinished share.
  - Compares missed vs right questions on readable measures (effect size >= 0.35 plus a real-world minimum gap;
    time window / weekday / year bunching).
  - Trap check (can the chart separate traps from winners?) and rule-based suggested fixes.
  - Writes data/quiz_report.md (for Claude), data/quiz_report.json (app) and the auto skill
    `.claude/skills/quiz-weak-spots/` (index + page per spot; claude-*.md pages kept).
- App: Weak spots panel (patterns, usual mistake, suggestion, Work on these), Refresh, Copy report for Claude (with
  a select-and-Ctrl+C fallback).
- quiz-school skill: how Claude turns a pasted report into claude-*.md skill pages.
- Tested:
  - 2,000-question synthetic run: report + skill pages written.
  - Planted pattern (one setup failing only during the NY open) caught: "100% of the ones it misses are in the New
    York open, vs 0%".
  - Copy button copied the 14.9k-char report.
  - Work on these sent the spot's question ids.
