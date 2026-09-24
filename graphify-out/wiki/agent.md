# M1 trading agent (`agent/`)
- **config.py**: `TIMEFRAME="M1"`, MoneyConfig (stake 0.1% of balance as margin, SL −25% of stake, TP +200%→50% of stake log-scaled from minimum lot to 100× minimum, max 10 open at once, skip if spread > 35% of stop), HardwareConfig (6 physical / 12 logical, GPU train, 2 predict threads), LabelConfig (ATR14, stop 1.2×ATR, RR 1.5, horizon 30 bars), RiskConfig (0.5%, daily 3%, 12 trades/day, spread/ATR ≤ 0.15, session 9–22 server, rollover 23–1, magic 260923), AgentConfig.
- **hardware.py**: sets OMP/MKL threads; `xgb_cuda_available()` checks that XGBoost really trains on the GPU (catches silent CPU fallback); torch TF32 + cuDNN if present.
- **features.py**: `triple_barrier` accepts per-row `sl_dist`/`tp_dist`; causal features (returns, EMA 20/50/200/750/3000 distance and slope, RSI, ATR rel, BB pos, range pos, wicks, vol z, spread/ATR, time of day, weekday) + `triple_barrier` labels (spread-aware, stop-first when both hit).
- **model.py**: `SignalModel`, XGBoost multi:softprob 3-class, GPU train, CPU predict, save/load JSON + meta (best_iteration).
- **train.py**: labels with the stake exits (`--margin-rate --sl-pct --tp-pct --horizon`, default horizon 240), chronological split with a horizon gap, prints break-even win rate and the out-of-sample threshold table, and saves `suggested_threshold` + `exit_rule` in model meta.
- **risk.py**: `stake_plan` (lots/stake/SL/TP money + price distances, forced_min, worst case), `tp_pct_for_stake`, `lots_for_risk`, `RiskGate` (bot-only daily stop 3% from `bot_pnl_today`, account-wide stop 6%, trade cap, session, rollover, spread filters).
- **score.py**: `trade_score(pnl, ...)`: 1 point = $1 of P/L, stop hits × `SL_MULT` (1.5).
- **ledger.py**: (+ stake, score, close_hint columns; `set_close_hint`; score stats) bot trade ledger `data/trades.db` (open_trade, close_trade with R from original stop `sl0`, update_levels, open_trades, recent, realized_pnl, stats). Shared by agent and app.
- **broker.py**: `Journal` CSV, `MT5Data`, `PaperBroker` (bar-based SL/TP, ledger-backed, restores open trade + equity after restart), `sync_ledger()` (reconciles ledger with MT5 positions/deals: exit price, P/L incl. commission/swap, reason sl/tp/manual/stop_out, SL/TP edits), `LiveBroker` (magic-filtered, adopts orphan bot positions, `foreign_position()` for netting accounts).
- **run.py**: loop; `broker.sync()` every second; cheap poll for a new closed bar; paper default; `--live` demo only unless `--allow-real`; modes paper/demo/real; netting guard; early exit when the model flips (`close_one(..., "early")`); records prob, risk_money and open_bar per trade; STOP file kill switch.

## Hardware
Ryzen 5 7600: numpy/pandas and live inference; Strategy Tester 10–12 agents. RTX 4060 8 GB: XGBoost CUDA training, optional small PyTorch nets (bf16), and a local Hermes 3 8B Q4 (~5 GB).
- **progression.py**: stage ladder (paper → demo → real_1 (2 open) → real_2 (5) → real_3), gates, evaluate/promote/demote, data/progression.json.
- **learn.py**: analyze ledger → learned_rules.json + `.claude/skills/m1-bot-lessons/`; `block_reason()` used by run.py.
- **practice.py**: `Practice.decide()` top-10% of the last 1440 confidence readings (Paper/Replay).
- **quiz.py**: quiz school. `build` (40-100,000) -> data/quiz.json + quiz_x/quiz_bars/quiz_times .npy: 18 setups
  (`_candidates`), vectorised outcomes (`_outcomes`), clean winners / traps / stay-out spots, best-first across years
  (`_year_balanced`), adaptive spacing 60/30/15, contradictions + near-copies removed with top-up, easy/medium/hard
  (`_neighbours`); `train [--resume] [--focus ids]` -> (49 indicators + 178 chart inputs)-64..512-3 network,
  REINFORCE with per-question baseline, batched (64/step), never revisits finished (finish = 5 in a row + best answer
  right), silent refresher + memory check every 10 rounds, adaptive exploration, loops until done (stall tactics:
  extra reps + bigger steps -> grow network -> reset stuck); writes .claude/skills/quiz-lessons; progress data/quiz_progress.npz,
  agent models/quiz_policy.json, live data/quiz_state.json. `--quiz-filter` in run/replay.
- **quiz_report.py**: weak-spot report (every 5 min + end of run): groups by setup/trap, weak spots, missed-vs-right
  contrasts, trap separability, fixes -> data/quiz_report.{md,json} + .claude/skills/quiz-weak-spots/.
- **pro.py**: professional-trader inputs (prior-day levels, Asian range, London/NY opening ranges, session average,
  liquidity sweeps, FVGs, H1 structure, round numbers) added by `build_features`; `active_setups()` / `primary_setup()`
  name setups for the bot card, ledger `setup` column and learn.py "by_setup" / `blocked_setups`.
- **history.py**: `python -m agent.history --years N` downloads free XAUUSD M1 (HistData 2009+, HF dataset
  fokan/xauusd-2009-2026, EST +7h -> server time, spread filled) to data/<SYM>_M1_history.parquet; `load_bars()` merges it
  with the MT5 file (MT5 wins on overlap, ns index). Used by train.py (`--no-history` to skip) and replay.py.
  Features have no volume (history has none) and are float32. RAM ~0.5 GB per year of candles when training.
- **replay.py**: history replay at slider speed (0 = Max; --days 0 = all; --from test|end|all|date); spread/ATR filter off unless --strict-filters;
  skip-reason Counter in replay_state.json ("skips"); PaperBroker.clock stamps trades with the replayed candle's UTC time so daily limits/learned hours are historical; (data/replay_control.json -> data/replay_state.json), mode "replay" in the ledger.
