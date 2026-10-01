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

## 2026-09-24: Quiz Wipe button
- Wipe (next to Stop): two clicks (the first arms it for 4 s). Stops a running quiz, deletes every question and its
  progress (quiz.json, quiz_x/bars/times .npy, progress, live state, control, weak-spot report). The trained quiz
  agent (models/quiz_policy.json) is kept. POST /api/quiz/wipe. Tested: 100-question quiz wiped, all files gone.

## 2026-09-24: Review of the first real report; never revisit; ~12x faster
- Review of the user's report (14,908 questions):
  - Exam 24% (below guessing) with sweeps at 0-1% on 1,100 unseen questions while practice was 88-89%. That is
    forgetting: finished questions were never re-checked, so narrow training (Work on these on STAY OUT traps)
    drifted the network.
  - Traps are the real weak spot (exam 0-7%). The trap check agreed across setups: traps come in quiet, small-candle
    markets. Spread/ATR and round-number distance were the same signal, because history spread is an estimate and
    distances are in ATRs.
  - The hardest questions cluster in early January (holiday-thin).
  - Written up as claude-*.md pages in .claude/skills/quiz-weak-spots/references/.
- Training:
  - Never revisits finished questions.
  - Finished now needs its best answer to be right too, not just 5 lucky picks.
  - Silent refresher (Settings `quiz_refresh`, default on; CLI --no-refresh) rehearses finished questions in each
    step.
  - Memory check every 10 rounds and before the exam puts forgotten ones back on the board.
  - Exam history with a drop warning; gentler last-resort tactic.
- Speed: batched training (64 per matrix step) 10,066 -> 119,394 answers/s on the same 2,000-question quiz;
  1,500 rounds in 13 s.
- Tests (synthetic):
  - Without the refresher, 250-600 "finished" were forgotten every 10 rounds; with it, ~100-150, leveling at
    1,300-1,370 of 1,500 truly finished, exam ~73-75%.
  - Damaged agent: memory check put back 584 and the exam-drop warning fired.
  - Current square never on a finished one (60/60 samples).
  - Start modes keep/clear progress correctly.
- Report: merges measures that move together, candle-size wording for spread/ATR, month bunching, 20+ per side for
  bunching, small-group flag, warnings (exam below guessing, exam fell, memorised).

## 2026-09-24: Faster question building (several finders at once)
- Profiled the 20k build (58 s): look-alike comparison 45 s (full recompute on each of 4 top-ups), features 17 s,
  outcome walk 1 s.
- Several question finders at once:
  - History cut into ~300k-candle slices with 30k warm-up; a process pool (auto: physical cores - 1, capped by free
    RAM at ~1 GB each; Settings `quiz_workers`) works through them; results merged.
  - Verified identical candidates/outcomes to one finder, indicators within 4e-6.
  - 1 finder 17.9 s -> 3 finders 3.9-5.6 s.
  - Memory measured: 2.3 GB for a 1.23M-candle slice, which is why slices are ~300k (~0.9 GB).
- Cache of finder results in data/quiz_cache (keyed to history files); rebuilds skip finding.
- Look-alikes: incremental (top-ups compare only new questions; verified identical to one-shot), threaded
  (6.6 s -> 3.3 s on 4 threads), sparse near-pair checks, in-place distances.
- Chart inputs vectorised (identical) and saved as data/quiz_c.npy.
- Build progress file + Quiz tab progress bar with one bar per slice.
- Result: 20k-question build 58 s -> 18 s cold, 11 s from cache (4-core sandbox).

---

# Two chats (from 2026-09-24)

Two Claude chats now work on this repo at once (see `TWO_CHATS.md`). Everything above is the history from before.
Each chat writes only in its own section below, and adds new entries just above its own marker line.

## Chat A log (Backend & Skills)

### 2026-09-24: Two-chat setup
- Request: the user will run two chats at once on this project and wants a file telling both chats what to do, plus
  a prompt to brief the second chat. Skills come later (Chat A's lane).
- `TWO_CHATS.md`: lanes (A = backend & skills, B = UI & polish with the anti-vibe-polish skill), the shared branch
  `claude/laughing-bell-3vt2c7`, a 9-step git routine for every task, shared-file rules, a "never" list, handoff lists.
- `CLAUDE.md`: short pointer so every new chat reads `TWO_CHATS.md` automatically.
- `Progress.md` and the wiki index now have one section per chat with marker lines, so the two chats' notes don't
  collide in a merge.
- Branch: the user chose the default branch `claude/laughing-bell-3vt2c7` (the one their PC pulls) as the shared
  branch and approved both chats pushing there. A new chat starts on it, so it starts up to date.

### 2026-09-24: Quiz builds no longer stop near 18,000 questions
- Cause: the contradiction check dropped *both* questions of any disagreeing look-alike pair, and new top-ups
  knocked out old good questions. With only 4 top-up rounds, builds levelled off (~18k) whatever size was asked for.
- Fix (agent/quiz.py):
  - `_Neighbours` keeps same/other near-twin vote counts; only outvoted questions are dropped (tie: the older one
    stays). Verified: incremental equals one-shot equals brute force.
  - Top-ups continue up to 25 rounds until the target is reached or progress stalls.
  - Extra 10-minute spacing tier.
  - Answer groups that run out are back-filled; `MAX_SHARE` holds traps <= 30% and stay-outs <= 40%.
- Shortfall reason written to quiz_build.json (`short`) and shown in the Quiz tab under the build bar.
- Stand-in 4-year history:
  - 20k: 19,296 -> 20,000.
  - 100k: 24,666 (70% "stay out") -> 27,999 (balanced: 35/33/32, 25% traps).
  - Training 50 rounds on 20k: exam 71.5%.

### 2026-09-24: Hermes actually works (sets itself up)
- Problem: the local backend needed Ollama running and `hermes3:8b` pulled by hand. Otherwise every message failed
  with a ⚠ error.
- `app/brain.py`:
  - Finds Ollama (PATH or the Windows install folders) and starts `ollama serve` hidden.
  - Downloads the model through `/api/pull` in the background with progress.
  - `local_state()` puts the local backend in one word with a next step for the user.
  - `setup()` installs Ollama with winget (Set up button only).
  - Chat runs setup before answering. In auto mode, if Hermes Agent errors it falls back to the local model.
  - Tool loop hardened:
    - models without tool support fall back to plain chat;
    - empty answers after tools are re-asked;
    - malformed tool calls are tolerated;
    - setup errors are kept out of the model's history.
- `app/server.py`:
  - `POST /api/assistant/setup`.
  - The status endpoint has new fields: `local`, `next_step`, `download_pct`, `installing`.
  - A startup warm-up starts Ollama and fetches the model as the app opens.
- `app/settings.py`: `assistant_autosetup` (default on).
- Tested with a fake `ollama` program and server:
  - cold start: starts, downloads 0-100%, chat with a tool call answers "The answer is 4.";
  - not installed: a clear message;
  - stopped: chat starts it and reports the download.
- UI (Set up button, status line) handed to Chat B in TWO_CHATS.md, since Chat B is editing `app/static/`.

### 2026-09-24: Hermes memory in one file, no lingering model
- Request:
  - Memory kept in a simple file, not lost when the app shuts down.
  - Hermes shuts down when you leave the chat tab, until messaged again, with the same memory.
  - 0 lingering time.
- Found: nothing wiped memory on shutdown (it was in `data/memory.db`). The model only saw the last ~12 messages, so
  older chat seemed forgotten.
- `app/memory.py` rewritten over one plain JSON file, `data/hermes_memory.json`:
  - Same functions as before; written atomically after every change.
  - The old SQLite memory is imported once.
  - A damaged file is set aside, not lost.
  - Keeps up to 5,000 chat turns; facts are never dropped.
- `app/brain.py`:
  - The model sees the last 20 messages (was 12).
  - `keep_alive` is sent as the number 0, so the model unloads right after each reply.
  - `sleep()` unloads it now.
- `app/server.py`: `POST /api/assistant/sleep`.
- `app/settings.py`: `ollama_keep_alive` default "0"; v5 migration turns a saved "5m" into "0".
- Tested with the fake Ollama:
  - the old SQLite facts and messages imported;
  - a new fact, a chat and a sleep (unloaded) all worked;
  - after a full restart, the facts and the chat history were all still there.
- Handoff to Chat B: call sleep when leaving the Hermes tab, and fix the memory file name in the Memory panel text.

### 2026-09-24: Hermes chat on a small CPU-only model
- Request: use Llama on the CPU so chat uses less VRAM.
- `app/settings.py`:
  - `ollama_model` default `llama3.2:3b` (about 2 GB).
  - New `ollama_cpu_only` (default true).
  - v6 migration: a saved `hermes3:8b` becomes `llama3.2:3b`.
- `app/brain.py`:
  - Sends `num_gpu: 0` when CPU-only, so no layers go to the RTX 4060.
  - The download message shows the model's size.
  - Status has `device`.
- `hermes/SETUP.md` Option A rewritten: self-setup, CPU only, 0 lingering, one memory file, `ollama rm hermes3:8b`
  to free disk.
- Tested with the fake Ollama: the migration switched the model; it downloaded and answered; every chat request
  carried `keep_alive: 0` and `num_gpu: 0`.
- Handoff to Chat B: the Hermes pill should show `device` instead of "RTX 4060".

### 2026-09-24: Quiz learns from each miss; question bank with an always-on creator; no maximum
- Requests:
  - It should learn each time it gets a question wrong.
  - Swap a missed question's retries for one of the other 5 in its section.
  - No maximum; 10 question creators; always be making questions and store them as markdown.
  - One creator generating at all times; the other 9 idle until Build quiz.
- Learning (`agent/quiz.py` train):
  - After a miss it is shown the right answer and learns it straight away (`CORRECT` 0.25).
  - A missed question's retries are answered on a random section-mate: one of its 5 closest look-alikes, same setup
    group, same answer, from `sections()`. The 5th right answer in a row must be on the question itself.
  - Tested on a 10k stand-in quiz, 800 rounds, 2 seeds: finished 79-82% -> 82.4%, exam 78-79% -> 80-81%. At 0.5
    without swaps the exam fell to 73% (memorising), hence 0.25 + swaps.
- Question bank (`agent/quiz.py`):
  - Fixed calendar half-year slices, each creator result saved in `data/quiz_cache/slices/<label>.npz` and keyed by
    a hash of that half-year's candles. Candidates are stored by candle time, so adding earlier history doesn't
    invalidate them.
  - The bank is `data/quiz_bank/bank.npz` + `meta.json`. Picks under the spacing and mix rules; look-alike checks
    are saved and restored, so new history is appended and only the new questions are compared (verified identical
    to a one-shot check).
  - Markdown: `data/quiz_bank/README.md` plus `questions/<year>.md`.
  - `bank --watch` (started by the app, below normal priority) checks the history every minute. It runs each update
    in a child process (memory handed back after) with one creator and steps aside, after the current half-year,
    when a build asks (`build_request`) or the app closes.
  - Build runs up to 10 creators on what's left (`default_workers`: min(10, threads - 2, free RAM / 0.6 GB)), then
    picks from the bank (`_pick_from_bank`, 0 = all).
  - No `MAX_QUESTIONS`; the API cap is gone too.
- Measured (4-year stand-in, 4-core sandbox):
  - cold bank + 20k quiz: 17 s;
  - build from an up-to-date bank: 2 s;
  - all 28,595: 4 s;
  - 20k new candles with the single creator: 4.5 s.
- Tested:
  - The watcher paused for a build mid-work: it finished its half-year, the build did the other 3, then it resumed
    and found the bank current.
  - Killing only the watcher: the child stopped at the next half-year, released the lock and said why.
  - Training 60 rounds on a bank-built quiz ran fine.
- `app/`: `bank` job; started at app startup (`quiz_bank_auto`); `/api/quiz/build` has no cap (0 = all);
  `/api/quiz/state` includes `bank`. Handoff to Chat B for the number box, a bank line and settings.

### 2026-09-24: Hermes web limited to trading sites; quiz-setups skill; vision models
- Request:
  - Can Hermes's web access be limited to stock/trading sites?
  - Is there a model of similar size that sees charts and learns more easily?
  - Otherwise, keep the program and make skills for each question type.
- `app/tools.py`:
  - `site_allowed()` + `_web_fetch` only open sites in the new `web_sites` setting. Subdomains are covered; an
    entry with a path allows only that section.
  - Only http(s), no logins in the URL; redirects are followed by hand and every hop is checked.
  - Tested: 15 allow/refuse cases (look-alike domains, other sections, localhost) and redirects off the list.
- `app/settings.py`: `web_sites` default list:
  - official data: Fed, BLS, BEA, Treasury, ECB;
  - gold: gold.org, LBMA, Kitco, CME;
  - FX and markets news: FXStreet, Forex Factory, Investing.com, Trading Economics, MarketWatch, Yahoo Finance,
    Investopedia, BabyPips, reuters.com/markets;
  - MT5 docs: mql5.com, metatrader5.com.
- `app/brain.py`: the system prompt says web_fetch is for market research only.
- `.claude/skills/quiz-setups/`:
  - SKILL.md index plus 20 pages: the 18 setups, stay-out and traps.
  - Each covers what the question shows (matches `_candidates`), why pros take it, the trade checked (stop, 2R, the
    clean-win rule), trap signs, the agent inputs (names verified against the 49 features) and what to do when
    stuck.
  - Generated from the creators' rules; the quiz agent can't read them, Claude and Hermes can.
- Hermes tool `setup_guide(setup)`: fuzzy lookup of a page (e.g. "fvg bull" -> Bullish fair value gap).
- Vision models: the small chart-reading models that run in Ollama are about 2-3 GB. They can describe a chart
  image, but can't learn from the quiz without GPU fine-tuning and read exact levels poorly. So: keep the program
  plus llama for chat.

### 2026-09-24: Manual tab backend (from Chat B's spec)
- `app/manual.py` + routes in `app/server.py`, following Chat B's suggested shapes exactly:
  - quote and quotes;
  - order: market, buy/sell limit and stop, GTC or today;
  - close: tickets, partial volume, all / profit / loss / buys / sells by owner and symbol;
  - modify: SL/TP, 0 removes, BE;
  - pending orders list and cancel (some or all);
  - history.
- Orders use magic 0, so they show as "you" and the bot ignores them.
- A real account is refused unless `confirm_real` is set.
- SL/TP must be on the right side and at least the broker's stop level away (a buy's are checked against the bid, as
  MT5 does).
- Pending prices must be on the right side of the market; volume is rounded to the lot step and clamped.
- Bot trades closed here get the ledger hint "manual (app)" and the ledger is synced.
- Tested with a stand-in MetaTrader5 module:
  - every route, the refusals (wrong-side SL, too close, a wrong-side limit, a real account without confirmation);
  - half-close, close losing, close profitable by owner, cancel all, history;
  - a bot trade closed in two halves was recorded as "manual (app)" with the P/L of both halves.

### 2026-09-24: The trading bot learns from each losing trade
- Request (via Chat B's handoff): every losing trade should teach it something straight away, with a floor so one
  bad day can't switch the bot off.
- `agent/ledger.py`: `close_trade` calls `learn.on_mistake` on every losing non-replay close (errors never block
  recording the close); new `get()`.
- `agent/learn.py`:
  - `on_mistake` writes the trade plus a one-line lesson to `data/mistakes.json`.
  - `derive_cautions` makes a setup + side whose latest trades lost need more confidence than those trades had
    (+0.02). This lasts 24 h after the last loss or until a win there. It's capped at the 80th percentile of recent
    entry confidence, and at most half of the setups traded can be under caution.
  - Cautions and the latest lesson go into the rules file at once; the full `learn()` (rules + lessons skill) reruns
    at most every 20 s.
  - The skill has a new "Learning from each mistake" section.
  - `block_reason` checks cautions; replay passes `cautions=False`.
  - Over-blocking fix: `min_confidence` is capped at the median entry confidence and never set from the top bucket.
    On 154 random, mostly losing trades it was 1.0 (block everything); now it's the median and half still pass.
- `agent/quiz.py`: `_bot_mistakes` turns each losing trade's entry candle (from `open_bar`) into a practice-only quiz
  question (answer: stay out; trap of its setup, or stay-out when the setup is unknown), with its own indicator inputs
  and an explanation quoting the lesson. The next Build quiz includes them automatically.
- Tested:
  - a fresh loss created a lesson and a caution;
  - lower confidence was blocked, higher allowed;
  - a win cleared the caution;
  - replay ignores cautions;
  - the caps held;
  - 12 mistakes became 12 practice questions (one outside the history skipped);
  - training and the weak-spot report ran fine.

### 2026-09-24: Manual tab SL/TP anchored to the fill (Chat B handoff)
- `POST /api/manual/order` takes `sl_points` / `tp_points` (the tab's 80 / 160). When they're sent:
  - market orders go in with SL/TP from the quote (so they're never unprotected), then `_anchor_to_fill` moves them
    to exactly that many points from the position's real open price (buy: fill − 80 / fill + 160, sell the other way);
  - pending orders get SL/TP from the order price; the `sl`/`tp` prices the UI sends are only used where no points
    are given.
  - If the move is refused (the price already ran past the new level, or the broker says no), the quote's levels stay
    and the reply has a `note`. The reply also carries the final `sl`, `tp`, the fill `price` and `anchored`.
- Tested on the fake MT5 with 30 points of slippage: buy fill 2650.55 → SL 2649.75 / TP 2652.15; sell, buy limit,
  sell stop, no points (unchanged), only tp_points, the price crashing through the SL (note), negative points refused.

### 2026-09-24: backend for the user's 11 new features (Chat B handoff)
- **3 Connection status:** `/api/manual/quote` adds `connected`, `tick_age` (seconds since the tick changed, timed on
  this PC so the broker's time zone can't skew it) and `market_open` (tradable, and not "no tick for 120 s on a
  weekend" or 30 min any time).
- **6 Trailing stop + auto break-even:** new `app/watch.py`, a 1 s thread inside the app, so it works with the tab
  closed. Settings `manual_be_points` / `manual_trail_points` (0 = off) apply to new manual orders; orders can override
  with `be_points` / `trail_points`; `POST /api/manual/auto {ticket, ...}` sets or clears one (warns on the bot's
  trades); `GET /api/manual/auto`. BE puts the stop at entry + 2 points; the stop only ever tightens. Rules are kept
  in `data/manual_auto.json` and forgotten once the trade is closed.
- **7 Alerts:** `GET /api/events?since=` gives opens, TP / SL hits, other closes (MT5 deal reasons, every owner) and the
  watcher's be / trail moves; the last 500 in memory; no `since` = only `last_id`.
- **8 You vs the bot:** new `app/stats.py`, `GET /api/stats/compare?days=30&mode=` (paper | live | all; default = the
  bot's current stage).
- **9 Trade replay:** history rows add `open_time`, `sl`, `tp`, `reason`, `duration_s` (the final SL/TP comes from
  the watcher, since MT5 forgets them); `/api/bot/trades` rows add `entry_time` / `exit_time`.
- **10 Weekly summary:** new `app/review.py`; Hermes writes it when its model is up, rule-based otherwise; stored in
  `data/reviews/`, last week's is made automatically.
- **12 Settings backup:** backup / list / restore (by name or from a picked file), current settings backed up first,
  unknown or wrongly typed keys ignored.
- **13 First-run checklist:** `GET /api/setup/checklist`.
- Tested with the fake MT5 through the API: quote status; BE at +85 points (stop 2650.27), trail 50 (2651.50, doesn't
  loosen); override orders; events open/be/trail/tp/sl; closed rules forgotten; history reason/SL/TP; stats on 5
  ledger trades (PF 1.83, hold 10 min, curve); review text; backup / restore / bad names refused; checklist shape.
  Test files removed afterwards.

### 2026-09-24: Hermes tab linked to the Hermes Agent app
- The user asked whether we use Hermes and, if so, to link it to the Hermes app. Answer: the tab already talked to
  Hermes Agent's API server (auto mode), but only if you started `hermes gateway` in WSL yourself; otherwise the small
  local model answered.
- Now the app starts it itself (`app/brain.py`): at app start, before a chat (auto / hermes_agent) and on Set up it
  checks for `hermes` in WSL and runs `hermes gateway` hidden, logging to `logs/hermes_gateway.log`.
  - Status adds `agent` / `agent_step`.
  - Agent replies may take up to 30 min, so real tasks (web, terminal, files) can finish.
  - A broken start isn't retried by every chat (10 min pause; Set up retries at once).
  - Settings: `hermes_agent_autostart`, `hermes_agent_cmd`, `hermes_wsl_distro`.
- Tested with a fake `hermes` command:
  - it started and answered with the session header in 1.5 s;
  - "not installed" falls back to the local model;
  - a failing command shows the error at once, and the next chat skips waiting.

### 2026-09-24: Windows pop-ups for TP / SL hits (Chat B handoff)
- New `app/notify.py`: when the watcher records a take profit or stop loss hit (any owner), Windows shows a
  notification, e.g. "✅ Your take profit hit +$40.00 - XAUUSD BUY 0.1 lot closed at 2654.25", so you see it with the
  app minimised. Silent, since the app rings its own bell.
- Setting `desktop_alerts` (default on). It uses `winotify` (added to requirements, Windows only), or PowerShell's
  built-in toast API if that isn't installed; nothing happens off Windows.
- Tested: the toast text for TP and SL, other events skipped, XML/quote escaping in the PowerShell fallback, the
  setting off = no pop-up, and the feature tests (events feed) still pass.

### 2026-09-24: Keybinds and Sounds pages backend (Chat B handoff)
- Settings `keybinds` and `sounds` (default `{}`): objects the UI owns and the server just stores, so they survive a
  reset of the window's storage and ride along in settings backups. Restore accepts only an object for them.
- New `app/sounds.py` + routes:
  - `GET /api/sounds` lists your own sounds;
  - `POST /api/sounds {name, type, data}` adds one (base64; at most 5 MB, else 413; the first bytes must be real
    wav/mp3/ogg/m4a/aac/flac/webm audio, else 415);
  - `GET /api/sounds/{id}` plays it;
  - `POST /api/sounds/{id}/rename` and `DELETE /api/sounds/{id}`.
  Files go to `data/sounds/`.
- Tested:
  - a wav and an mp3 upload (data: URLs are fine too), list, play back with the right type, rename, delete;
  - a non-audio file, and audio claiming the wrong type, give 415; 5 MB+ gives 413; bad base64 or a blank name
    gives 400; unknown ids give 404;
  - keybinds survive backup and restore, and wrong types are ignored.

### 2026-09-24: speed pass: bot ledger sync throttled (Chat B handoff)
- `mt5_service.sync_bot_ledger()` now runs at most once every 2 s. The window polls `/api/bot/trades` every 2 s (plus
  the calendar and Review), and the agent already syncs every second, so the same MT5 history lookups kept repeating.
- Closes still show at once:
  - the Close button (`close_position`) and the watcher (a bot position vanished) mark it stale, so the next poll
    syncs;
  - the kill switch and bulk closes force a sync.
- Tested: a burst of 10 polls = 1 sync; after a Close the next poll syncs; after 2 s it syncs again; forcing always
  syncs.

### 2026-09-24: Windows' own pop-ups off by default (Chat B handoff)
- The window now shows its own custom pop-ups at the top right (Chat B), so `desktop_alerts` defaults to false and
  settings v7 switches it off once in existing settings files; the user can turn it back on ("Also show Windows' own
  pop-up"). Tested: a v6 file with it on -> off and v7; turning it on afterwards sticks; fresh install -> off.

### 2026-09-24: Telegram alerts on your phone
- New `app/telegram.py`: every event the watcher records (by default TP, SL, open, close; break-even and trailing
  moves can be added) goes to your own Telegram bot, through a background queue so trading is never held up.
- Set up once: make a bot with @BotFather, paste the token, message the bot, press "Find my chat"
  (`POST /api/telegram/detect` saves the chat id and says hello); `POST /api/telegram/test`; `GET /api/telegram/status`.
- Settings `telegram_enabled`, `telegram_token`, `telegram_chat_id`, `telegram_events`.
- Tested against a fake Telegram API:
  - clear errors for a missing or wrong token and for no chat yet;
  - detect saved the chat and said hello; the test message was sent;
  - with alerts off nothing was sent; with them on, open / TP / SL arrived in the right wording, and break-even
    (not in the list) didn't.

### 2026-09-24: recommendations, part 1: news pause, spread limit, is the quiz agent worth it?
- **News pause** (`agent/news.py`): the week's calendar from the public ForexFactory feed, cached and refreshed every
  6 h. The bot opens no new trades 15 min before to 15 min after high-impact USD news (settings `news_pause`,
  `news_before_min`, `news_after_min`, `news_currencies`, `news_impact`). `GET /api/news` gives the next events and
  whether it's paused now. Offline, it keeps the last calendar.
- **Spread limit on the Manual tab:** `manual_max_spread` (80 points, 0 = off) refuses a market order when the spread
  is wider, unless sent again with `ignore_spread`. The quote adds `max_spread` / `spread_ok`. The bot already had its
  spread filters.
- **Quiz second opinion measured:** every bot trade (live, paper and replay) records what the quiz agent said at entry
  (new ledger column `quiz`), even with its filter off. `GET /api/stats/quiz` compares agreed / disagreed / no opinion
  and gives a verdict once there are ~30 of each (a long Replay is the fastest way).
- Tested:
  - news: in window / after it / other currency / off / medium impact, the API, and the agent's flags;
  - spread: refused at 25 > 20, sent with `ignore_spread`, pending orders unaffected;
  - quiz stats on 120 trades (verdict right; "not enough" for an empty mode);
  - `agent.run` / `agent.replay` start fine with the new flags.

### 2026-09-24: recommendations, part 2: watchdog, daily data backup, trade notes
- **Watchdog** (`app/watchdog.py`, every 10 s):
  - if the bot's process dies with an error while you had it running, it's started again (3 times an hour at most,
    then it stays stopped and tells you);
  - "stuck" alert when it hasn't reported for 5 min while the market ticks;
  - MT5 closed / disconnected for a minute, and back again.
  All go to the app's pop-ups (events feed) and Telegram (category "watchdog", on by default; settings v8 adds it).
  Stopping it yourself or the kill switch never triggers a restart.
- **Daily backup of all data** (`app/backup.py`): one zip a day with a consistent copy of trades.db, settings, Hermes
  memory, rules/lessons/mistakes, notes, reviews, sounds, models. Settings `backup_dir` (point it at OneDrive/USB),
  `backup_keep` 14, `backup_daily`. `POST /api/backup/data` makes one now.
- **Trade notes:** write why you took a trade and tag it (`/api/manual/notes`, or `note`/`tags` on the order); history
  shows them and the weekly review says which tags made or lost money.
- Tested:
  - watchdog: a crashing bot was restarted 3 times, then gave up with the last log line; a clean exit and your own
    stop didn't restart it; stuck was detected; MT5 down after 60 s, then up;
  - backup: zip contents, keep-N pruning (same-second names and ordering fixed);
  - notes: saved on the order, edited, shown in history, removed, used by the review.

### 2026-09-24: recommendations, part 3: honest backtest report
- `POST /api/backtest/start` runs the Replay engine over the model's unseen test period at full speed with the
  threshold rule, no learned rules (they could come from those months), and costs on top of the candles' spread:
  commission per lot (setting `backtest_commission`, 7) and slippage on every market fill (`backtest_slippage`, 10
  points; take profits are limits, so no slippage).
- It keeps its own ledger (`data/backtest.db`), so your stats, lessons and the stage ladder never see it.
- `agent/backtest.py` writes `data/backtest.json` + `.md`: win rate, net, PF, expectancy, score, max drawdown, per
  month, each Paper -> Demo gate line passed or not, and a verdict. `GET /api/backtest` gives progress and the report.
- Tested:
  - costs: a 1-lot stop that would lose $80 lost $107 (slippage in and out + $7), a take profit $143 instead of $160;
  - the report on 150 synthetic trades (gate table and verdict right);
  - a full run over 29,430 test candles with a real trained model and separate files (the real ledger stayed
    empty). That model didn't trade: the sandbox's synthetic candles gave it no confidence.

### 2026-09-24: recommendations, part 4: automated tests + CI
- `tests/` with pytest (`python -m pytest -q`, ~5 s), 26 tests:
  - `tests/fake_mt5/MetaTrader5.py` stands in for MT5;
  - `conftest.py` redirects every file the app and agent write to a temp folder, so the tests never touch real data.
- Covered: manual orders (anchoring with slippage, pending, bad input, real-account guard, spread limit), notes +
  history, break-even/trailing + events, sync throttle, watchdog (crash restarts, clean exit, stuck, MT5 down/up),
  settings backup/restore + migrations, sound files, data backup, you-vs-bot stats, quiz agreement, weekly review,
  Telegram (fake API), news pause, backtest costs + report, Hermes Agent auto-start, the memory file.
- `.github/workflows/tests.yml` runs them on GitHub for every push; `requirements-dev.txt` (pytest). TWO_CHATS
  routine step 5 and CLAUDE.md now say to run the tests before pushing.
- Found while writing them: the Hermes gateway log path was fixed (now `brain.GATEWAY_LOG`, so tests can redirect it).

### 2026-09-24: demo video; notification fade handed to Chat B
- Recorded a 2 min 20 s walkthrough of today's features (demo copy of the app, simulated MT5 with moving prices and
  broker SL/TP hits, stand-in Telegram, Playwright + ffmpeg): `demo-new-features.mp4` (git-ignored).
- The user wants notifications to fade out over 0.9 s instead of vanishing. That's UI, so the full spec is in
  TWO_CHATS "For Chat B": 0.3 s -> 0.9 s in app.css and notify.html, the 450 ms fallback timer, and an opacity fade
  even with reduced motion.

### 2026-09-24: the app now really updates itself
- The user's shortcut kept opening an old version. `Trading Bot.bat` ran `git pull --ff-only -q >nul 2>&1`, which
  gives up silently when the copy is on another branch, has no tracking, has local edits or commits, or isn't a git
  clone (ZIP), and hides errors like a GitHub sign-in.
- New `app/update.py`, run by the .bat before the app opens:
  - fetches the shared branch; stashes local edits; keeps local-only commits on a backup branch;
  - switches to GitHub's version and sets tracking;
  - says clearly when there's no git, no internet or no .git folder;
  - writes `logs/update.log` and `data/update_status.json`.
  `/api/status` now has `version` (commit, date, branch, last update).
- The .bat's update-to-start part is now one parenthesised block (cmd parses it at once), so an update that rewrites
  the .bat can't garble the run.
- README: clone with git; a one-time fix for a copy that's stuck.
- Tests: 6 new against real temporary git repos (old copy, other branch, local edits, local commits, offline, ZIP,
  status/log). 32 pass.

### 2026-09-24: why updates never reached the user's PC
- The quiz rewrote `.claude/skills/quiz-weak-spots/SKILL.md`, a tracked file, so every `git pull --ff-only` failed
  silently. The user updated by hand (`git stash` + `git checkout -B ...`).
- Now the app-written skill files are ignored and untracked: `m1-bot-lessons/`, `quiz-lessons/`,
  `quiz-weak-spots/SKILL.md` and its generated references. Claude's `claude-*.md` pages stay tracked.
- `app/update.py` also renames an untracked local file that blocks a checkout to `<name>.local-<time>` and retries.
- 34 tests pass (2 new: an untracked file in the way; an app-rewritten file).

### 2026-09-24: MCP bridge fixed; quiz report (traps) analysed
- **MCP bridge:** the user's setup checklist said "MCP bridge not running" and Start bridge did nothing.
  - The bridge itself works (tested with mcp 1.30: it answers `initialize` on :8765/mcp).
  - The checklist only looked at the app's own process. A bridge left over from an earlier session (after the
    update) held port 8765, so every new bridge exited at once, silently.
  - New `app/bridge.py`:
    - asks the port itself (`probe`: our bridge / another program / nothing);
    - `start()` replaces a leftover bridge (psutil; reuses it if that isn't allowed) or starts one, waits for it to
      answer, and returns the reason from logs/mcp.log when it dies;
    - another program on the port is named.
  - `/api/mcp/start` returns 500 with the reason; there's a new `GET /api/mcp/status`; the checklist uses it.
    `app/main.py` starts the bridge through `bridge.start` in the background (FYI to Chat B).
  - 3 tests, 37 pass.
- **Quiz report** (73,667 questions, exam 69.7%): real setups 66–98% on the exam, traps 5–36% with 9,986 stuck.
  - Tried "keep a trap only if most look-alikes agree" on a 12k quiz, 400 rounds: exam 72.3% -> 71.0%, traps 13 -> 17%,
    stay-out spots 65 -> 56%. Not kept.
  - New page `quiz-weak-spots/references/claude-traps-look-like-winners.md`: traps look like winners, so don't press
    Work on these for trap groups; do it for fair value gaps; judge the agent by its exam on real setups.

- 2026-09-24: quiz report 22:34 (mid-run, no exam yet): traps finished 18% -> 41% while trap practice accuracy stayed at 58%, which means memorising. Added an update to `claude-traps-look-like-winners.md` (check the real-setup exam at the end; Continue if it dropped).

### 2026-09-25: quiz report stops sending the user to grind on traps
- Three pasted reports in a row listed only trap groups as weak spots, each saying "Work on these", which is the step
  that memorises and pushes out real knowledge.
- `agent/quiz_report.py`: weak spots now lead with real setups (up to 6); at most 2 trap groups (`TRAP_SPOTS`) keep
  the trap check visible. Trap spots say "Don't press Work on these" and why. Every group has `grind` (false for traps)
  so the app can hide the button. Checked on the sandbox quiz; 37 tests pass.

### 2026-09-25: paper bot no longer idles for an hour after starting
- The user's bot "wasn't doing anything": paper practice mode needs 60 readings (one per candle) before it trades,
  and that count started from zero on every start, so every restart meant an hour of waiting.
- `agent/run.py` now scores the last day of closed candles (up to 1,440) when it starts, and `Practice.seed()` loads
  them, so it trades its top ~10% setups from the first new candle. If scoring fails it falls back to learning live.
- 2 tests (`tests/test_practice.py`); 39 pass.

### 2026-09-25: The confidence slider drives the agent; Hold to flatten resets the bot
- The user saw "Needs 12% to enter" on the Bot trade card while the slider said 0.07. Two causes:
  - Practice mode entered on its own "top 10% of readings" bar and ignored the slider.
  - A running agent only read the slider once, at Start.
- Now entries always use the slider, practice mode included. The agent gets `--settings data/settings.json` and
  re-reads `threshold` every candle; a change is printed in the live log. Practice mode only reports `top10` in the
  status (where its best ~10% of readings start), for the card.
- `POST /api/kill` (Hold to flatten) now resets the bot:
  - it stops the agent and closes its MT5 positions;
  - it closes any paper trades still open (reason `kill`, at the current price);
  - it clears `data/agent_status.json`.
  Stage progress, history and lessons are kept.
- UI handed to Chat B:
  - the status text under Start agent was wrapping one word per line;
  - the card's "Needs" line;
  - the flatten button's label and instant clear.
- Tests: `tests/test_kill_reset.py`; 41 passed.

### 2026-09-25: Why the bot didn't trade with high confidence: hidden trading hours
- Checked end to end: the real agent was run against a simulated live market (a trained model and an MT5 stand-in
  serving candles, one a second, in a scratch copy).
  - At 10:00 server time it opened on the first candle and filled all 10 slots.
  - At 07:00 every reading was "skipped: outside session". New entries were only allowed 09:00-22:00 server time,
    fixed in `agent/config.py` with no setting. The user's screenshot was at 07:06.
- Fix:
  - Entries are allowed all day by default, set by `trade_hours_start`/`trade_hours_end` (a start later than the end
    wraps midnight), passed as `--hours` to agent.run and replay/backtest. The 23:00-01:00 rollover pause stays.
  - Re-run at 07:00: it opened at once, and a slider change while running applied on the next candle.
- The other thing that can overrule the slider: **loss cautions** (after losses on a side, that side needs more
  confidence for 24 h). They are on purpose, and the "Use learned rules" switch turns them off.
- Skip reasons are now in plain words. `agent_status.json` gets `last_hour` (outcome counts over 60 candles) so the
  card can show what's blocking it (Chat B handoff: trading-hours pickers + that line).
- Tests: 43 passed.

### 2026-09-25: Chart dots handed to Chat B
- The user wants dots on both charts (Manual and bot): yellow at entry, green at TP, red at SL. They may overlap. The
  full spec is in TWO_CHATS.md (For Chat B) and replaces the thin SL/TP lines idea. The backend already serves every
  field.

### 2026-09-25: Manual tab without double-click confirms (handed to Chat B)
- Every click-twice confirm on the Manual tab is UI-only (`app/static/app.js`): Buy/Sell arming, spread "send
  anyway", bulk close, Cancel all, position close. Full list handed to Chat B. The real-money "type REAL" check stays
  (backend `confirm_real`).

### 2026-09-25: Bot tab backend: Co-pilot / Full Auto, live card, symbol switch, points (UI to Chat B)
- **No warm-up:**
  - The agent now always scores the last 1440 closed candles on start (before, only in practice mode). The
    confidence rank is ready at once, and it decides on the current candle within seconds of Start.
  - The indicators already got 5000 candles up front.
- **Co-pilot mode** (`bot_mode` = `copilot`; Full Auto = `auto`, the default). The agent re-reads the mode every
  candle. When every check passes, instead of sending the order it:
  - writes `data/copilot.json` (symbol, side, entry, TP, a one-sentence reason, a 0-100 confidence rank, expiry);
  - checks every second for `data/copilot_decision.json` (written by `POST /api/copilot/decide`);
  - on Approve, re-prices at the current tick and sends. Skip drops it. On timeout it sends when
    `copilot_auto_execute` is on, otherwise drops it (`copilot_seconds`, default 30).
- **`GET /api/bot/live`:** one call for the full-screen card:
  - headline sentence, confluence pills (trend / momentum / volatility / execution ready), confidence rank;
  - heartbeat (broker / AI / feed), points (realized score + floating P/L, today);
  - open positions with entry, TP, progress and points;
  - the proposal.
  It has **no stop loss anywhere**, and a test walks every key. Stops stay in the orders.
- **Other routes:**
  - `POST /api/bot/symbol` restarts a running agent on the new symbol (it needs a trained model).
  - `POST /api/bot/mode`, and `GET /api/bot/symbols`.
- **New settings:** `bot_mode`, `copilot_seconds`, `copilot_auto_execute`, `display_timezone`.
- **New module** `agent/livecard.py`: the plain-words card.
- **Verified:** the real agent ran against the simulated market:
  - Co-pilot: approve -> filled, skip -> nothing, timeout with auto-execute -> filled.
  - Full Auto: opened on the first candle.
  - Tests: 48 passed.
- The full-screen Bot tab UI is handed to Chat B with the full contract.

### 2026-09-25: Market -> Bot tab merge handed to Chat B; Bot tab checked headless
- The user wants the Bot tab to replace Market. Spec to Chat B:
  - the chart becomes the Bot tab's main area, with the live card on the right;
  - one symbol switcher drives both the bot and the chart;
  - no SL on this tab's chart (stop hits drawn as grey exits);
  - "Size a trade" moves to Manual;
  - `dash` links and keybinds map to `bot`.
- Headless test of Chat B's Bot tab against the real server (fake MT5): no console errors or 5xx. One bug: the mode
  note toast lands on the mode switch and hover-holds, so you can't switch back until the mouse moves. Handed to
  Chat B.

### 2026-09-25: Learned confidence bar blocked every trade (0.20 vs a model reading 0.05-0.10)
- The user's Bot tab showed:
  - "held back: learned: confidence 0.09 below 0.20";
  - 9 of 9 candles skipped for that reason;
  - no trades at all.
- Cause: `learned_rules.json` had `min_confidence` 0.20. It was learned from trades on another confidence scale
  (the learner also reads Replay trades, possibly from an older model), while the current model reads 0.05-0.10.
- Fix: `learn.block_reason(..., recent_probs=)` caps the learned bars at the live model's own last day of
  readings: the median for `min_confidence`, the 80th percentile for loss cautions. run.py passes `ranker.seen`.
  - A stale bar can no longer block everything.
  - Below-median readings are still filtered.
  - Replays are unchanged (they pass no readings).
- Test in `tests/test_practice.py`; 49 passed.

### 2026-10-01: CandleSenseICT.mq5 - one advanced EA instead of the ML pipeline
- The user wanted one extremely advanced EA instead of the multi-file ML pipeline
  (CandleSenseML/CandleSenseMulti), built by researching and borrowing from real gold EAs.
  **`ea/CandleSenseICT.mq5`** (+ `ea/README.md`), researched via WebSearch/WebFetch:
  - FVG detection with a 0-100 quality score (gap size, displacement, H1 trend align,
    freshness, premium/discount) and Order Block confluence, adapted from the MIT-licensed
    [foeed/FvgGold-EA](https://github.com/foeed/FvgGold-EA) (45% win rate, +48.7% 6-month
    backtest) after fetching and reading its actual source.
  - ICT killzones (London, NY, overlap, GMT), the standard filter in the public gold EAs found.
  - Liquidity sweep detection kept from CandleSense.mq5, now a confluence bonus.
  - Risk-based sizing via `OrderCalcProfit()` from the start (the fix v1.50 made after the
    fact to its tick-value bug).
  - Self-learning setup weights (4 combinations: FVG only / +OB / +sweep / +OB+sweep), each
    scored from its own closed-trade history via global variables, same idea as CandleSense's
    per-signal weights but per ICT setup type.
  - Break-even + ATR trailing, daily loss limit, max trades/day, spread filter.
  - Caught and fixed two bugs before shipping: functions called before their forward
    declaration (would not compile), and ATR/EMA indicator handles being recreated every call
    instead of once in `OnInit` (handle leak that would eventually return `INVALID_HANDLE`).
- **Not tested here**: this cloud session has no `mcp__mt5__*` tools (those only exist on the
  user's PC via the `mt5-m1-trader` subagent) and no MetaEditor, so it could not be compiled or
  backtested from this session. `ea/README.md` says how to do both on the user's PC.

### 2026-10-01: CandleSenseICT HUD + diagnostics, and CandleSenseSwing (a simpler stacking EA)
- **CandleSenseICT.mq5 v1.01**: added back the on-chart Trades/Earned/Lost/Subtotal panel (same
  minimal style as CandleSense.mq5 v1.40), wired to real closed-deal profit via
  `OnTradeTransaction`.
- **v1.02**: user reported it running (HUD showing, Trades: 0) but never placing a trade.
  `TryEnter()` was silent on every skip reason, so added a `Print()` at each early-return (max
  open, max/day, daily loss limit, killzone with the computed GMT hour, spread, no qualifying
  FVG, score below threshold, already-traded bar) so the Experts/Journal log shows exactly which
  gate is blocking it. Prime suspect flagged to the user: `GMT_Offset_Hours` defaults to 0
  (assumes broker server time = GMT), but the user's chart time (06:05) vs their own clock
  (11:05 PM) suggests their broker isn't actually on GMT, which would silently misalign the
  killzone window and block every entry.
- **`ea/CandleSenseSwing.mq5`** (new): the user described a different style they'd seen - "just
  go with where the chart's going", very low take profits, up to 60 trades stacked at once with
  a -150 point SL / +200 point TP. Built as a separate, much simpler EA rather than folding it
  into CandleSenseICT: EMA-slope trend direction (no FVG/OB/killzone logic), fixed-point SL/TP,
  stacks another trade once price has moved `MinStackPoints` further in the trend's direction.
  Sizing: `MaxTotalRiskPct` caps what ALL open trades losing together would cost and splits that
  budget across `MaxOpenTrades`, instead of a flat risk % per trade (which would let worst-case
  loss scale unbounded with trade count). Same HUD style, plus an "Open now: N / max" line.
  Caught and fixed a forward-declaration issue (HUD_Update called CountMyOpenTrades before its
  definition) before shipping. `ea/README.md` updated with both EAs' sections.
- Not tested live here either (no MT5 access from this cloud session, as before).

### 2026-09-30: CandleSense.mq5 v1.50 installation guide
- **CandleSense v1.50 in /scratchpad/CandleSense/CandleSense.mq5**: rule-based EA with corrected position sizing via `OrderCalcProfit()`. Replaces v1.40 which underestimated risk (tick value vs broker-specific per-lot cost). 
- Installation: copy to `%APPDATA%\MetaQuotes\Terminal\<TerminalID>\MQL5\Experts\`, compile with MetaEditor F7, attach to chart.
- Settings: `RiskPercent` (default 0.25%), `RewardRisk` (default 2.0), adjust per strategy.
- Tested: backtests on XAUUSD H1 (before v1.50) showed +23.7% gain with 989 trades, now with correct sizing.

### 2026-10-01: CandleSenseSwing v2 - trades every swing, both ways
- The user's v1 run showed 12 trades, -149.60, and they asked for it to trade all swings, not only
  the ones the 3-bar EMA slope "confirmed". v2 drops the EMA entirely and reads swing highs/lows
  on M1 (a bar beating `SwingStrength`=2 bars each side): latest swing low -> buy, latest swing
  high -> sell. Always has a direction; first trade of each new swing fires at once, then stacks
  every 60 points with the swing, up to 60 open. Same 150/200 SL/TP and total-risk-capped sizing.
- HUD gets a Swing line (UP/DOWN from price) and a Win rate line (with the 43% break-even for
  150/200); box grown to fit. Failed orders now print their retcode.
- Not compiled or tested here (no MT5 in the cloud session).

### 2026-10-01: CandleSenseSwing v2.10 - a new trade every 5 seconds
- User: "not trading again, make it create a new trade point every 5 seconds". Added a 5 s timer
  (`EntryEverySeconds`) that opens a trade with the current swing each time until 60 are open;
  `MinStackPoints` default 0. Direction flips at once when price breaks past the swing point.
- Likely cause of "not trading": `MaxSpreadPoints` 40 vs the demo's gold spread of 38-70 points
  (screenshots). Raised to 120. The HUD now shows a "Last:" line with the last trade or skip
  reason; skips print only when the reason changes.

### 2026-10-01: simulated trading-every-second before building it (ea/frequency_study.py)
- User asked for a bot that trades "almost every second" in bunches on their $5M demo. Simulated
  it first on the repo's real XAUUSD M1 data (349 candles replayed as per-second ticks) with the
  demo's own 45-point gold spread and the EA's current 8%/60-trade sizing.
- Result: loss scales linearly with frequency. Every 300 s: -$280k. Every 5 s: -$16.1M. Every
  1 s: -$62.7M in 5.8 hours on a $5M account - it blows up 12x over. At the minimum 0.01 lot it
  still loses $14,115 in the same window, so sizing is not the fix.
- Cause: SL 150 / TP 200 needs a 42.9% win rate; a 45-point spread drags a coin-flip bot to 30%.
  The strategy must supply that 12.9-point gap every trade, and frequency cannot create it -
  it only pays the spread more times ($7.2M/hour in spread alone at 1 trade/second).
- Did not build the every-second version. Told the user the honest result and the alternative
  (fewer, higher-quality trades - i.e. fixing CandleSenseICT's killzone GMT offset so the
  selective EA actually runs).

### 2026-10-01: tested "study the chart but still trade a lot" (ea/pattern_study_test.py)
- User's follow-up idea: have the bot learn from past chart movements but keep trading constantly.
  Tested it properly - learned 3-candle patterns on the first 60% of the real gold data, traded
  the unseen 40%, with the demo's 45-point spread and SL150/TP200.
- The study does tilt the odds (after UUU price rose 63.6%, after DDD only 25.8%), but the
  out-of-sample win rate was 33.3% over 132 trades - below the 42.9% needed. Still a loss.
- The useful finding is the selectivity gradient: raising the confidence bar cut trades from 132
  to 22 (6x fewer) and cut the loss from -4,400 to -500 points (9x smaller). Fewer, better trades
  lose less - the same direction the frequency study pointed. "Study + trade constantly" doesn't
  escape the spread; the study has to buy selectivity, not volume.
- Caveat recorded in the script: 349 candles is 5.8 h of one day, so these specific patterns are
  mostly noise. The repo already has the right version of this idea done properly -
  CandleSenseML (XGBoost on 3.3 years, PF 1.15-1.17 on unseen months, ~300 trades/year).

### 2026-10-01: tested "highest win rate" and "pick the best performer daily"
- User wants the highest win rate possible and a daily pick of the best-performing strategy.
  Tested both on the real gold data before building either.
- **Win rate is the wrong target** (`ea/winrate_vs_money.py`): same bot, same data, only the
  stop/target changed. A 600pt stop with a 20pt target wins **94.8%** of trades and still loses
  1,420 points, because one loss erases 30 wins. Every SL/TP pair tested lost money, with win
  rates from 8.7% to 94.8% - win rate and profit are close to unrelated. What decides it is
  expectancy = (win rate x avg win) - (loss rate x avg loss). The HUD's Subtotal is the honest
  line; the win-rate line can be gamed to look perfect.
- **Daily "best performer" selection is noise at that sample size** (`ea/daily_selector_test.py`):
  ranked 10 strategy configs across 6 periods. The winner of each period ranked on average
  **6.0 of 10** in the next period - chance is 5.5. 4 of 5 picks fell off immediately. Strategy
  performance mean-reverts; selecting on one day picks the strategy whose conditions just ended.
- The statistically sound version of the user's idea already exists in this repo: the
  CandleSenseMulti trainer selects per symbol on a long validation window with real gates
  (>=30 trades, PF >= 1.15, >= 0.05R per trade). That is "pick the best performer" with enough
  data behind it to mean something.

### 2026-10-01: ran the "$100 -> $10,000 in a day, recklessly" request (ea/reckless_test.py)
- User (away from their PC) asked to simulate the 94.8%-win-rate 600/20 setup repeatedly until it
  made $10,000 in a day from $100. Ran it: 10,000 simulated days across 5 risk levels (5% to 90%
  per trade), compounding, on resampled real gold minute-moves.
- Result: **0 of 10,000 runs reached $10,000. 100% were wiped out** at every risk level.
- The binding constraint is structural, not tuning: with $100 and a 600-point stop, MT5's minimum
  0.01 lot already risks $6 = 6% of the account. You cannot size below ruin. Per-trade EV at that
  size is (0.95 x $0.20) - (0.05 x $6.00) = -$0.11, so more trades only arrive at zero faster.
- Reframe given to the user: $10,000/day on their existing $5M demo balance is 0.2%/day, which is
  an achievable target. The same $10,000/day from $100 is a 10,000% daily return, which no
  strategy produces. The goal is reachable; the $100 starting point is what makes it impossible.

### 2026-10-01: what a small account can actually earn (ea/small_account_study.py)
- User asked what $25 then $100 at 1:100 leverage could make per day, compounding day and night.
- Key distinction established: leverage sets MARGIN (0.01 lots of gold = $4,170 notional, $41.70
  margin at 1:100), not RISK (a 150pt stop on 0.01 lots loses $1.50 whatever the leverage).
  Raising leverage buys position count, not profit.
- $25 fails structurally: the minimum 0.01 lot risks $1.50 = 6% of the account, 24x the 0.25%
  CandleSenseML was backtested at; its 6.5% drawdown becomes 156%. 22% of simulated years busted.
- $100 at 1:100 works: $1.50 is 1.5% risk, 2 concurrent positions, 0% busted across 500 runs at
  every horizon out to 3 years. Median: $104 after a month, $155 after a year, $369 after 3 years
  at a good 0.2%/day.
- The honest headline for the user: 0.2%/day on $100 is $0.20/day. The bot controls the
  percentage; the balance controls the dollars. $10,000/day at 0.2% needs $5M - which their demo
  already has.

### 2026-10-01: CandleSenseStart.mq5 - an EA designed for a ~$100 beginner account
- User asked for the best EA for a beginner with a low starting balance, making the most it can.
  Built `ea/CandleSenseStart.mq5` with every parameter chosen from the measurements made today
  rather than by feel.
- Swept stop/target against the real 45pt spread first: at 150/200 a strategy must beat random by
  12.9% every trade; at 1:2.5 with a 250pt stop only 5.1%. Widening the target is the single
  cheapest improvement available to a small account, so the EA uses ATR stops (min 200 pts) with
  a 2.5x target.
- Strategy: H1 EMA50/200 trend + pullback to the M15 EMA20 closing back with the trend. Selective
  by design (the frequency study showed more trades = linearly more loss).
- Beginner protections: daily loss limit (6%), pause after 3 consecutive losses, hard balance
  floor that halts the EA, margin check before every order, and a start-up warning under $80 where
  the minimum lot exceeds the chosen risk.
- **Auto-detects the broker's GMT offset** (`TimeTradeServer()` vs `TimeGMT()`), removing the
  class of bug that silently stopped CandleSenseICT from ever trading.
- Lots compound from the current balance each trade. HUD shows balance, growth since start, win
  rate against the break-even it needs, net, risk per trade, the detected GMT offset and a plain-
  English status line.
- Not compiled or backtested here (no MT5 in the cloud session). Needs demo validation.

### 2026-10-01: projected CandleSenseStart on $100 / 1:100 (ea/start_projection.py)
- Simulated the EA's real mechanics 1,000 times per scenario over a trading year: 2% risk, 1:2.5
  targets, the 0.01-lot staircase, the daily loss limit, the 3-loss pause and the $50 floor.
- Margin checks out: 0.01 lots needs $41.70 at 1:100, and a 200pt stop at 0.01 lots risks exactly
  $2.00 = the 2% the EA targets on $100. The design lands right on the minimum-lot boundary.
- Break-even is 28.6% at 1:2.5. Median balance after 1 year by true win rate:
  25% -> $0 (92% busted) | 28.6% -> $79 | 32% -> $195 | 35% -> $404 | 40% -> $1,729 | 45% -> $8,141
- Drawdowns are large even when winning (21-33% median at 35-40%), which is normal for a 1:2.5
  system with a sub-30% break-even but worth warning the user about before they watch it live.
- The real win rate is unknown until the demo run - that is the number the whole thing turns on.

### 2026-10-01: researched what actually works (ea/WHAT_ACTUALLY_WORKS.md)
- User asked how people make so much with their own bots and to find known-good ones.
- Findings: ~1% of day traders are consistently profitable, ~90% lose money in year one,
  and algo strategies that do work average **15-25% a year** - not a day. Documented real
  examples: 9.5%/yr at 23% max DD; 11.5% compounded across 742 trades.
- The Myfxbook accounts showing +9,000% are overwhelmingly grid/martingale: no stop loss,
  hidden floating drawdown, lots growing after losses, killed by trend persistence and the
  margin call rather than by the reversal. Same shape as our own 600/20 test (94.8% win rate,
  still loses money) - we measured the pattern before finding it documented.
- What separates professionals is validation, not strategy: walk-forward optimisation, decay
  analysis (out-of-sample vs in-sample metrics), Monte Carlo trade reshuffling, placebo tests.
  Recorded the confidence ladder: backtest 20%, out-of-sample 40%, walk-forward 60%, forward
  test 80%, demo 90%.
- Noted that CandleSenseML's trainer already implements the professional methodology
  (chronological splits, unseen-month hold-out, costs in the labels, PF/trade-count gates),
  and its modest PF 1.15-1.17 is the believable shape of a real edge.

### 2026-10-01: fleet launcher (agent/fleet.py, agent/FLEET.md)
- User asked for a small terminal app that connects to MT5, launches multiple ML bots across
  symbols, and starts them all up - then for the controls to live in Telegram rather than the
  terminal (/stop /start /pause /total /prof /loss).
- `agent/fleet.py`: one `agent.run` subprocess per symbol (isolation - one crash can't take the
  others down, dead bots auto-restart), a read-only terminal dashboard fed by the ledger, and
  `--scan` which checks each symbol's spread against its typical M1 range, refusing anything over
  25% (the cost study is why). Only symbols with a trained model in `models/` are eligible, so the
  fleet can't trade something `agent.train` never validated.
- Telegram: added `register_command()` / `unregister_command()` to `app/telegram.py` so other
  modules can answer commands without it importing them. The fleet registers /stop /start /pause
  /status /bots; /total /prof /loss were already handled there from the ledger. The existing
  chat-ID restriction means only the owner can stop the bots.
- **Stopping is a drain, per the user's correction**: /stop ends the bot processes at once (so no
  new trade can open) but never force-closes open trades - they keep their broker-side SL/TP and
  are left to finish. The fleet holds in `draining`, syncing the ledger so results are still
  recorded with no bot running, then flips to `stopped` and messages the user. /start cancels a
  drain in progress.
- Tested the state machine with fake processes and a fake ledger: start -> stop(2 open) ->
  draining -> stays draining while open -> stopped + notification when the last closes; /start
  cancels a drain; /stop with nothing open stops immediately.
- Caught before committing: an f-string with nested same-quotes (invalid on Python 3.11).

### 2026-10-01: multiple agents per symbol, trading independently
- User asked whether several agents could trade gold at once without interfering. Yes, on a
  hedging account (theirs is "Demo Account - Hedge"), and most of the mechanism already existed:
  `LiveBroker` filters positions by magic number, so each instance only sees its own.
- What was missing, now added:
  - `agent/ledger.py`: `agent` and `magic` columns (auto-migrating, same pattern as the earlier
    additions) and `agent=` filters on `open_trades`, `recent` and `stats`, so each instance's
    win rate and P/L are tracked separately.
  - `agent/run.py`: `--magic` and `--agent`, plus a warning when a custom magic is used on a
    NETTING account - there MT5 nets positions per symbol, so agents would silently close each
    other's trades.
  - `agent/broker.py`: both brokers carry an agent name onto every ledger write.
  - `agent/fleet.py`: `--agents N` with `plan_agents()` giving each instance its own magic AND a
    different entry threshold (0.50/0.55/0.60 for three). Identical agents would take identical
    trades - one agent at 3x size paying 3x spread - so they are deliberately spread apart.
    Dashboard and /bots now show per-agent rows.
- Tested with fakes: 3 agents on gold, one long and one short simultaneously, fully separate
  ledger stats; /status, /bots and the /stop drain all correct per agent.
- Documented the honest limits in FLEET.md: margin, account equity and market exposure are still
  SHARED. Agents on one symbol with similar models agree, which concentrates risk rather than
  diversifying it - real diversification comes from different symbols.
- Caught two bugs in my own patch before committing: an invented function name
  (`symbolless_name`) and a comment displaced onto the wrong line.

### 2026-10-01: does running more bots make more? (ea/multibot_study.py)
- User asked whether several small-compounding bots would earn more than one. Simulated 2,000
  years per scenario across bot counts and correlations.
- Splitting the same money between bots does NOT raise the return. 3 identical bots return
  $157 vs $156 for one - they see the same candles and take the same trade, minus the extra
  spread each pays. What falls is the swing: at correlation 0, 10 bots cut the spread of
  outcomes from $53 to $17.
- That steadiness is the actual prize, because it can be spent: running the same total risk
  across uncorrelated bots lets each take a bigger position for the same wobble. Risk-scaled
  medians after a year: 1 bot $156, 3 uncorrelated $230, 10 uncorrelated $461 - roughly the
  sqrt(n) law. At correlation 1.0 scaling up gains nothing ($158), it just multiplies risk.
- Practical read for this repo: 3 agents on gold with the same model and different thresholds
  are highly correlated, so the gain is small. Real multiplication needs different *markets*,
  which is an argument for training more symbols rather than stacking agents on XAUUSD.
- Caveats recorded: this assumes each bot actually has an edge (multiplying no-edge bots
  multiplies losses), and correlations tend toward 1 in a crisis.

### 2026-10-01: tested a buy-low/sell-high bot at 0.1% risk (ea/meanrev_study.py)
- User felt basic manual trading beats these returns and asked to test a simple mean-reversion
  bot. Ran 36 parameter combinations on the real gold day with the true 45pt spread.
- 23 of 36 settings lost money over the full day. The best made $124 from $100 in 5.8 hours -
  but that was chosen with hindsight after seeing every result, so it means nothing.
- **Sizing finding**: 0.1% risk is not achievable at $100. 0.1% of $100 is $0.10, but the
  minimum 0.01 lot with a 200pt stop risks $2.00 - 20x the intended risk. 0.1% per trade only
  becomes real above a $2,000 balance.
- **Two of my own hypotheses were wrong, recorded honestly**: I predicted the cherry-picked
  setting would collapse out-of-sample - instead the unseen half did BETTER (26/36 settings
  profitable vs 0/36 in-sample). I then guessed the first half was trending; measuring showed
  both halves ranged (8.0% and 1.7% efficiency). The real difference was movement: the second
  half walked 34,968 points versus 15,857 in a similar range - more than twice the oscillation,
  which is precisely what a mean-reversion strategy is paid for.
- Conclusion for the user: results were dominated by how much the market moved, not by the
  settings. 5.8 hours of one day cannot establish an edge either way - months of data are needed,
  which the app's Train tab downloads.

### 2026-10-01: $5 trades on $100 - the bet-sizing study (ea/betsize_study.py)
- User asked what $5 per trade would do. That is 5% of a $100 account, so this is the Kelly
  question. Simulated 2,000 years per cell across risk levels and true win rates.
- The answer is genuinely "it depends", and on one specific unknown - the real win rate:
  - at 30% wins (just over the 28.6% break-even), 5% risk returns **$75** (a LOSS) while 2%
    returns $117. Over-betting destroys a thin edge: 2.5x Kelly here.
  - at 35% wins, 5% risk returns **$1,871** vs $435 at 2%. Roughly half-Kelly, about right.
  - at 40% wins, 5% risk returns **$46,482**. (Caveat: 40% at 1:2.5 is PF 1.67, exceptional.)
- The shape worth remembering: returns rise with bet size, peak at Kelly, then FALL while
  drawdown keeps climbing. Past the peak you take more risk for less money.
- Drawdown cost even when it works: 5% risk at a winning 35% still has a median 62% max
  drawdown - $100 spends part of the year looking like $38.
- Practical answer given: start at 1-2%, measure 50+ live trades, compute the real win rate,
  then size to half-Kelly. Bet size is a function of an edge that has not been measured yet -
  CandleSenseStart has no live trades.

### 2026-10-01: optimised the config for $5/trade on $100 (ea/optimize_config.py, EA v1.10)
- User: "find the best way - $5 per trade, $100 start, most profit per week." Treated it as an
  optimisation over reward ratio and trade frequency, since with a fixed $5 risk
  profit/week = trades x $5 x expectancy.
- **Wider targets win**: the 45pt spread is a fixed toll, so you pay the same to chase 875 points
  as 250. Expectancy per trade at 8% skill: -$0.10 at 1:1, +$0.50 at 1:2.5, +$1.10 at 1:4.
  Noted the model's limitation - it adds skill as a flat probability bonus at any R:R, which
  flatters very wide targets, so 1:3 to 1:4 is the trustworthy end.
- **Frequency multiplies whatever the expectancy is**, in both directions. At 40 trades/week:
  +$60/week at 8% skill, -$36/week at 0%. Identical configuration; only the edge differs.
- Applied to `CandleSenseStart.mq5` v1.10: RiskPercent 5, MinStopPoints 250, RewardRatio 3.5,
  daily loss limit raised to 15% (3 losses at 5% each). Header and README now carry the warning
  to run at 1-2% until 50 demo trades establish the win rate, and that 5% brings ~60% drawdowns.
- Fixed stale numbers in my own script's closing text ($640/-$240) that contradicted its computed
  output ($60/-$36) before committing.

### 2026-10-01: would launching multiple EAs on one account make more, or lose it all?
- User asked exactly that, noting the EAs would not be collaborating. Simulated it
  (`ea/multi_ea_risk_study.py`), 4,000 runs per cell, one month, with a GOOD strategy
  (30% wins at 1:3.5 = +0.35R/trade) so any failure is from stacking, not from a bad edge.
- **Uncoordinated copies on the same symbol are strictly worse**, in both directions at once:
  | EAs | risk/round | median end | wiped out |
  | 1 | 5% | $712 | 0.4% |
  | 3 | 15% | $711 | 10.3% |
  | 5 | 25% | $424 | **23.7%** |
  | 10 | 50% | $150 | **41.6%** |
  Lower median AND far higher ruin. Five "safe" 5% bets are one 25% bet.
- Four compounding reasons recorded: each EA reads the same balance and takes its own 5%
  unaware of the others; copies on one symbol agree by construction (one position at 5x size,
  not five positions); per-EA daily loss limits do not compose (5 EAs at 15% each permits a 75%
  fall); and at $100 margin runs out first anyway (0.02 lots of gold needs ~$83 at 1:100).
- **A shared risk budget fixes the ruin column**: the same 5 EAs sharing one 5% cap drop from
  23.7% to 16% wiped out, and 5 uncorrelated EAs sharing a budget give the smoothest ride of
  all - 16% drawdown vs 53% for a single EA.
- Fixed my own simulation before trusting it: the first version compounded with no lot cap and
  produced $1e19 balances. Added a broker-style MAXLOT and a one-month horizon.

### 2026-10-01: replayed CandleSenseStart on 6 months of real gold; v1.11 (no warm-up, skip oversize)
- User asked me to act as the EA on gold data, and that it start trading as soon as it's launched.
- Data: `data/XAUUSD_M1_history.parquet` turned out to be the sandbox's synthetic set (it "falls"
  from $2,637 to $1,245 over 2021-24), and huggingface.co is blocked here. GitHub is reachable, so
  cloned getdata-finance/xauusd-15m-ohlcv-metals-historical-data (MIT): 11,989 real M15 candles,
  2026-03-26 to 2026-09-25. Saved as `ea/XAUUSD_15m.csv`.
- `ea/start_replay.py` mirrors the EA rule for rule (H1 EMA50/200 from closed hours, M15 EMA20
  pullback, ATR14 stop min 250pts, 1:3.5, BE + ATR trail at 1R, sessions, daily/streak/floor
  limits, 45pt spread). Stop assumed before target when a candle touches both.
- **Found a real bug**: 2026 gold's M15 ATR makes the stop 1,100-2,100 points, so 0.01 lots risks
  $11-21 (11-21% of $100). v1.10 only warned and traded anyway: $100 -> $43 in 3 weeks, halted at
  the $50 floor. v1.11 skips any trade the minimum lot cannot size to within 1.5x of RiskPercent:
  on $100 it took 34 of 424 setups, $100 -> $99.11 (-1%), 41% max drawdown.
- **Honest strategy result**: at $1,000 / 2% (no min-lot distortion) the rules made +11% in
  Mar-Jun and -21% in Jun-Sep. Break-even/trailing were not the cause (all exit variants similar).
  No dependable edge on this data; did not tune further on the same 6 months (would overfit).
- **No warm-up**: MT5 loads history at attach, so indicators are ready immediately. TryEnter now
  returns false only while indicator data is still loading, and OnTick retries on every tick
  until it can evaluate - previously a not-ready first tick burned the whole M15 bar. The first
  tick after launch checks for a setup. Status line now shows the real $ risked.

### 2026-10-01: SmallAccountPro.mq5 from the user's own spec, replayed on real gold
- User wrote a detailed spec (EMA21/50/200 + RSI + Bollinger pullback, $5 minimum risk, 1.8 R:R,
  ATR stop clamped 100-500 pts, 80%-of-free-margin guard, $ break-even/trail, $15 daily breaker,
  60 s start-up countdown + immediate initial trade, Comment() HUD). Built it as
  `ea/SmallAccountPro.mq5`, native MQL5 only. Deviations, all flagged to the user: sizing uses
  OrderCalcProfit with tick value only as fallback (tick value was ~10x off on gold before); lots
  round UP so the stop loses at least $5; initial trade waits until EMA21/50 and RSI slope agree.
  Not compiled here (no MetaEditor) - written to avoid the usual warnings (explicit casts,
  checked returns, no MQL4 calls).
- `ea/sap_replay.py` mirrors it on the 6 months of real M15 gold (EA targets M1/M5, so this is an
  approximation). The rules were written by the user before seeing this data, so it is a fair
  out-of-sample test:
  - $1,000 / 1:100 (fixed $5 risk): 1,320 trades, 50% win rate, +$816 (+82%), 7% max drawdown,
    17 of 26 weeks positive, average +$31/week vs the $100 goal.
  - Holds in both halves (+38% Mar-Jun, +45% Jun-Sep) and at a 70-point spread (+48%).
  - $100 / 1:100: an early losing run took it to ~$46, where 0.01 lots of gold ($46 margin) no
    longer fits 80% of free margin, so it locked itself out after 5 weeks: -54%.
  - $100 / 1:500: survived the same run (59% drawdown) and finished at $916.
- First strategy today with a consistent result on both halves of real data. Caveats: M15 not
  M1/M5, intrabar management approximated, no live/demo trades yet.

### 2026-10-01: SmallAccountPro on M1 / M5 - tested, M15 only (v1.01)
- User asked if it could run on M1. It already reads the chart's timeframe, so the question was
  whether it still works there. Cloned the same publisher's real 1m (179,663 rows) and 5m data for
  the same six months and reran `ea/sap_replay.py`:
  - M1, $1,000/1:100: 55% win rate yet -95% in 12 weeks. M5: -12%. M15: +82%.
  - Cause: M1 ATR is tiny, so the stop sits at the 100-point floor and the 45-point spread is ~45%
    of it; the $2.50 break-even and $1.50 trail close winners for cents while losses are a full $5.
  - Raising the M1 minimum stop to 250 or 400 points still lost in both halves. Not M1-viable.
- v1.01 prints a warning at start-up and shows one on the HUD when attached below M15.

- Timeframe sweep (same six months, $1,000 / 1:100, fixed $5 risk; full / 1st half / 2nd half):
  M1 -95% (lost in both halves) | M5 -12% (+35% then -46%) | **M15 +82% (+38% / +43%, 7% DD)** |
  M30 +30% (+11% / +19%, 12% DD) | H1 +7% (-2% / +8%). M15 is best and the most consistent;
  M30 is the only other timeframe positive in both halves.

- Compounding (user asked whether +$31/week grows with the balance - it doesn't; the EA risks a
  fixed $5). Replay on M15, $1,000/1:100: fixed $5 +82% (7% DD) | 0.5% of balance +163% (9% DD) |
  1% of balance +407% (16% DD). $100/1:500 at 5% of balance reached $77k but with a 76% drawdown
  and no allowance for slippage at size - treated as an upper bound, not a forecast.
  v1.02 adds `InpRiskPercentOfBalance` (default 0 = fixed $5, the tested behaviour); when > 0 the
  risk is the larger of the $ minimum and that % of balance. HUD shows which mode is on.

- User's risk ladder ($5 per $100 of balance up to $25 at $500-599, then a flat $50 from $600)
  added as v1.03 (`InpUseRiskLadder`, default on; step/amount/steps/top are inputs; overrides the %
  setting). Replay M15, $100 start, 1:500: $6,013 (+5,913%) vs $916 with fixed $5, worst drawdown
  59% either way; both halves positive. At 1:100 the account still locks itself out in week 2
  (an early -50% week leaves too little margin for 0.01 lots), so the ladder needs 1:500 at $100.
  Weekly path: weeks 1-7 at $5 risk swing between $55 and $222; the $10-$25 rungs take it to $1,088
  by week 11; from week 12 it sits at the $50 cap and grows linearly (~$4,000 over 15 weeks), with
  7 losing weeks out of 26.

- v1.04: user extended the ladder - from $1,500, +$50 risk per $1,000 gained ($2,500 -> $100,
  $3,500 -> $150 ...; settings InpLadderBigFrom/Step/Add). Replay M15, $100/1:500: $24,031 vs
  $6,013, same 59% worst drawdown, but losing weeks become large in dollars (weeks 20-22: -$6,900;
  weeks 25-26: -$15,228, $39,259 peak to $24,031). Risk follows the balance down as well as up.

- Leverage sweep for the v1.04 ladder (user asked if their account must be 1:500): at $100 the
  EA needs 1:200 or more (1:100 locks out, 1:50/1:20 can't open 0.01 lots at the 80% margin
  guard); 1:200 and 1:500 give identical results. From $300, 1:50 already works. Very large end
  balances at $300-$500 starts ($86k-$306k) are flagged to the user as backtest artefacts: no
  slippage at multi-lot size, no overnight swap, constant spread, intrabar order approximated.
  US note given: CFTC caps retail FX at 1:50 majors and Dodd-Frank restricts leveraged OTC spot
  gold for US residents; 1:500 is offshore-only and gives up CFTC/NFA protection.

- US routes (user is in the US). Researched: only FOREX.com and Trading.com offer MT5 to US
  residents, CFTC caps retail FX at 1:50, and leveraged OTC spot gold is generally not offered to
  US retail. Tested the EA on EURUSD (same publisher's real M15 data, 1:50, 1.3-pip spread): lost
  in both halves (-31% at $1,000 fixed $5; -57% at a 2-pip spread; ladder from $100: -73%). So the
  US MT5 forex route does not work for this strategy.
  The legal US gold route is CME 1-Ounce Gold futures (1OZ): $1 per $1 move, the same as 0.01 lots
  of XAUUSD, ~$243-390 overnight margin (lower intraday at some brokers). Not available on MT5, so
  the EA would need porting to a futures platform. Offshore 1:500 not recommended (no CFTC/NFA
  protection).

### 2026-10-01: finding a CFTC/NFA-regulated US route for SmallAccountPro ($400, demo first)
- User is in the US, wants CFTC/NFA regulation, any instrument, up to $400.
- `ea/sap_replay.py` generalised to any symbol (contract maths for USD-quoted, USD-based and cross
  pairs, typical US spreads, optional `ladder` arg). Gold result unchanged ($1,816.42) after the
  rewrite. Tested all 8 majors/crosses available at US MT5 brokers (FOREX.com, Trading.com), $400,
  1:50, ladder: **every pair lost** (EURUSD -1%, others -82% to -96%; most lost in both halves).
  The edge is gold-specific.
- US gold = CME 1-Ounce Gold futures (1OZ, $1 per $1 move = 0.01 lots). First futures test lost:
  at the EA's 100-500pt stops the edge is ~$0.60/trade and costs must stay under ~$0.75 round
  trip; NinjaTrader all-in is ~$0.80-1.06 per side and the tick sets a 25pt minimum spread.
  Closing before CME's daily break did not hurt (+86% vs +82% with no costs).
- Commission is per contract, so wider stops dilute it. `ea/futures_replay.py` (new): 1OZ with
  $2.00 round trip, 25pt spread, $60 day margin, flat by 20:45 UTC, ladder. **M30, 500-2500pt
  stops: $400 -> $2,541 (+535%), 48% max DD, +253% / +297% by half**; 800-3000 and 1200-4000 also
  positive in both halves. M15 mixed. Saved `ea/XAUUSD_30m.csv` (MIT, getdata-finance).
  Caveat: 8 variants searched on the same 6 months; M30 consistent across all wide ranges.
- Broker: NinjaTrader (free platform with sim + NinjaScript automation; Clearing LLC is a
  CFTC-registered FCM, NFA ID 0309379) - but its NFA record shows "Pending Withdrawal", so the user
  was told to check NFA BASIC before funding. Futures need a NinjaScript port of the strategy.

### 2026-10-01: SmallAccountPro ported to NinjaTrader 8 (1OZ futures)
- User chose NinjaTrader. New `ninjatrader/SmallAccountProNT.cs` (NinjaScript strategy) +
  `ninjatrader/README.md` (install, Strategy Analyzer -> Sim101 -> live, settings, NFA check).
- Same rules as `ea/futures_replay.py`: 30-min chart, EMA21/50/200 + BB(20,2) + RSI(14) pullback,
  stop 1.5xATR clamped $5-$25, target 1.8x, ladder -> contracts (rounded up, 80% day-margin cap at
  $60/contract), BE +$2.50 -> +$0.50, trail $1.50 from +$4, -$15 daily limit, no entries after
  15:30 NY, flat 16:30 NY (+ exit-on-session-close 30 min early). ATR as an SMA of true range (like
  MT5 iATR); balance = Starting balance input + strategy's closed profit (Sim101 holds $100k).
- Found while porting: the replay never checked the entry candle's own high/low. With it checked:
  $400 -> $2,346 (+486%, DD 45%) instead of +535% - still holds. NinjaTrader checks that candle.
- Not compiled here (no NinjaTrader/C# compiler in the container): the user's F5 is the first compile.

### 2026-10-01: NinjaTrader install/test instructions with links
- `ninjatrader/README.md`: sign-up (free 2-week live-data trial, Sim101), Desktop download, OneDrive
  path fix, commission templates, Strategy Analyzer settings (1OZ, 30 min, commission, slippage 1,
  $400), Sim101 run, going live. Links checked against NinjaTrader's support pages (Aug 2026).

### 2026-10-01: NinjaTrader backtest exposes a replay flaw - SmallAccountPro has no edge
- SmallAccountProNT compiles on the user's PC. Strategy Analyzer, 1OZ DEC26, 30 min, Jan-Sep 2026,
  $400: 126 trades, 47.6% won, -$328.75 (commission still $0 - template had no 1OZ rate).
- Cause of the gap: `ea/sap_replay.py` filled stops at the stop price even when the trail/break-even,
  set from the bar's high/low, was already past the price - an impossible fill. Fixed (fills at the
  open when the bar opens past the stop). With real fills the futures setup is $400 -> $75 (-81%),
  and the MT5 M15 settings lose too. The earlier +535% / +486% / +82% results were this artifact.
- Told the user not to fund it. NinjaTrader's numbers agree with the fixed replay.

### 2026-10-01: honest re-search for a gold edge (22 years, real fills)
- Got 2004-2025 gold 15m (BaseMax/XAUUSD-LSTM, MIT; broker time = NY+7h) + 2026 data. New
  `ea/research/` (honest-fill engine + studies, README with the table). Data file gitignored.
- Opening-range breakouts: all 54 lose. Trend on 1h: lose. Daily Donchian trend: all 18 versions
  win in both halves (classic trend edge). But today's daily stop is ~$190 per 1OZ contract (47% of
  $400). Unlevered (fund shares): ~6%/yr, 20% worst drop. RSI2 dip-buy: negligible.
- Conclusion for the user: no safe edge at $400 on short timeframes; the real edge needs ~$2-4k on
  1OZ, or runs unlevered at single-digit %/yr. Asked which way to go.

### 2026-10-01: research - automated ways toward $100/week (Solana trenching, Kalshi, prop firms)
- `ea/research/money_paths.md`: the app already has the Solana trenching bot + tweet radar (`sol/`, Chat B,
  paper by default). CoinGecko/Dune: most Pump.fun wallets lost monthly until late 2025; Apr 2026 73%
  profitable but 65% made only $1-500/month, 5.4% > $1k. Kalshi: CFTC-regulated, API bots allowed.
  Topstep: bots allowed, 16.8% of Combines pass, 33% of funded get paid. Safe yields ~4-6%/yr.
- Told the user $100/week from $400 isn't available safely; offered: measure the Solana bot honestly in
  paper, prototype a Kalshi bot in paper, or the gold trend bot once the account is ~$2-4k.

### 2026-10-01: $250 options on Solana - Axiom, spot trend rules
- Axiom's Terms of Use ban bots/automation (third-party "Axiom bot" SDKs/sites want wallet keys).
- Crypto data: exchange APIs are blocked by the proxy, so Binance daily klines came through Firecrawl
  (SOL 2020-08.., BTC/ETH 2017-08.. to 2026-09-26). `ea/research/crypto/` (ctest.py + README).
- Spot, unlevered, 0.3%/swap: SMA50 filter beat holding on SOL/BTC/ETH over the full period and cut the
  worst drop from -96% to -70% on SOL; second halves much weaker. $250 -> ~$5/week at 100%/yr.

<!-- Chat A: add new entries above this line -->

## Chat B log (UI & Polish)

### 2026-09-24: Chat numbers
- The user named the chats: this chat is chat 2 = Chat B (UI & Polish); the other chat is chat 1 = Chat A (Backend &
  Skills). The two-chat setup entry in Chat A's log above was written by this chat before the names were set.
- `TWO_CHATS.md` headings now carry both names.

### 2026-09-24: Design review (screenshots of every page)
- Request: pictures of all pages and design recommendations; design work happens in this chat (chat 2).
- Ran the app in the cloud sandbox from a copy of the repo (so no `data/` files landed in the working tree), with a
  fake `MetaTrader5` module: demo account, two positions (one bot, one manual), 3,000 random-walk XAUUSD M1 candles.
  Seeded 18 bot trades and a short Hermes chat, then shot all six tabs with headless Chromium at the real window size
  (1440x900; Agent, Train and Settings at full scroll height). Google Fonts were fetched through the proxy with TLS
  verification on, so IBM Plex rendered. No repo code changed.
- Verdict against the anti-vibe checklist: 2 of 9 tells (every panel is the same rounded box; middle-dot meta strings
  such as "0.02 lots · demo · conf 71%"). No purple, real typefaces, specific copy: a solid base.
- Bugs seen: Train step 2 text crushed into a thin column; the Market bot card title wraps ("Bot / trade") and its two
  trades run together; the Agent stat tiles leave one orphan tile; Settings uses native blue checkboxes, only ~60% of
  the width, and Save only at the very bottom; Quiz highlights Continue when no quiz exists; "Replay history" sits
  among the symbol chips; gold means brand, primary action, selected, bot and buy all at once.
- Recommendations given: hierarchy instead of identical boxes; colour roles (gold = brand and primary action, a
  colour of its own for the bot, arrows for buy/sell); a trader-first top strip (RAM/VRAM moved out); empty states with
  a next step; glass only where content scrolls under it; one motion moment (a trade opening); domain features
  (session bands and prior-day levels on the chart, stage ladder, daily P/L calendar, setup leaderboard); Settings with
  section nav and a sticky Save; Agent tab re-layout.
- Next: the user picks what to change first.

### 2026-09-24: Chart auto-align, lazy history, P/L calendar, Train dropdowns, animations, empty states
- Requests: chart auto-align when it gets messed up; Train step text into dropdowns; Weak spots shows only the copy
  button; the daily P/L calendar; animations for everything, optimized; "do whatever needs optimizing" for empty panels;
  load chart history only when scrolling far enough and unload what was loaded before; images of the result.
- Chart: Auto button (on by default, saved per PC). After a zoom/drag the chart straightens itself 10 s later (a thin
  bar on the button drains meanwhile): price axis autoscaled, default candle width, newest candle at the right.
  Double-click realigns now; Auto off keeps the view. Realigns on symbol change, tab return and window resize.
- Lazy history: 300 candles at start; reaching the left edge loads 500 older (`GET /api/bars?before=`, a 3-line backend
  addition flagged to Chat A); the window is capped at 1,800 and the far side is unloaded (newest when going back,
  oldest when coming forward); auto-align brings the live 300 back. Live polls fetch 3 candles instead of 300.
- Agent: daily P/L calendar in the Bot trades panel (UTC close days, green/red heat by size, month nav, summary,
  tooltip, click a day to filter the table), stats in 4 columns (no orphan tile).
- Train: explanations behind small dropdowns (animated), step 2 no longer crushed, Output card until something runs.
- Quiz: Weak spots is only the copy button (fetches the newest report, builds one if needed); the main button follows
  the state; empty cards for the board, latest mistake and points chart; build note restyled (handoff).
- Hermes (Chat A handoffs): pill from `local`/`device`, next-step line, Set up button, download bar, 2 s polling while
  busy, sleep on leaving the tab, memory file name, CPU-only switch in Settings.
- Motion: tab panels stagger in, sliding rail highlight, numbers glide and flash, new rows/positions/messages slide in,
  switches for checkboxes, one gold glow when the bot enters. Only transform/opacity for anything continuous; markup
  writes skipped when unchanged; off with the OS setting or Settings > Display.
- Tested in the sandbox with a fake MT5 (populated and fresh install): every interaction driven in headless Chromium,
  0 console errors, 0 long tasks over 50 ms in 8 s of running. 12 images sent to the user.
- Handed to Chat A (user request): make the model learn from each mistake.

### 2026-09-24: Three design proposals (mockups only, not built)
- Sent as images for the user to pick from; built in the sandbox by injecting CSS/markup into the running app:
  1. Market: trader-first top bar (account chip with server, equity, today, floating, open count, session clock for
     London/New York/Asia, agent status; RAM/VRAM behind a small button); the bot gets its own colour (baby blue) on
     badges, the bot card edge and its entry lines; ▲/▼ for buy/sell; bot card as a label/value grid; Replay as its own
     button; chart with the Asia range box, London/New York open lines and prior-day high/low.
  2. Agent: one control bar (stage ladder drawn as a path with locks on the real-money stages, Start/Stop, Live log
     drawer button, both sliders); Paper gate and the trade plan side by side; "Which setups make money" leaderboard
     (net P/L per setup, trades, win %) next to "What the bot has learned"; Bot trades unchanged below.
  3. Settings: side menu (Trading, Bot money rules, Quiz school, Hermes, Display), sections as cards in three
     columns, units inside the inputs, help lines under switches, quiz settings in their own section, and a save bar
     that stays visible and names the unsaved change.
- Next: the user picks which to build.

### 2026-09-24: The 3 approved designs, Manual tab UI, more handoffs (0f1149b)
- The user approved all three proposals; built for real (not mockups):
  - Market: top bar = account chip (DEMO/REAL, server, login), equity, "Bot today" for the current stage, floating,
    open positions, session clock (London 10:00–18:30, New York 16:30–23:00, Asia 01:00–09:00 in broker server
    time = New York time + 7 h, as agent/pro.py uses), agent status; RAM/VRAM/free margin in a popover. Bot colour
    blue (`--bot`), ▲/▼ for direction, bot card as a label/value grid, Replay button. Chart overlay layer: Asia range
    box, London and New York open lines, prior-day high/low price lines (fetched once per symbol per server day),
    redrawn at most once a frame on scroll/zoom/data; Settings > Display switch.
  - Agent: control bar with the stage ladder as a path (progress on the next edge, locks on real money), gate and plan
    side by side (plan in 4 columns), "Which setups make money" leaderboard (follows the mode filter), Live log drawer.
  - Settings: section menu with scroll-spy and unsaved dots, card sections, units inside inputs, help lines, Quiz
    section, sticky save bar naming the change (with a retrain hint for exit rules), Discard.
- New Manual tab (the user asked for everything the MT5 mobile app does): order ticket (one-click switch, lots
  stepper/presets, market/limit/stop, SL/TP, points at risk, size from stop, slippage, expiry), quotes list, positions
  with Close / ½ / SL-TP / BE, bulk close (all, profitable, losing, buys, sells; everyone's/mine/bot/Hermes; two
  clicks), pending orders, today's history. Watching prices and closing work now (existing endpoints); placing,
  editing and pending orders wait for `/api/manual/*` - full spec handed to Chat A in TWO_CHATS.md.
- Chat A handoffs done: Quiz size without a maximum plus All, question-bank line with half-year bars, quiz settings
  (`quiz_workers` wording, `quiz_bank_auto`); Hermes `web_sites` list in Settings.
- Tested in the sandbox (fake MT5, populated and fresh): every new control driven in headless Chromium, 0 errors,
  earlier regression suite still green, 0 long tasks. 7 images sent to the user.

### 2026-09-24: Manual tab round 2, lessons UI, "Always on" rule
- The user asked for the chart with buy and sell under it, TP always 160 above and SL 80 below, everything from the
  right column moved under the chart, and a strip above the chart with all open trades plus Close all / Close
  profitable / Close negative.
- Manual tab now: left column = order ticket + quotes; right = open-trades strip (summary, owner filter, the three
  bulk buttons with two-click confirm, one chip per trade with a two-click quick close), the chart (its own
  lightweight-charts instance: 300 bars, then live updates every second; entry/SL/TP lines for every position; hovering
  Buy or Sell previews the TP/SL you would get), the SELL | spread | BUY bar under it, then Positions, Pending orders
  and History.
- TP/SL are set in MT5 points: 160 above / 80 below for a buy, flipped for a sell (1.60 / 0.80 on gold). Editable in
  the ticket and remembered; a small table shows the exact entry/TP/SL for both sides. Orders send the prices plus
  `sl_points`/`tp_points`; asked Chat A to re-anchor them to the real fill price so slippage can't move them.
- Chat A handoff done: "Latest lesson" box and caution chips in "What the bot has learned"; "your bot's trade" badge
  on quiz questions made from the bot's own losses.
- TWO_CHATS.md: new "Always on" section from the user (both chats always open; any message = sync, do open handoffs,
  then the request; write specs into the other chat's list instead of asking the user to relay).
- Tested against Chat A's real `/api/manual/*` with a fake MT5: levels right for both sides, hover preview lines,
  two-click buy filled, chip arming, fallback quote, 0 console errors. Screenshots sent to the user.

### 2026-09-24: 11 new features (UI), tested on Chat A's backend
- The user picked 1, 3, 4, 5, 6, 7, 8, 9, 10, 12 and 13 from my list. I wrote the backend spec into Chat A's list
  first (ecc1e10); Chat A built it (aaff90b) while I built the UI.
- 1 Real-account guard: red banner on the Manual tab, type REAL once per app session before the first real order (also
  before one-click can go on), hold × for 1 s to quick-close a trade on real money.
- 3 Connection: a pill in the chart head (live / quiet / no new price / MT5 offline / market closed); Buy and Sell grey
  out and refuse while it's red, amber or closed.
- 4 Drag SL/TP lines on the Manual chart: the label shows points and money while you drag; a level on the wrong side
  snaps back; letting go moves it in MT5.
- 5 Keyboard shortcuts (off by default, Settings > Manual trading): B, S, Shift+X, Esc, +/-.
- 6 Break-even and trailing stop: in the ticket for the next order, per trade in Positions (Auto), defaults in Settings.
- 7 Alerts: a card (bottom-left, 8 s) and a sound when a take profit or stop loss is hit, for every owner; the window
  title says it while the app is in the background.
- 8, 9, 10 New Review tab: You vs the bot (scorecard, running P/L chart, best hours), Trade replay (list + chart with
  entry/SL/TP/exit; History rows on Manual and Bot trades rows on Agent open it; arrow keys step), Weekly summary
  (Hermes or rule-based, week picker, Write it again).
- 12 Settings > Backup: back up now, restore a backup, restore from a file (shows what would change first), copy as
  text without the Hermes key.
- 13 Setup pill in the top bar and a checklist drawer that opens once on a fresh install, with Fix buttons.
- Fixed on the way: Manual History crashed on real rows (time is a number); Save in the per-trade editors did nothing
  (it looked for the ticket on the editor row).
- Tested in the sandbox (fake MT5) three ways: routes missing, mocked, and Chat A's real routes. Every control driven
  in headless Chromium, 0 errors. Couldn't do here: Windows pop-up notifications outside the app window (handed to
  Chat A) and a run on the real MT5 terminal.

### 2026-09-24: Hermes Agent in the Hermes tab (Chat A handoff)
- Header tag says who answers next ("Hermes Agent" in gold, or "Local model"); the pill shows Hermes Agent ready /
  starting / not running; `agent_step` shows under the header while it isn't ready; Set up also shows for a stopped
  agent; status polls every 2 s while it starts.
- Each reply carries a small tag naming who wrote it; while waiting, the bubble counts the seconds and says agent
  tasks can take a few minutes.
- Settings → Hermes: start Hermes Agent with the app, the command, the WSL distro.
- Tested with mocked statuses and a 23 s mocked reply: 0 errors.

### 2026-09-24: Trade-finish bell
- The user asked for a bell like the one the Neverlose cheat plays as its kill sound for profitable closes, and the
  same sound one octave down for a stop loss. The app can't ship that sound file (it isn't ours), so it synthesises a
  short, bright bell (struck-bar partials plus a tiny strike click); the loss bell is the same sound at half speed
  (one octave down, twice as long). Dropping a file in `app/static/sounds/` as `profit.wav` / `profit.mp3` replaces
  it, and a loss plays that file at half speed.
- Rings for: TP/SL alerts from `/api/events`, other closes from the feed (bell only), and the bot's paper/replay closes
  (demo/real ring from the feed, so nothing rings twice). Settings > Manual trading has "Play profit bell" /
  "Play loss bell". Rendered both to WAV and sent them to the user.
- Bells queue 0.45 s apart, so two trades closing together ring one after the other. Recorded a 2-minute walkthrough
  video of every new feature (headless Chromium, captions, bells mixed in at the alert) and sent it with 11 stills.

### 2026-09-24: Deeper loss bell
- The user found the loss bell too high. It's now two octaves under the profit bell (E4, about 330 Hz, was E5), rings
  about twice as long, has its tinny top rolled off (low-pass at 1.8 kHz) and is a little louder so it doesn't sound
  weaker. A custom sound file plays at quarter speed for a loss. Re-rendered the WAV for the user.

### 2026-09-24: Keys page, Sounds page, custom notifications, speed pass
- The user asked for a separate keybind page, custom sounds with pitch and every other sound setting, notifications at
  the top right (custom, several at once, newest below, fading after 1.2 s, animations kept), and for everything to be
  as optimised as it can be. Backend asks went into Chat A's list the moment they came up (settings keys + sound files,
  a `sync_bot_ledger` throttle, `desktop_alerts` off by default); Chat A built the first in c071ee7.
- Keys page (new rail tab): every shortcut listed by group (Trading on the Manual tab, off by default; Moving around, on)
  with a scope tag; click a key, press the new one (Ctrl/Alt/Shift allowed), Esc cancels, Backspace clears; a key
  already used where it would clash moves over and the old action shows "no key" with Undo; copy/paste/reload and
  similar keys are refused; search; reset one or all; a keyboard map lights the keys in use (click one to jump to it).
  New actions: tabs 1-0, realign chart (R), live log (L), write to Hermes (/), mute (M), next/previous symbol ([ ]),
  order type, close profitable/negative. One dispatcher runs them; never while typing or with a dialog open. Saved in
  `data/settings.json` (`keybinds`), so backups carry them.
- Sounds page (new rail tab): 10 events (profit, loss, bot opened, order filled, refused, stop moved, stage up/down,
  feed lost, Hermes replied), each with on/off, sound, pitch (±24 semitones), volume, tone and length, a live waveform
  of exactly what will play, play and reset; master volume, mute everything, the gap between back-to-back sounds, quiet
  hours; 10 built-in sounds made by the app; your own files (drop or choose; WAV/MP3/OGG/M4A/FLAC up to 5 MB, kept in
  `data/sounds/` by the server) with rename, delete and "Use for". Every change saves and plays once. `M` or the Muted
  pill in the top bar toggles mute. The old `alert_sound` switch left Settings (false starts the page muted once).
- Notifications: one custom stack at the top right for every message (orders, closes, TP/SL, bot trades, errors):
  several at once, each new one below the others, 1.2 s each (changeable), a thin timer line, hover keeps one open,
  click closes, slide-in, fade-out and the rest glide up. When the app isn't in front the same cards pop up at the top
  right of the screen in a small always-on-top window that never takes focus (`app/main.py` + `app/static/notify.html`).
  Settings on the Sounds page, including Chat A's `desktop_alerts` (Windows' own pop-up, bottom right).
- Speed: while the window is hidden only bot trades, account, positions and events keep polling (everything else waits
  and catches up on return); the Market and Manual tabs share one positions request; WebView2 no longer slows timers
  while minimised, so alerts and sounds stay on time; the window keeps its storage between restarts (pywebview's
  private mode wiped it every time).
- Fixed on the way: backup times showed as raw numbers.
- Tested in the sandbox against Chat A's real routes: rebinding, clashes and undo, reserved keys, keys driving the app,
  mute pill, sound rows and waveforms, pitch saved to the server, upload, use-for, delete, notification stacking and
  timing, the on-screen pop-up page, hidden-window polling, earlier suites again: 0 errors. The pop-up window itself
  needs Windows (pywebview); it can't run in the cloud.

### 2026-09-24: Screen pop-ups over full-screen apps and while minimised
- The user wants notifications to show while the app is minimised and another app is full screen.
- `app/main.py`: the pop-up window is now a Win32 tool window (no taskbar button, not in Alt+Tab, never activated,
  clicks don't take focus) raised to the top of the always-on-top band every time it shows, so it sits above
  full-screen apps (borderless/windowed full screen, browsers, video players and most modern games; true exclusive
  full-screen games let no window draw over them, the sound still plays). It's placed at the top right of the chosen
  screen's work area in real pixels (DPI-aware). TP/SL/close/stop-move alerts are read from `/api/events` by a Python
  thread every 0.7 s and shown whenever the app isn't in front, so they don't depend on the minimised page; the page
  sends the rest (bot paper trades, orders, Hermes) and no longer sends feed alerts twice. Notifications sent while the
  pop-up page loads wait for it (`ready()`). Settings reach Python through `configure()` (kept in
  `data/popups.json`). Chromium's own window-occlusion and one-wake-up-a-minute modes are also switched off.
- Sounds page > Notifications: "Screen pop-ups appear on" (every screen listed, main first) and "Show one on the
  screen" (desktop app only).
- Cards are a touch more opaque so text behind them can't show through.
- Tested: the bridge and the feed watcher against a stub feed (pending until ready, TP/SL/trail shown, opens skipped,
  quiet while the app is in front), the page with a stand-in bridge (settings, screen list, no double sends), ctypes
  argument types. The Win32 part needs Windows to run. Recorded an animation of the notifications popping up (in the
  app, and the pop-up over a stand-in full-screen app) as MP4 and a close-up GIF for the user.

### 2026-09-24: Notifications stay 2 s
- The user asked for 2 seconds instead of 1.2. New default everywhere (app stack, screen pop-up page, the pop-up's
  Python side); anyone still on the old 1.2 default moves to 2 by itself, a different chosen value is kept. The slider
  on the Sounds page still changes it. Tested: a card is still there at 1.7 s and gone by 2.4 s, in the app and the
  pop-up.

### 2026-09-24: Chat A handoffs: news pause, Manual spread limit, quiz second opinion, Telegram alerts
- News (`/api/news`): a chip in the top bar ("News in 12 min: USD CPI", amber inside the pause window, red "Bot paused
  for news" while paused; the next releases in its tooltip; click opens the setting), a line on the Agent tab (why it's
  paused, or when the next pause starts), and a Settings > News pause section (switch, minutes before/after,
  currencies, High/Medium/Low, the next six releases in your time). Countdown every 20 s, fetch every minute.
- Manual spread limit: the spread on the trade bar turns red over your limit (tooltip says the limit); a refused
  market order arms that button for 6 s: one more click sends it with `ignore_spread`. Setting in Settings > Manual
  trading.
- Quiz second opinion (`/api/stats/quiz`): a Review panel with agreed / disagreed / no opinion (trades, won, net, per
  trade, profit factor) and the verdict, following the Review period and mode; the verdict also sits under the quiz
  filter switch in Settings.
- Telegram: Settings > Phone alerts (switch, token as a password field, three steps, Find my chat, Send a test,
  which alerts); the token is saved first when you press a button; status line with errors.
- The settings form now handles checkbox groups as lists (and counts only the box you changed in the save bar).
- Tested against Chat A's routes in the sandbox (news and Telegram replies mocked: no internet or bot token here),
  0 unexpected errors.

### 2026-09-24: Chat A handoffs: 0.9 s fade, backtest card, watchdog alerts, trade notes, full data backup
- Notifications fade away over 0.9 s (the user's ask via Chat A), in the app and the screen pop-up. Two real causes of
  the "instant" exit: the fade was 0.3 s, and each card's timer line ended at the same moment the fade began, so its
  "animation ended" signal removed the card at once; now only the card's own fade counts. With reduced motion on
  (Windows or the app's switch) the cards still fade over 0.9 s, just without the slide (the catch-all reduced-motion
  rule gets an exception). Measured: fade from 2.1 s to about 2.9 s in all three modes.
- Agent tab: "Backtest before going live" card (Run / Stop, progress with the bar time and trades so far, the verdict,
  ten figures, the Paper gate lines with ticks, a bar per month, the log's last lines); costs in Settings > Bot money
  rules. A watchdog line (gave up / stuck / MT5 down / restarts in the last hour).
- Watchdog events (agent restarted / stopped / stuck, MT5 down / back) pop up (red for the bad ones, always shown),
  also on screen from Python; a new sound event "Bot crashed or looks stuck"; Telegram gets its "watchdog" box.
- Trade notes: "Why this trade?" and tags on the order ticket (sent with the order, cleared after), a note mark and a
  Note editor on each position, a Note column in History, "Your note" in Review's trade replay.
- Settings > Backup > Everything else: daily switch, how many to keep, folder, "Back up everything now", the list.
- Agent and Settings now load their server data from the tab switch itself, so keyboard navigation gets it too.
- Chat A's test suite: 26 passed before pushing. Browser-tested in the sandbox (backtest report and watchdog events
  mocked: no model or history there; notes and the full backup against the real routes), 0 errors.

### 2026-09-25: dots on the charts, Manual without confirms, the bot's "why", trading hours
- Fixed: the text under Start agent read one word per line. The new notification cards had taken the `.note` class
  that small status texts already used; the cards are `.ntf` now.
- Manual tab acts on the first click (user's request): Buy/Sell, bulk close (with a total-P/L notification), chip ×,
  Cancel all. The One-click switch, the spread "send anyway" and the Esc "cancel" key are gone. Real accounts still
  ask to type REAL once per session (also before a close).
- Dots instead of lines on the Market, Manual and Review charts: yellow entry, green TP, red SL, grey other close.
  Open trades show all three on the entry candle; closed ones show entry + exit. Hover a dot for owner, side, lots,
  entry, SL, TP, P/L. On Manual, drag a red/green dot to move the SL/TP (the axis holds still; the tip shows points
  and money). Hovering Buy/Sell shows faded preview dots.
- Bot card: "Needs 7% to enter" (practice adds "its best 10% start at 12%"), a "Last hour" line with the top skip in
  amber. Slider hint while the agent runs. Kill is "Hold to flatten & reset agent" and clears the card at once.
- Settings > Trading: trading hours (server time). Settings > About: version, update message and notes (also the
  logo's tooltip). Quiz: trap rows greyed and left out of Work on these. Events retry every 30 s after a 404.
- Tests: 43 passed. Browser-tested in the sandbox (bot trades, history and kill mocked), 0 page errors.

### 2026-09-25: the Bot tab (Co-pilot / Full Auto), on Chat A's backend
- New **Bot** tab, first in the sidebar and the one the app opens on (key: the ` key left of 1). One full-screen card,
  no scrolling at 1280x720 and 1440x900:
  - Header: symbol switcher (trained symbols only; the others say "train it first") with the live price, a clock you
    click to pick the time zone (every time on the tab follows it), the points badge, the Full Auto / Co-pilot switch
    and three heartbeat dots (Broker, Hermes AI, Data Feed).
  - The hero sentence (what the bot is doing right now), four confluence pills in their state colours, a "Last hour"
    bar of what it did on each of the last 60 candles, the AI Confidence half-ring gauge and the active position with
    its progress to take profit. No stop loss anywhere on the tab.
  - Co-pilot proposals sit on top with a countdown, Approve & Execute / Skip Setup, the "Execute when the timer runs
    out" switch and a 15/30/60/120 s timer; the outcome flashes for 4 s. A new sound + notification "Co-pilot
    proposal" (also on screen when the app is behind).
  - Start / Stop / Hold to flatten & reset on the card; Hold is on the Agent tab now too.
- Fixed while at it: at 1280 px the top bar pushed the whole page wider than the window (it now fits; session
  details hide below 1400 px).
- Tests: 48 passed. Browser-tested in the sandbox: the whole co-pilot flow with mocked proposals (approve, skip, 409,
  timer out, expired), mode, symbol, time zone, stopped state; Start / Stop / Hold against the real sandbox backend.

### 2026-09-26: the Market tab is now part of the Bot tab (your request via Chat A)
- One tab, **Bot**: the live chart (Auto, Replay and its bar) fills the left, the bot's open trades sit in a strip under
  it, and the live card is a column on the right (hero sentence, pills, confidence gauge, last hour, co-pilot options,
  Start / Stop / Hold). A co-pilot proposal lies over the top of the chart while it waits.
- One symbol: the header's switcher drives the bot and the chart; the bid and spread moved into the header badge
  ("Replay" shows there during a replay).
- No stop loss anywhere on the tab, chart included: only the bot's trades are drawn, with yellow entry and green TP
  dots; closed trades show a green exit at TP and a grey one for any other close, stop hits included. Manual and
  Review keep their red SL dots.
- Gone with the Market tab: the Bot trade card, the Open positions list (a count of your and Hermes' trades links to
  the Manual tab), the Size-a-trade calculator (Manual's "Size from stop" does the same) and the second Hold button.
  The "1" key opens Bot; a saved Market key now opens Bot too.
- Fixed (Chat A found it): a notification could cover the Full Auto / Co-pilot switch and stay up forever while the
  pointer sat on it. On the Bot tab notifications now start under the header, and one that pops up under a still
  pointer fades as usual.
- Tests: 49 passed. Browser-tested at 1280x720 and 1440x900 (no scrolling, nothing cut off, also with the replay bar
  open), 0 page errors.

### 2026-09-30 (Chat B): Solana trenching backend, Bongo Cat avatars, quiz schools, Telegram commands (7793203)
- The user asked Chat B to do the backend itself ("no handoff, do it all in here"), and for the debate to be immediate
  so the market can't move while the bots argue. New package `sol/` (map: graphify-out/wiki/sol.md):
  rug filter (6 rules, fails closed), GeckoTerminal + RugCheck feeds, the model crew that splits to train and merges
  into one bot file, a flattened RandomForest (identical answers; whole crew predicts in ~2.6 ms, was ~90 ms), the
  debate (opening + at most 3 rounds, ~0.03 ms), main agents whose subagents can veto (Solana and MT5), paper trading
  with TP / trailing stop / timeout, live Jupiter swaps signed locally (key only from .env, never returned).
- Trenching research (Pump.fun "trenches": fresh launches, most die, take profit fast) -> a preloaded starter set so
  the quiz trains at once, a downloader for real PumpSwap candles (+25 % before -12 % in 30 min), 2+ question creators
  writing questions to disk with their own file positions (no RAM), quiz training with grades per model.
- Quiz tab: Stocks / Trenching (Recommended) / Combined picker and a Trenching school panel. Settings: Telegram
  /prof /loss /total /help (saved chat only). Debate panel shows the main agent's subagent check.
- Avatars rebuilt to the user's spec: suited Bongo Cats in square frames for the main agents only (no subtext),
  typing loop; profit = green fur + glow, arms up and waving, canvas $ rain, two $ locked on the eyes for 2 s, then
  back to typing. "Preview animations" opens a 5-row board (each phase looping, Play, slow motion).
- Rust: measured first; the slow part was the RandomForest (fixed in numpy), the rest is network time.
- Sandbox: GeckoTerminal/RugCheck/Jupiter are blocked by the network policy here, so real downloads were not tested;
  the downloader reports that and the starter set trains meanwhile. Tests: 58 passed (9 new in tests/test_sol.py).

### 2026-09-30 (Chat B): Mac support, agent profiles, successful-trade video
- Mac (b7787c0), map in graphify-out/wiki/mac.md. `Trading Bot.command` is the Mac installer + launcher: detects
  macOS 12+, Apple silicon / Intel (switches a Rosetta Terminal to native), Homebrew, Python 3.10-3.13, libomp, git /
  Command Line Tools, installs what's missing after asking, builds .venv, updates, installs packages, makes
  `Trading Bot.app`. Checked: the XGBoost and LightGBM Mac wheels need Homebrew's libomp, so it installs it.
  Tested here: `--check` on Linux, a simulated Mac (stub uname/sw_vers/xcode-select/brew) and a real install run.
- MetaTrader5 is Windows-only, so Macs reach MT5 through `agent/mt5_remote.py` (RemoteMT5 drop-in + a stdlib bridge
  next to MT5 on a Windows PC/VM, `MT5 Bridge.bat`), with Settings > MT5 connection and a Test button. Everything
  else runs natively: Mac pop-ups over full-screen apps without stealing focus (AppKit), Notification Center alerts,
  Ollama via Homebrew, native Hermes Agent, ⌘ key labels, WebKit prefixes. Not testable here: real macOS/AppKit calls
  (all wrapped so a failure falls back to pywebview's own behaviour).
- Agent profiles: an expand button at the bottom right of each Solana avatar opens its profile under the crew:
  points (trades / quiz), rank, quiz grade, a 1-minute chart of the coin it's on with the buy and sell marked, its
  confidence now and over its last debates, and what it has done (its call, the crew's verdict, result, points).
  Backend: votes table in sol.db (record / link / settle), `GET /api/sol/agent/{model}`.
- Video preview of a successful trade (scripted data, real UI): debate -> buy -> climb -> take profit +30 % -> the
  crew celebrates (close-up) -> LightGBM's profile. Tests: 69 passed.

### 2026-09-30 (Chat B): rank system + Ranks tab
- The crew climbs a trading-desk ladder: Intern, Junior Trader, Trader, Senior Trader, Portfolio Manager, Partner,
  Legend. Needs points (trade points + latest quiz grade), closed trades and, from Senior up, accuracy. Promotes at
  once, demotes only when clearly below (no flicker). Rank changes the suit (lanyard, tie colours, pocket square, tie
  bar, gold tie + pin, Legend's brass frame) and the vote weight in the debate (1.0 to 2.0). Promotions: ring + chip
  pop + "Promoted" tag + notification + Telegram; history in sol.db rank_log.
- Fixed while doing it: quiz points used to add up on every training, so pressing Train again would have ranked
  agents up without trading; they now hold the latest grade.
- New Ranks tab: the ladder with the agents on each rank, their points and % to the next rank, standings, promotions.
  Profiles show the rank and a Career section. Tests: 73 passed (4 new).

### 2026-09-30 — Tweet radar: every agent's own monitor on X, and one-line installers (Chat B)
- Each agent now has **its own tweet monitor** (`sol/tweets.py`) on a different beat, so four monitors don't keep
  finding the same coin: XGBoost reads new launches, LightGBM the runners, RandomForest the crowd, CatBoost the
  callers (plus any handles you add). Two providers: twitterapi.io ($0.15 / 1,000 posts) and the official X API
  ($0.005 a post); off until a key is saved.
- **The filters all still apply.** A find is a candidate, nothing more: mints are read out of the text and out of
  pump.fun / Dexscreener / Birdeye / Solscan / gmgn / Axiom / Photon / BullX links, cashtags are looked up on
  GeckoTerminal, and then every one goes through `engine.evaluate` — the six rug rules, the model floor, the
  debate and the subagents' veto. The radar only decides *which coins get looked at first*.
- Before that it has its own bar, so the app doesn't pay to look up spam: coin-spam wording, minimum likes,
  minimum followers, minimum account age, maximum post age, and at least 2 different accounts on a coin unless
  one big account (25k+) posts it alone. Heat (0-100) sorts what is left — loud, fresh, widely repeated, found by
  a higher-ranked agent, and found by more than one beat all score higher — and only the top few a round get
  checked.
- New: Tweet radar panel in the Solana tab (provider, key, start/stop, Read now, a running cost estimate in
  dollars a day, a card per agent with its beat and what it read, and the finds table with what happened to each),
  and the same monitor inside each agent's profile. `GET /api/sol/tweets`, `POST /api/sol/tweets/{monitor,key,beat,round}`.
- The X key is the first entry in `settings.SECRETS`: saved to `data/settings.json`, but `/api/status` and
  `/api/settings` hand back the placeholder `__saved__` instead, and sending that placeholder back never wipes
  the real key. No route ever returns it.
- Cat animations, as asked: **typing is the only animation while an agent is doing anything** — watching,
  debating, reading X, holding a trade — and profit is the only thing that changes it (green fur, arms in the
  air waving, $ raining and locking on the eyes for 2 s, then back to typing). Checked in the browser, not just
  in the CSS; the preview board row is relabelled "Typing (everything else)".
- **One-line installers**: `install.ps1` (PowerShell) and `install.sh` (bash, macOS + Linux). They check Python,
  git and — on a Mac — the chip, Homebrew and libomp, install only what is missing after asking, download the app,
  make a Desktop shortcut on Windows, and start it. Run the same line later and it just updates. The bash one was
  run end to end in the sandbox. Links are at the top of the README.
- Tests: 79 passed (6 new, including one that proves a coin everyone is tweeting about is still thrown out by the
  rug filter and nothing is bought).

### 2026-10-01 — Simpler app overall; the trenchers get more data and training that shows it (Chat B)
User asked for two things at once: "make the app simple overall" and "give the trenchers more data and improve the
training too see real data/improvement."

**Simpler:**
- The rail had grown to 12 tabs. Now six stay always visible (Bot, Manual, Solana, Agent, Hermes, Settings) and six
  fold behind one "More" toggle (Ranks, Review, Train, Quiz, Keys, Sounds), collapsed by default, remembered in
  localStorage. A link into a folded tab (the Keys/Sounds "change" links) opens the group first.
- **Found and fixed a real bug while building this**: the toggle button shared the `.rail-btn` class for a matching
  look, which meant the app's existing generic rail-click wiring also caught it and called `showTab(undefined)` —
  which then matched *every* button lacking `data-tab` (`undefined === undefined`) and hid whatever tab was open.
  A screenshot caught it (the gold highlight jumped onto "More" and the open tab vanished) before it shipped; fixed
  by scoping those two queries to `.rail-btn[data-tab]`.
- Solana tab: the control bar drops from 5 buttons to 3 (scanner, mode, auto-trade). "Build dataset" and "Train
  Parallel Ensemble" move into a "Data & training" disclosure, since both now run by themselves (see below) — along
  the way, fixed their copy, which had never matched what the buttons actually do ("checking wallets against the
  four skill rules", "0 of N wallets skilled" while running: leftover text from an earlier design; the real
  `trench.download()` has only ever pulled GeckoTerminal pool candles). The tweet radar's four per-agent beat cards
  now collapse behind one summary line by default; the finds table stays visible.

**More data, and training that shows it:**
- `sol/trench.py download()` now reads four pool lists (new pools, PumpSwap trending, Raydium trending, overall
  trending) instead of two, on a recurring timer (`trench_download_min`, default 20 min) instead of once at boot,
  and looks at more pools per round (40, was a fixed 24).
- Training now retrains itself: once real data has grown by `trench_auto_retrain_gap` (400) since the last
  training, `train_quiz()` runs on its own. Every training (manual or automatic) is logged to a new
  `training_log` table (AUC, per-model AUC, real-sample count, whether it was automatic).
- New in the Quiz tab's Trenching school: a **"Real improvement over time"** chart — every crew member's AUC across
  its trainings, plus the merged bot, with a hover tooltip and a plain sentence ("Merged bot: AUC 0.600 -> 0.718
  (+0.118) across 5 trainings, 3,340 more real moments than the first one"). This is the direct answer to "see real
  data/improvement": pressing Train repeatedly as data grows now visibly moves a real number, not a snapshot.
- Verified with seeded training_log rows in the sandbox (never committed; `data/` is gitignored) and screenshots of
  both the collapsed/expanded states and the chart with its tooltip. Tests: 85 passed (6 new).

<!-- Chat B: add new entries above this line -->
