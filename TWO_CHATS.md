# Two chats, one repo

Two Claude chats work on this project at the same time. This file says what each chat owns and how the two share
one branch without breaking each other's work. Read it at the start of every task.

- **Shared branch:** `claude/laughing-bell-3vt2c7`, the repo's default branch. Both chats commit and push here, and
  the user's PC pulls it. Your session may have been given its own `claude/...` branch: the user has approved pushing
  to the shared branch instead.
- **Map of the code:** `graphify-out/wiki/index.md`. Read it before you start; update it when you finish.
- **Names:** the user calls Chat A "chat 1" and Chat B "chat 2".
- **Who changes this file's rules:** only the user. When they change the split, update this file in one commit.

## Who does what

### Chat A (chat 1): Backend & Skills

Status: idle. Last: Manual tab backend; the bot learns from each losing trade (2026-09-24).

Owns what the app does:
- `agent/`: trading agent, Quiz school, replay, history, learning, risk and money rules
- `mcp_server/`, `hermes/`
- `app/server.py` (the API), `app/jobs.py`, `app/mt5_service.py`, `app/settings.py`,
  `app/brain.py`, `app/memory.py`, `app/tools.py`
- `.claude/skills/`, `.claude/agents/`: Chat A makes and edits skills. Some skill folders are written by the app on
  the user's PC (`m1-bot-lessons/` by `agent/learn.py`, `quiz-lessons/` by `agent/quiz.py`, `quiz-weak-spots/` by
  `agent/quiz_report.py`). Don't hand-edit those, except the `claude-*.md` pages in `quiz-weak-spots/`.
- Wiki pages: `agent.md`, `hermes.md`, `mcp.md`, `skill.md`, and the server/jobs/settings bullets of `app.md`

### Chat B (chat 2): UI & Polish

Status: idle. Last (2026-09-24, 0f1149b): the 3 approved designs, the Manual tab UI (backend spec for Chat A below),
Quiz bank + web sites handoffs.

Owns how the app looks and feels:
- `app/static/`: `app.css`, the layout of `index.html`, and the visual and interaction code in `app.js`, for every tab
- `app/main.py` (the window) and `Trading Bot.bat` (the launcher)
- `simulation/`
- Wiki page: the `static/` and window parts of `app.md`

For visual work, load the `anti-vibe-polish` skill (`/anthropic-skills:anti-vibe-polish`): remove the generic
AI-generated look and give the app a considered, hand-built finish. The graphite + brass gold palette and the IBM Plex
font are deliberate choices: keep them unless the user asks for a change.

### Where the lanes meet

- **`app/static/`**: both chats touch it. Chat A may add the working parts of its own features there (elements, JS
  wiring, API calls), using existing CSS classes and no new styling. Chat B owns styling and layout, and restyles what
  Chat A adds. Pull right before editing `app.js` or `index.html`, and commit those edits in small pieces.
- **The API** (`/api/...` routes and their JSON) is the contract between the lanes. Never rename or remove a route or
  field the other side uses; add a new one instead.
- **Anything else in the other chat's files**: don't. Add a handoff (below) and carry on. A tiny edit is fine only
  when you can't finish without it. Keep it minimal and add a handoff line so the owner knows.

## Every task, in this order

1. Sync: `git pull --no-rebase origin claude/laughing-bell-3vt2c7`
2. Read this file: your status line, and the handoffs for you.
3. Set your status line to what you're doing now.
4. Work in your lane.
5. Test what you changed: TestClient for the API, a script run for agent code, a screenshot with mocked data for UI.
6. Log it: add a dated entry in your section of `Progress.md`, update your wiki pages, and add a line to your list at
   the bottom of `graphify-out/wiki/index.md`.
7. Commit with your tag first: `[A] Quiz: ...` or `[B] UI: ...`
8. Sync again (step 1). Fix any conflict, and re-test if code changed.
9. Push: `git push origin HEAD:claude/laughing-bell-3vt2c7`. If it's rejected because the other chat pushed first,
   repeat step 8, then push again.

Commit and push small pieces often. The other chat sees your work sooner, and conflicts stay small.

If a push is refused for permission (not because the other chat pushed first), push to your own session branch
instead and tell the user its name. Chat A then merges it into the shared branch.

## Shared files

Both chats write to these. Stay inside your own part:
- `TWO_CHATS.md`: your own status line, and new lines in the other chat's handoff list.
- `Progress.md`: only your own section at the end of the file. Add new entries just above your marker line.
- `graphify-out/wiki/index.md`: only your own list at the bottom, just above your marker line.
- `requirements.txt`, `README.md`, `.gitignore`: small additions only.

On a merge conflict in any of these files, keep both sides.

## Never

- Force-push, rebase or amend commits that are already pushed, or `git reset --hard` over the other chat's work.
- Push code that fails its tests or stops the app from starting.
- Reformat or reorganize files you don't own.
- Commit runtime files from `data/`, `logs/` or `models/`. They live on the user's PC.
- Change money or risk rules (`agent/config.py`, `agent/risk.py`) or enable real-money trading unless the user asks.

## Handoffs

To ask the other chat for something, add a line to its list: date, what you need, and why. The owner marks it done
with the commit hash.

### For Chat A (from Chat B)
- **Done (Chat A, 21a70ff):** all routes built with your shapes unchanged; history rows also carry `ticket`, orders carry `owner`, quote adds `spread` and `time`. Orders use magic 0 (owner "you").
  2026-09-24, from the user: **build the backend for the new Manual tab** (UI done by Chat B: `#tab-manual` in
  `index.html`, "manual trading" block in `app.js`). The user wants everything the MT5 mobile app does: one-click
  trading, market and pending orders, SL/TP edits, close all / all profitable / all losing, and so on. Today the tab
  already works for watching prices (`/api/bars`) and closing (`POST /api/positions/{ticket}/close`, looped for
  bulk closes). Everything else switches on by itself once these answer (a 404 on `/api/manual/quote` means "not
  built yet"). Suggested shapes (change them if you must, then note it here):
  - `GET /api/manual/quote?symbol=` → `{symbol, bid, ask, digits, point, volume_min, volume_max, volume_step,
    tick_value, tick_size, contract_size, stops_level, trade_allowed, day_high, day_low}` (the UI shows money at
    risk from `tick_value`/`tick_size`, and steps lots by `volume_step`).
  - `GET /api/manual/quotes?symbols=A,B,C` → `[{symbol, bid, ask, digits, point}]` for the Quotes list.
  - `POST /api/manual/order {symbol, side: "buy"|"sell", type: "market"|"limit"|"stop", volume, price?, sl?, tp?,
    deviation?, expiration?: "gtc"|"today", confirm_real?: true}` → `{ok, retcode, comment, ticket, price}`.
    Pending = buy/sell limit/stop at `price`. Please refuse a real account unless `confirm_real` is true (the UI sends
    it only after the user confirmed), check SL/TP are on the right side and outside `stops_level`, clamp volume to
    the symbol's limits, and use a magic of your choice so these show as "you" (or add an owner like "manual").
  - `POST /api/manual/close {tickets?: [..], volume?, filter?: "all"|"profit"|"loss"|"buys"|"sells", owner?:
    "any"|"you"|"bot"|"hermes", symbol?}` → `{closed: [{ticket, profit}], failed: [{ticket, comment}]}`. `volume`
    with one ticket = partial close (the ½ button). Bot positions closed here should land in the ledger as manual
    closes (your `sync_ledger` probably already does this).
  - `POST /api/manual/modify {ticket, sl, tp}` (0 = remove) → `{ok, retcode, comment}`; the BE button sends sl = open.
  - `GET /api/manual/orders` → `[{ticket, symbol, type: "buy_limit"|"sell_limit"|"buy_stop"|"sell_stop", volume,
    price, sl, tp, time_setup}]`; `POST /api/manual/orders/cancel {tickets?: [..], all?: true}` →
    `{cancelled: [..], failed: [..]}`.
  - `GET /api/manual/history?days=1` → `[{time, symbol, side, volume, open, close, profit, owner}]` (today's closed
    deals, newest first).
  - Nice to have: `mt5_service.account()` already gives balance/equity/margin/free margin/level, which the tab shows.

- **Done (Chat A, see the commit "[A] Trading bot learns from each losing trade"):** every losing close teaches it at once: a lesson, a 24 h caution for that setup + direction (with floors), the next Quiz build practises the chart, and the confidence rule can no longer block everything. UI fields: see the new line in your list below.
  2026-09-24, from the user: **make the model learn from each mistake.** Today `agent/learn.py` only writes lessons
  after 50 closed trades and every 50 after that. The user wants every losing trade (stop hit, wrong way, losing early
  exit) to teach it something right away. Ideas, yours to choose: update the lessons on every losing close; turn each
  losing trade's chart into a new Quiz question so the quiz agent practises it; keep a small "mistakes" record the
  entry filters read. Careful with over-blocking: with 154 random paper trades (sandbox test data) `learn.py` wrote
  `confidence ≥ 1`, which blocks every entry. Per-mistake updates need a floor so one bad day can't switch the bot off.
  If the UI needs to show it (for example a "Latest lesson" line on the Agent tab), add a field and note it here.
- 2026-09-24, FYI (small edit in your files, done by Chat B): `GET /api/bars` takes an optional `before` (unix time):
  only candles older than that. `mt5_service.m1_bars(symbol, count, before)` uses `mt5.copy_rates_from(..., before - 1,
  count)` when it's set; calls without it are unchanged. The chart uses it to load history as you scroll back.
  Change it however you like; just keep the parameter.

### For Chat B (from Chat A)
- 2026-09-24: Quiz tab has a new build shortfall line (`#quiz-build-note`, one `.build-note` rule in app.css using `--warn`). Restyle as you like; keep the id. **Done (4610c90): warn card, id kept.**
- 2026-09-24: Hermes tab needs a "Set up" button and clearer status (backend done by Chat A; I left `app/static/` alone
  since you're editing it). Why: when Ollama isn't installed/running or the model isn't downloaded, Hermes just fails.
  API, new fields only (old ones unchanged):
  - `GET /api/assistant/status` adds `local` (`ready` | `starting` | `downloading` | `not_installed` | `stopped` |
    `no_model` | `error`), `next_step` (a sentence to show the user, "" when ready), `download_pct` (0-1 while
    downloading, else null), `installing` (bool).
  - `POST /api/assistant/setup {}` installs Ollama with winget if missing, starts it, downloads the model. Returns the
    same status plus `note` (show it as a toast when non-empty).
  - Suggested UI: pill text by `local` (e.g. "Downloading 37%", "Ollama not installed"); `next_step` as a small line
    under the Hermes header; a "Set up" button when `local` is `not_installed` / `stopped` / `no_model` / `error` and
    not `installing`; poll status every 2 s while `downloading` / `starting` / `installing`. Chat replies starting
    with "⚠" are setup messages, so refresh the status after them. **Done (4610c90).**
- 2026-09-24: Hermes sleep + memory file (backend done by Chat A). Why: the user wants Hermes to shut down when they
  leave the Hermes tab (0 lingering) and keep the same memory.
  - When the user switches away from the Hermes tab, call `POST /api/assistant/sleep` (no body; returns
    `{unloaded: bool, reason?}`). It unloads the model from RAM/VRAM; the next message reloads it. Fire-and-forget.
  - Memory moved from `data/memory.db` to one plain file, `data/hermes_memory.json` (old one imported automatically).
    The Memory panel's line in `index.html` still says `data/memory.db`; please change it to `data/hermes_memory.json`.
  - `ollama_keep_alive` now defaults to `0` (unload right after each reply). If Settings shows that field, "0" means
    "unload right away". **Done (4610c90): sleep on leaving the tab, file name, label.**
- 2026-09-24: Hermes chat now runs `llama3.2:3b` on the CPU only (backend done by Chat A). The Hermes pill in
  `app.js` says `${s.model} on RTX 4060`; please use the new status field `device` ("CPU" or "GPU") instead, e.g.
  "llama3.2:3b on CPU". Settings has a new boolean `ollama_cpu_only` (default true) if you show Hermes settings. **Done: pill says "… on CPU"; switch in Settings.**
- 2026-09-24: Quiz question bank + no maximum (backend done by Chat A). Why: the user wants no cap, 10 question
  creators, and questions always being made and stored as markdown.
  - The Quiz number box: please remove its max (the API has none now) and offer "All" (send `questions: 0` = every
    usable question in the bank).
  - `GET /api/quiz/state` has a new `bank` object:
    - `stage`: text, e.g. "up to date: 28,595 questions ready", "question creators at work", "paused: the Build quiz
      button is using all 10 question creators".
    - `running`, `pct`.
    - `finders`: per half-year `{label, stage, pct}`.
    - `good` (usable questions), `questions` (found), `history` ("2009-01-02 to 2026-09-24"), `updated`.
    - `watcher`: bool, the always-on creator job.

    Suggested: a small line on the Quiz tab like "Question bank: 28,595 ready (2009–2026), always adding new ones",
    with the half-year bars while it works. **Done (0f1149b): no max + All chip, bank line + bars, both settings.**
  - Settings: `quiz_workers` label is now "question creators when Build quiz is pressed" (0 = up to 10; allow up to
    16). New boolean `quiz_bank_auto` ("keep making questions in the background", default on).
  - Build progress (`build`) works as before; the finder bars are now per half-year (e.g. "2016H2").
- 2026-09-24: Hermes web access is limited to trading/market sites (backend done by Chat A). New setting `web_sites`
  (a list of sites; "site/path" limits to a section, e.g. `reuters.com/markets`). If Settings shows Hermes options,
  please add it as an editable list with a line like "Hermes may only open these trading and market sites". **Done (0f1149b): one site per line in Settings > Hermes.**
- 2026-09-24: The bot learns from each losing trade (backend done by Chat A). `GET /api/progress` -> `learned` (and
  `/api/learn` -> `rules`) now also carries:
  - `latest_lesson`: one sentence, e.g. "Buy on 'Liquidity sweep below lows' at 14:32 UTC, confidence 0.30 hit its
    stop (-1.00R, -5.00). 3 of the last 7 buys on this setup lost. It now needs confidence of at least 0.32 there
    until 09-25 14:32 UTC (or a win)."
  - `latest_lesson_utc`, `mistakes` (count).
  - `cautions`: `[{side, setup, losses, min_prob, until, until_utc, why}]`.

  Suggested: a "Latest lesson" line on the Agent tab and the cautions as small chips. Skipped entries already show
  the reason in the agent's "say" feed ("learned from a recent loss: ..."). Quiz questions made from the bot's own
  losing trades carry a `bot` object (`{trade_id, side, pnl, r, exit, lesson, mode}`); you could badge them "your
  bot's trade" on the board or question view. The explanation text already says so.

## If only one chat is running

That chat may work in any lane. The git routine and the rules above still apply.
