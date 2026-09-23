# M1 trading agent (`agent/`)
- **config.py**: `TIMEFRAME="M1"`, HardwareConfig (6 physical / 12 logical, GPU train, 2 predict threads), LabelConfig (ATR14, stop 1.2×ATR, RR 1.5, horizon 30 bars), RiskConfig (0.5%, daily 3%, 12 trades/day, spread/ATR ≤ 0.15, session 9–22 server, rollover 23–1, magic 260923), AgentConfig.
- **hardware.py**: sets OMP/MKL threads; `xgb_cuda_available()` checks that XGBoost really trains on the GPU (catches silent CPU fallback); torch TF32 + cuDNN if present.
- **features.py**: causal features (returns, EMA 20/50/200/750/3000 distance and slope, RSI, ATR rel, BB pos, range pos, wicks, vol z, spread/ATR, time of day, weekday) + `triple_barrier` labels (spread-aware, stop-first when both hit).
- **model.py**: `SignalModel`, XGBoost multi:softprob 3-class, GPU train, CPU predict, save/load JSON + meta (best_iteration).
- **train.py**: chronological split with a horizon gap, prints out-of-sample threshold table (trades, win %, avg R, total R).
- **risk.py**: `lots_for_risk`, `RiskGate` (daily stop, trade cap, session, rollover, spread filters).
- **broker.py**: `Journal` CSV, `MT5Data`, `PaperBroker` (bar-based SL/TP), `LiveBroker` (order_check + order_send, filling mode).
- **run.py**: loop; cheap poll for a new closed bar; paper default; `--live` demo only unless `--allow-real`; STOP file kill switch.

## Hardware
Ryzen 5 7600: numpy/pandas and live inference; Strategy Tester 10–12 agents. RTX 4060 8 GB: XGBoost CUDA training, optional small PyTorch nets (bf16), and a local Hermes 3 8B Q4 (~5 GB).
