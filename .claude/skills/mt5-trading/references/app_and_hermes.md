# Desktop App & Hermes

The user prefers the app over typing commands. Describe actions as "tab → button".

## Launch
Double-click `Trading Bot.bat` in the repo folder. The first run creates `.venv` and installs `requirements.txt`
(a few minutes). After that it opens a native window (pywebview) or the default browser at `http://127.0.0.1:8420`.
MetaTrader 5 must be open and logged in, with Algo Trading on (Ctrl+E) for demo/real agent modes.

## Tabs
| Tab | What's there | Maps to |
|---|---|---|
| Market | M1 candle chart for the watchlist, live quote and spread, "Size a trade" calculator, open positions with Close buttons, **hold-to-flatten** kill switch | `app/mt5_service.py`, `/api/kill` |
| Agent | Paper / Demo / Real (Real locked until unlocked in Settings), threshold and risk sliders, Start/Stop, live log, journal table | `python -m agent.run` |
| Train | Fetch data (M1 history → `data/<SYMBOL>_M1.parquet`), Train (XGBoost on the RTX 4060, prints out-of-sample table), then Open Agent | `fetch_m1.py`, `python -m agent.train` |
| Hermes | Chat assistant with memory, suggested prompts, Memory panel (add/forget facts) | `app/brain.py`, `app/memory.py`, `app/tools.py` |
| Settings | Symbol, watchlist, terminal path, point size, history days, Hermes backend/URLs/key/model, VRAM idle unload, web access, MCP bridge autostart | `data/settings.json` |

Top bar: demo/real badge, equity (counts up on open), floating P/L, free margin, RAM and VRAM meters, agent state.

## Hermes backends
- **Local**: `hermes3:8b` in Ollama on the 4060. Tools: account, positions, M1 market summary, position size,
  agent status/start/stop, remember/recall, web_fetch, notes, calculate, time. No order placement (by design).
- **Hermes Agent** (Nous Research, runs in WSL2): OpenAI-compatible API server on :8642 with its own persistent
  memory and skills, plus the MT5 MCP bridge (`http://localhost:8765/mcp`) for full trading tools, including orders with a risk guard.
- **Auto**: Hermes Agent if reachable, else local.
Setup steps: `hermes/SETUP.md`. Seed memory: `hermes/user_seed.md`.

## Disk vs RAM
Running code must be in RAM. Everything persistent is on disk: `data/` (settings, memory.db, notes, M1 history),
`logs/` (job logs, journals), `models/`. The Hermes model sits in VRAM and unloads after the idle time in Settings.

## Troubleshooting
| Symptom | Fix |
|---|---|
| Badge says "MT5 offline" | Open MT5 and log in; set the terminal path in Settings if you have several installs |
| "No trained model" on Start | Train tab → Fetch data → Train |
| Hermes pill "Ollama not running" | Start Ollama; `ollama pull hermes3:8b` |
| Hermes pill "Hermes Agent not running" | In WSL: `hermes gateway`; check API key in Settings |
| Agent log shows retcode 10027 | Algo Trading button off in MT5 (Ctrl+E) |

## Trading alongside the bot
The bot keeps its own ledger in `data/trades.db` (`agent/ledger.py`). It covers paper, demo and real trades, and it survives restarts.
- **Ownership by magic number**: bot = 260923, Hermes/MCP = 260924, anything else (your manual trades, magic 0) = "You".
  Positions on the Market tab carry a Bot / Hermes / You tag. The bot never touches, sizes against, or counts your trades.
- **Exits are always recorded**: in demo/real the agent reconciles with MT5 every second (`sync_ledger`). The app also
  reconciles on every refresh, so SL/TP hits, manual closes (tagged "manual"), kill-switch closes and stops you moved in MT5 are
  captured with the real P/L (incl. commission and swap), even if the agent wasn't running.
- **Daily loss limits**: the bot's 3% stop counts only the bot's own P/L, so your manual losses don't pause it. A separate
  6% whole-account stop still protects the account.
- **Netting accounts** merge positions per symbol, so the bot waits while you hold that symbol. Hedging accounts have no conflict.
- **Following it**: the Market tab's *Bot trade* card shows side, entry, stop, target, confidence and live P/L/R. The chart draws
  the bot's entry/SL/TP lines and entry/exit markers (exits labelled in R). *Size mine* loads the bot's stop into the sizer at
  your own risk %, and *Copy levels* copies "XAUUSD BUY entry … SL … TP …". You get a toast and a sound (toggle in Settings)
  when it opens or closes a trade.
- **History**: Agent tab → *Bot trades* (filter All/Paper/Demo/Real) with closed trades, win rate, net and today's P/L,
  total R, avg R, profit factor. Hermes can answer "what is the bot doing?" via its `get_bot_trades` tool.

## Bot money rules (the user's choice; set in Settings → Bot money rules)
- **Stake** = margin committed per trade = 0.1% of balance. If that's below the minimum lot (0.01 on XAUUSD), the minimum lot is used.
- **Stop loss** = the trade has lost 25% of its stake. **Take profit** = +200% of stake for the smallest trade (minimum lot),
  easing log-scaled to +50% at 1.00 lot and above (anchors adjustable; 0 = auto).
- **Max 25** bot trades open at once (1 on netting accounts), at most one new entry per M1 candle, 100 new entries/day.
- Price distances depend only on leverage: stop ≈ 0.25 × price / leverage (XAUUSD at 1:100 ≈ $6.6; at 1:500 ≈ $1.3).
  The bot skips an entry if the spread is over 35% of the stop, or if the stop is inside the broker's stops level.
- Reward:risk is up to 8:1, so the break-even win rate is ~11%. Expect low win rates and long losing streaks. Confidence
  thresholds are therefore low (0.1–0.3); training prints and saves a suggested threshold.
- The model is trained on these exact exits (`agent.train --margin-rate --sl-pct --tp-pct`); retrain after changing them.
- Agent tab → *Each trade right now* shows balance, leverage, stake, lots, SL/TP in money and price, reward:risk, and the
  worst case if all open trades stop out (warns above 5% of balance or when the minimum lot is forced).
- Real mode is locked by default: tick *Unlock Real mode* in Settings (per session), then confirm on Start.

## Score system
Each closed bot trade scores the % it gained or lost on its stake (full +200% target = +200 points). A stop-loss hit costs
1.5× (−25% → −37.5); a trade the bot closes early (model turned against it), the kill switch, or a manual close costs only
what it actually lost. Shown on the Agent tab (Score, Today's score, Avg points, Stops / early exits) and in close alerts.
Early exit: opposite-side probability ≥ threshold and ≥ 2× the trade's own side. Toggle in Settings.
