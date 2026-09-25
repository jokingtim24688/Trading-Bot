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

<!-- Chat B: add new entries above this line -->
