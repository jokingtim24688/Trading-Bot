# Solana trenching bot (`sol/`)

Built 2026-09-30 by Chat B (the user said: "no handoff, do it all in here"). Paper trading by default; live needs
`SOL_PRIVATE_KEY` in `.env` plus a typed LIVE, and no route ever returns the key.

"Trenching" = Solana slang for digging through brand-new Pump.fun / PumpSwap launches to buy before a coin is widely
noticed. Most launches die within hours, snipers and insiders get the cheapest coins, and survivors take profit fast.

## Files
| File | What it does |
|---|---|
| `sol/store.py` | SQLite `data/sol.db`: `seen` (feed), `positions` (open + closed trades), `bots` (score, quiz points, last_win), `debates` (24 h) |
| `sol/rug.py` | 6 rug rules (mint + freeze authority revoked, LP >= 90 % locked, top 10 <= 30 % excl. pools, liquidity >= $5k, dev <= 5 %). Missing data fails closed |
| `sol/features.py` | the 8 features (log liquidity, age, buys/sells 5 m, buy share, log volume 5 m, move 5 m, top-10 %) and the label: +25 % before -12 % within 30 one-minute candles |
| `sol/feeds.py` | GeckoTerminal (new pools, PumpSwap pools, 1-minute candles, prices; ~2 s between calls) and RugCheck (authorities, locked LP, holders). Short timeouts, failures return nothing |
| `sol/model.py` | the crew: XGBoost, LightGBM, RandomForest (+ CatBoost if installed). **Split** while training (each model in its own thread, 5-fold out-of-fold answers), then **merged** into one bot: `data/sol_models/bot.joblib` = members + a logistic judge. `FastForest` flattens the RandomForest into arrays: identical answers, ~0.2 ms instead of ~75 ms. Whole crew predicts in ~2.6 ms |
| `sol/debate.py` | the argument, **immediate**: opening + at most `MAX_ROUNDS` (3) DeGroot rounds (each model moves halfway toward the others, proven models pull harder), then a forced decision. ~0.03 ms. BUY needs consensus >= 0.78 and every model >= 0.65; the compromise shrinks size and tightens the trail when they're split or close to the line |
| `sol/agents.py` | **main agents + subagents**: every coin / MT5 symbol has a main agent; before a trade its subagents check one thing each and can veto (Solana: Risk, Rug check, Price drift, Momentum, Skeptic; MT5: Confidence, Reward/risk, Momentum, Quiz agent (advisory)). One veto = no trade. Latest reviews in `data/agents.json`, `GET /api/agents` |
| `sol/engine.py` | scanner thread (new pools every `sol_scan_s`), `evaluate()` = rug gate -> models -> debate -> main agent review -> paper/live trade; monitor thread every 5 s: TP (+30 % or the compromise), trailing stop (-10 % from peak), hard stop (-15 %), 20-min timeout. On close each model scores `+pnl%` if its final stance was BUY, `-pnl%` if PASS |
| `sol/wallet.py` | live only: key from `.env`, balances over `SOL_RPC_URL` (e.g. Helius) or public RPC, Jupiter quote + swap (lite-api first, then quote-api v6), signed locally with `solders` |
| `sol/trench.py` | trenching data + quiz: **starter set** (6,000 moments, flagged synthetic) preloaded on first start so the quiz trains at once; **downloader** (`download()`) labels every 3rd minute of real PumpSwap/new-pool candles; **question creators** (at least `quiz_min_creators` = 2, restarted by a watchdog) write `data/quiz_bank/trenching/questions.jsonl`, each with its own file position (`creator_k.pos`), nothing held in RAM; `train_quiz()` = split, learn, grade on unseen questions (quiz points = (AUC - 0.5) x 200), merge |
| `sol/api.py` | routes, included by `app/server.py`; `startup()` loads the merged bot, starts the monitor and the trenching boot (starter set, creators, background download) |

## Routes
`GET /api/sol/state` (scanner, mode, wallet (public), paper balance, model incl. `merged`, training, dataset, apis,
config, `bots[]`, `crew{merged,training}`, `debate{max_rounds,last_ms}`), `GET /api/sol/feed`, `GET /api/sol/debate/{mint}`
(rounds, consensus, compromise, `review` = main agent + subagents, `probs`, `ms`), `GET /api/sol/positions`,
`GET /api/sol/trades`, `GET /api/sol/pnl`, `POST /api/sol/scanner {run}`, `/autotrade {on}`, `/mode {mode, confirm:"LIVE"}`,
`/train`, `/dataset`, `/positions/{id}/close`. Trenching quiz: `GET /api/trench/state`, `GET /api/trench/question`,
`POST /api/trench/train`, `POST /api/trench/download`, `POST /api/quiz/mode {stocks|trenching|combined}`. `GET /api/agents`.
Agent profile: `GET /api/sol/agent/{model}` (score split, rank, `stats` from the votes table, `confidence{last, need,
floor, series}`, `activity[]` with open/closed/passed status, points and P/L, `chart{symbol, candles, markers,
position}` for the coin it's on (candles from GeckoTerminal, cached 30 s), `model_info{auc, weight}`).
Votes: `store.votes` table, one row per model per debate (`record_votes` in `evaluate`, `link_votes` when the trade
opens, `settle_votes` on close = the points each model gets).

## Settings (app/settings.py)
`quiz_mode` (default trenching), `quiz_min_creators` (2), `telegram_commands` (True), `sol_trade_size_sol` 0.1,
`sol_max_open` 3, `sol_tp_pct` 30, `sol_trail_pct` 10, `sol_timeout_min` 20, `sol_buy_threshold` 0.78,
`sol_model_floor` 0.65, `sol_min_liq_usd` 5000, `sol_scan_s` 10, `sol_paper_start` 10.

## Elsewhere
- `agent/run.py`: before every MT5 entry the symbol's main agent runs its subagents (`sol.agents.mt5_subagents`); a veto
  skips the trade with the reason on the bot card.
- `agent/quiz.py`: the stocks question bank runs with 2 creators (`bank --watch --workers 2`).
- `app/telegram.py`: `/prof`, `/loss`, `/total`, `/help` answered by a long-poll thread, only for the saved chat;
  closed trades only (MT5 paper/demo/real in money, Solana paper/live in SOL). `notify_text()` for Solana alerts.
- Tests: `tests/test_sol.py` (9 tests).
- Rust: measured first; the debate (0.03 ms) and review are arithmetic, the crew predicts in 2.6 ms, so the time is in
  the network calls. Rust would help only if the scanner ever evaluates thousands of coins a second.

## Ranks (`sol/ranks.py`, 2026-09-30)
Career ladder: Intern -> Junior Trader (25 pts) -> Trader (75 pts, 5 closed trades) -> Senior Trader (150, 15, 55 %
right) -> Portfolio Manager (300, 30, 58 %) -> Partner (600, 60, 60 %) -> Legend (1200, 120, 62 %). Points = trade points
+ the latest quiz grade (quiz points now replace, not add up, so training again can't farm rank). Trades / accuracy
come from the votes table. `rank_for(..., current)` promotes at once and demotes only when clearly below (10 % under
the points or 2 points under the accuracy). `update()` runs after each close (engine.close) and each quiz training,
writes `bots.rank`/`rank_t` + `rank_log`, and `engine.announce_rank` sends Telegram. Rank = vote weight in the debate
(`debate.run(weights=ranks.weights())`: 1.0 / 1.1 / 1.2 / 1.35 / 1.5 / 1.7 / 2.0; `d["weights"]` shown in the transcript).
Routes: `GET /api/sol/ranks` (ranks with who's on them, agents with points / trades / accuracy / next{needs, frac} / pct,
log), `career` in `/api/sol/agent/{model}`, `rank` in `bots[]` of `/api/sol/state`.

