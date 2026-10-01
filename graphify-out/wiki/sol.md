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
| `sol/trench.py` | trenching data + quiz: **starter set** (6,000 moments, flagged synthetic) preloaded on first start so the quiz trains at once; **downloader** (`download()`, 2026-10-01: four pool lists, not one, see below) labels every 3rd minute of real PumpSwap/new-pool candles, **on a recurring timer**, not just once at boot; **question creators** (at least `quiz_min_creators` = 2, restarted by a watchdog) write `data/quiz_bank/trenching/questions.jsonl`, each with its own file position (`creator_k.pos`), nothing held in RAM; `train_quiz()` = split, learn, grade on unseen questions (quiz points = (AUC - 0.5) x 200), merge, **log to `training_log`**, and (2026-10-01) **retrain itself** once enough new real data has come in |
| `sol/api.py` | routes, included by `app/server.py`; `startup()` loads the merged bot, starts the monitor and the trenching boot (starter set, creators, background download) |

## Routes
`GET /api/sol/state` (scanner, mode, wallet (public), paper balance, model incl. `merged`, training, dataset, apis,
config, `bots[]`, `crew{merged,training}`, `debate{max_rounds,last_ms}`), `GET /api/sol/feed`, `GET /api/sol/debate/{mint}`
(rounds, consensus, compromise, `review` = main agent + subagents, `probs`, `ms`), `GET /api/sol/positions`,
`GET /api/sol/trades`, `GET /api/sol/pnl`, `POST /api/sol/scanner {run}`, `/autotrade {on}`, `/mode {mode, confirm:"LIVE"}`,
`/train`, `/dataset` (now reads `trench_download_pools` when no `pools` is given, instead of a hardcoded 24),
`/positions/{id}/close`. Trenching quiz: `GET /api/trench/state` (now also carries `history`: `store.training_log`,
oldest first, each row's AUC/members/weights/real_samples/auto), `GET /api/trench/question`, `POST /api/trench/train`,
`POST /api/trench/download`, `POST /api/quiz/mode {stocks|trenching|combined}`. `GET /api/agents`.
Agent profile: `GET /api/sol/agent/{model}` (score split, rank, `stats` from the votes table, `confidence{last, need,
floor, series}`, `activity[]` with open/closed/passed status, points and P/L, `chart{symbol, candles, markers,
position}` for the coin it's on (candles from GeckoTerminal, cached 30 s), `model_info{auc, weight}`).
Votes: `store.votes` table, one row per model per debate (`record_votes` in `evaluate`, `link_votes` when the trade
opens, `settle_votes` on close = the points each model gets).

## Settings (app/settings.py)
`quiz_mode` (default trenching), `quiz_min_creators` (2), `telegram_commands` (True), `sol_trade_size_sol` 0.1,
`sol_max_open` 3, `sol_tp_pct` 30, `sol_trail_pct` 10, `sol_timeout_min` 20, `sol_buy_threshold` 0.78,
`sol_model_floor` 0.65, `sol_min_liq_usd` 5000, `sol_scan_s` 10, `sol_paper_start` 10.
Trenching data growth (2026-10-01): `trench_download_min` 20 (minutes between background downloads; the first run
is at once), `trench_download_pools` 40 (was a fixed, one-shot 24), `trench_auto_retrain` True, `trench_auto_retrain_gap`
400 (new real labelled moments since the last training before it trains again by itself).

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


## Tweet radar (`sol/tweets.py`, 2026-09-30)
Every agent has **its own monitor on X**, on a different beat, so four monitors don't keep finding the same coin:

| Beat | Whose | What it reads |
|---|---|---|
| New launches | 1st crew member (XGBoost) | brand-new mints, the minute someone posts them |
| Runners | 2nd (LightGBM) | coins already moving, before the move is over |
| Crowd | 3rd (RandomForest) | what a lot of different accounts keep repeating |
| Callers | 4th (CatBoost) | the accounts with a name to lose, plus the handles in `x_accounts` |

Providers: **twitterapi.io** (`X-API-Key`, `/twitter/tweet/advanced_search`, $0.00015 a post) and the **official X
API v2** (`Bearer`, `/2/tweets/search/recent`, $0.005 a post). `x_provider = "off"` until a key is saved, and the
key is in `settings.SECRETS`: `/api/status` and `/api/settings` return the placeholder `__saved__`, sending the
placeholder back never overwrites it, and no route ever returns the real one.

**A find is a candidate, nothing more.** `_check()` turns it into a snapshot (`feeds.token_pools` for a mint,
`feeds.search_pools` for a cashtag) and hands it to `engine.evaluate`, which runs the same gates as a scanner
find: the six rug rules, the model floor, the debate, the subagents' veto, and auto-trade before anything is
bought. The snapshot is tagged (`found_via`, `found_by`, `found_url`, `found_heat`, `found_model`) so the feed
knows where it came from. The radar only decides **which coins get looked at first**.

Its own bar, before any of that (nothing else is paid for): coin-spam wording, `x_min_likes` (scaled per beat),
`x_min_followers`, `x_min_account_days`, `x_max_age_min`, and `x_min_voices` different accounts on a coin unless
one over `x_big_voice` posts it alone. Mints come out of the text and out of pump.fun / Dexscreener / Birdeye /
Solscan / gmgn / Axiom / Photon / BullX links; wrapped SOL, USDC and USDT are never candidates. **Heat** (0-100)
then sorts what is left: likes, followers, views, freshness, how many voices, verified, a bonus when a second
beat found it too, and × the finding agent's rank weight — the same weight that tips its vote in the debate.
Only `x_max_per_round` coins a round are actually checked; a post is never read twice (`store.tweet_ids`).

Settings: `x_provider`, `x_api_key`, `x_scan_s` (300), `x_per_beat` (15), `x_min_likes` (4), `x_min_followers`
(400), `x_min_account_days` (30), `x_max_age_min` (45), `x_min_voices` (2), `x_big_voice` (25000),
`x_max_per_round` (6), `x_accounts`, `x_beats` (per-agent on/off and search terms).
Store: `tweets` table (`record_tweet`, `tweet_verdict`, `tweet_finds`, `tweet_ids`, `tweet_voices`, `tweet_stats`).
Routes: `GET /api/sol/tweets`, `POST /api/sol/tweets/monitor {on}`, `/key {provider, key}`, `/beat {model, on, terms}`,
`/round`; `tweets` in `GET /api/sol/agent/{model}`.
UI: Tweet radar panel in the Solana tab (provider, key, start/stop, Read now, a cost estimate in dollars a day, a
card per agent, and the finds table with what happened to each) and the same monitor in each agent's profile.

## The avatars, in one line
Two animations only. **Typing** runs the whole time an agent is doing anything — watching, debating, reading X,
holding a trade. **Profit** is the only thing that changes it: green fur, arms in the air waving, $ raining and
locking on the eyes for 2 s, then back to typing. Nothing else touches the cat's pose (a promotion pulses a ring
round the frame, not the cat).

## Trenching data & training that actually shows improvement (2026-10-01, Chat B)
The user's ask: "give the trenchers more data and improve the training too see real data/improvement."

**More data, continuously, not a one-shot 24 pools:**
- `download()` now reads **four** pool lists instead of two, so one quiet source doesn't starve a round:
  `feeds.new_pools(3)` (brand-new, network-wide — the core trenching source), `feeds.trending_pools(2, "pumpswap")`,
  `feeds.trending_pools(2, "raydium")` (migrated runners), `feeds.trending_pools(1)` (network-wide trending, a
  catch-all). Deduped by pool address, filtered by liquidity, capped at `trench_download_pools` (40, up from a
  hardcoded 24) — all pre-existing behaviour, just over four lists.
- `keep_alive()`'s boot loop used to call `download()` exactly once and then only kept the question creators alive.
  It now re-downloads every `trench_download_min` minutes (first run still at once) for as long as the app is open,
  so the real-sample count keeps climbing in the background instead of topping out after the first pull.

**Training that retrains itself, and a history you can watch:**
- `store.training_log` (new table): one row per completed `train_quiz()` — `t`, `n_samples`, `real_samples`,
  `synthetic_share`, `auc`, `precision_at_buy`, `n_test`, `members` (per-model AUC), `weights` (the judge's trust in
  each), `seconds`, `auto` (whether it ran by itself). `store.add_training(meta, real_samples, auto)` /
  `store.training_log(limit)` (oldest first, so a chart reads left to right).
- `trench._maybe_retrain(gap)`: after a download, if `trench_auto_retrain` is on and real samples have grown by at
  least `trench_auto_retrain_gap` (400) since the last training (`trench.state["train"]["last_real_at_train"]`,
  updated on every `train_quiz()`), it calls `train_quiz(auto=True)` itself. Below 60 real rows or already
  training, it does nothing (same floor `model.train()` already enforces).
- UI: the Quiz tab's Trenching school gets a new section, **"Real improvement over time"** (`#qt-hist-sec`,
  `renderTrenchHistory()`), a `solChart` line per crew member plus a thicker gold "Merged bot" line, AUC on the
  y-axis with a "0.5 guessing" reference line, hover tooltip (date + every model's AUC at that training). Below it,
  a plain sentence: `Merged bot: AUC 0.600 -> 0.718 (+0.118) across 5 trainings, 3,340 more real moments than the
  first one - last one ran by itself as new data came in.` One training logged shows a "train again to add a
  point" note instead of a one-point chart.
- The manual "Build dataset" / "Train Parallel Ensemble" buttons moved into a `<details class="sol-adv">` ("Data &
  training") in the Solana tab, since both now happen by themselves; see app.md's Simplicity pass. Their copy was
  also wrong before this (talked about "checking wallets against the four skill rules" and "0 of N wallets
  skilled" — leftover text from a different, never-shipped design): `trench.download()` has only ever pulled
  GeckoTerminal pool candles. Fixed at the API too (`dataset.wallets_checked`/`wallets_skilled` -> `pools_checked`/
  `new_samples`).
- Tests (`tests/test_sol.py`, 6 new): the four-list download with dedup, the configurable pool cap (route and
  function both), `training_log` round-tripping across two trainings, `_maybe_retrain`'s gap gate, the
  `/api/sol/dataset` route no longer hardcoding 24, and `history` riding in `/api/trench/state`. 85 passed.
