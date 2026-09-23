# Local Trading Agent: RTX 4060 + Ryzen 5 7600

The repo's `agent/` package is an M1 trading agent sized for this PC. This file explains the hardware
choices and how to run and tune it.

## The hardware and what it's good at
| Part | Specs that matter | Best use |
|---|---|---|
| **Ryzen 5 7600** | Zen 4, 6 cores / 12 threads, AVX-512, ~5.1 GHz boost | Feature engineering (numpy/pandas), live inference, MT5 terminal, Strategy Tester agents |
| **RTX 4060** | Ada (sm_89), 8 GB GDDR6, 3,072 CUDA cores, 4th-gen Tensor cores, FP16/BF16 | Training gradient-boosted trees (XGBoost CUDA) and small neural nets; optional local LLM |
| RAM | 32 GB recommended (16 GB minimum) | 1–3 years of M1 bars + features fits in < 2 GB |
| Storage | NVMe SSD | Parquet tick/bar store |

## Why this model stack
An M1 decision happens once every 60 seconds, so inference speed isn't the limit. Data quality and costs are.
- **Primary model: XGBoost (`device="cuda"`, `tree_method="hist"`).** Gradient-boosted trees are the strongest
  and most robust choice for tabular price features. On a 4060, training on ~1M M1 rows × 40 features takes
  seconds to a few minutes, which makes walk-forward retraining cheap. Inference on one row runs on the CPU in < 1 ms.
- **Optional sequence model (upgrade path): small 1D-CNN/TCN or GRU in PyTorch** with `torch.autocast(dtype=torch.bfloat16)`.
  Keep it under ~5M params and batch 1024–4096 windows of 64–256 M1 bars. That uses about 2–4 GB of VRAM and leaves room.
  Only adopt it if it beats XGBoost out of sample after costs.
- **Not recommended for per-bar decisions: LLMs.** A 7–8B model (e.g. Qwen2.5-7B-Instruct or Llama-3.1-8B at Q4_K_M,
  ~5 GB VRAM via Ollama/llama.cpp) runs ~40–60 tokens/s on a 4060. That's fine for summarizing news, the economic
  calendar, or the trade journal, but it's too slow and non-deterministic to be the signal. Unload it before GPU training (8 GB is shared).
- **Reinforcement learning**: overfits easily on M1 and is hard to validate. Not included.

## Thread & GPU settings (applied by `agent/hardware.py`)
| Setting | Value | Why |
|---|---|---|
| `OMP_NUM_THREADS`, `MKL_NUM_THREADS` | 6 | Physical cores; SMT adds little for numpy math |
| XGBoost train (GPU) | `device="cuda"`, `max_bin=256` | Uses the 4060 |
| XGBoost train (CPU fallback) | `n_jobs=12` | All threads when the GPU is absent |
| XGBoost live predict | CPU, `n_jobs=2` | Leaves cores for the MT5 terminal; no GPU transfer overhead |
| PyTorch | `set_float32_matmul_precision("high")`, cuDNN benchmark, bf16 autocast | Ada Tensor cores |
| Strategy Tester agents | 10 while the live agent runs, 12 otherwise | Keep 1 core for terminal + agent |
| Windows | Power plan "High performance"/"Ryzen Balanced", disable sleep, GPU driver "Prefer max performance" for python.exe | Avoid stalls/latency |
| Process priority | Agent "Above normal"; don't set "Realtime" | Stable timing without starving the OS |

## Install (Windows, on the trading PC)
```powershell
# Python 3.11 x64
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# optional neural net upgrade (CUDA 12.x wheels):
# pip install torch --index-url https://download.pytorch.org/whl/cu124
```
Check the GPU: `python -m agent.hardware` prints the CPU thread plan and whether CUDA XGBoost is available.

## Workflow
1. **Fetch M1 history** (terminal open, symbol in Market Watch, Max bars = Unlimited):
   `python .claude/skills/mt5-trading/scripts/fetch_m1.py XAUUSD --days 365 --out data/XAUUSD_M1.parquet`
2. **Train with walk-forward check**:
   `python -m agent.train data/XAUUSD_M1.parquet --symbol XAUUSD`
   This prints out-of-sample stats per probability threshold (trades, win %, avg R after spread).
   Pick a threshold with enough trades and avg R > 0.1.
3. **Paper trade** (default mode; places no orders):
   `python -m agent.run --symbol XAUUSD --threshold 0.55`
4. **Demo live** (real orders on a DEMO account):
   `python -m agent.run --symbol XAUUSD --threshold 0.55 --live`
5. **Real account**: requires `--live --allow-real`, and only after weeks of stable demo results.

## Safety built into the agent
- Timeframe hard-locked to M1 (`config.TIMEFRAME = "M1"`; not a CLI option).
- Acts only on closed bars.
- Risk % per trade (default 0.5%), daily loss stop (3%), max trades/day, max 1 position per symbol.
- Spread filter (vs rolling median and ATR), session filter, rollover blackout.
- Refuses to trade a real-money account unless `--allow-real` is passed.
- Kill switch: create a file named `STOP` in the working directory and the agent flattens and exits.
- CSV journal of every signal, order, and fill in `logs/`.

## Tuning checklist
- Retrain weekly or monthly (walk-forward). Compare with the previous model on the same test window.
- Watch live slippage vs backtest assumptions; if avg slippage > 30% of the modeled spread, widen the filters.
- Keep features causal. Any new feature must use only bars ≤ the last closed bar.
- One symbol per process. Run several processes for several symbols (the 7600 handles 4–6 easily).
