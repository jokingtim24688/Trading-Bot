# Two chats, one repo

Two Claude chats work on this project at the same time. This file says what each chat owns and how the two share
one branch without breaking each other's work. Read it at the start of every task.

- **Shared branch:** `claude/laughing-bell-3vt2c7`, the repo's default branch. Both chats commit and push here, and
  the user's PC pulls it. Your session may have been given its own `claude/...` branch: the user has approved pushing
  to the shared branch instead.
- **Map of the code:** `graphify-out/wiki/index.md`. Read it before you start; update it when you finish.
- **Names:** the user calls Chat A "chat 1" and Chat B "chat 2".
- **Who changes this file's rules:** only the user. When they change the split, update this file in one commit.

## Always on (from the user)

Both chats stay open all the time. Whenever the user sends anything, even one word like "go" or "check", start
with the routine: sync, read your status line and your handoff list, and do every open item for you first, then
the user's request. When your work needs something from the other lane (Chat B needs a backend route, Chat A needs
UI), don't wait and don't ask the user to pass it on: write the full spec into the other chat's handoff list (what,
why, routes, request and response shapes, ids) and carry on with what you can do. Mark items **Done** with the
commit hash. The user only has to say "go" to the other chat.

## Who does what

### Chat A (chat 1): Backend & Skills

Status: idle. Last: app-written skill files untracked so updates never block (2026-09-24).

Owns what the app does:
- `agent/`: trading agent, Quiz school, replay, history, learning, risk and money rules
- `mcp_server/`, `hermes/`
- `app/server.py` (the API), `app/jobs.py`, `app/mt5_service.py`, `app/settings.py`,
  `app/brain.py`, `app/memory.py`, `app/tools.py`
- `.claude/skills/`, `.claude/agents/`: Chat A makes and edits skills. The app-written skill files are git-ignored
  (so they can't block updates). Some skill folders are written by the app on
  the user's PC (`m1-bot-lessons/` by `agent/learn.py`, `quiz-lessons/` by `agent/quiz.py`, `quiz-weak-spots/` by
  `agent/quiz_report.py`). Don't hand-edit those, except the `claude-*.md` pages in `quiz-weak-spots/`.
- Wiki pages: `agent.md`, `hermes.md`, `mcp.md`, `skill.md`, and the server/jobs/settings bullets of `app.md`

### Chat B (chat 2): UI & Polish

Status: idle. Last (2026-09-24): Keys page, Sounds page (your own sounds via /api/sounds), custom top-right
notifications in the app and on screen, speed pass (hidden-window polling, shared positions, no timer throttling).

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
   Then run the whole suite: `python -m pytest -q` (fake MT5, throw-away data folder, ~5 s). It must pass before a
   push. GitHub runs it on every push too (`.github/workflows/tests.yml`). Chat A adds tests for new backend code in
   `tests/`.
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
- **Done (Chat A, 9cb15fd):** `desktop_alerts` now defaults to false; settings v7 turns it off once in existing settings files, and after that it stays however the user sets it.
  2026-09-24, from the user: **notifications must be custom and sit at the top right of the screen** (several at
  once, newest below the others, each fading after 1.2 s). Windows' own toasts can't be moved or styled, so the window
  now shows its own: in the app at the top right, and, when the app isn't in front, in a small always-on-top window at
  the top right of the screen (`app/main.py` + `app/static/notify.html`, my files). Please set **`desktop_alerts`
  default to `false`** (keep the setting; I label it "Also show Windows' own pop-up") so people don't get every
  TP/SL twice. Nothing else is needed; the window reads `/api/events` as before.
- **Done (Chat A, 6f1c9e3):** at most once per 2 s. The Close button and the watcher (bot position gone) mark it stale so the next poll syncs; kill and bulk close force it. 10 polls in a burst = 1 sync.
  2026-09-24, from the user ("make everything as optimised as it can be"): **throttle `sync_bot_ledger()` in the app
  server.** `bot_trades_payload()` runs it on every `/api/bot/trades` call, and the window asks every 2 s (plus the
  calendar and Review loads, while the agent already syncs every 1 s itself), so the same MT5 history lookups run over
  and over. Suggested: skip it when the last run was under ~2 s ago (a module-level timestamp), and keep the Close
  button path forcing a fresh sync. On my side the window now pauses or slows its polling while it's minimised, and
  shares one positions request between the Market and Manual tabs.
- **Done (Chat A, c071ee7):** `keybinds` / `sounds` settings (dicts, carried by backup/restore) and the `/api/sounds` routes, with your shapes. Errors: 413 over 5 MB, 415 not audio, 400 bad base64 or blank name, 404 unknown id.
  2026-09-24, from the user: **a Keybinds page and a Sounds page** (Chat B is building both now). They already work on
  this PC from the window's own storage; these make them survive anything and ride along in Settings backups.
  1. Two new settings whose values are objects the UI owns; the server only stores them: `keybinds` (default `{}`) and
     `sounds` (default `{}`). Please add both to `DEFAULTS`, and make `check()` accept a dict when the default is a
     dict (reject anything else) so backup/restore carries them. `POST /api/settings {"keybinds": {...}}` already
     merges a partial body, so nothing else is needed. For reference only:
     `keybinds = {"bindings": {"man.buy": "B", "tab.review": "4", ...}, "groups": {"app": true, "manual": false}}`,
     `sounds = {"master": {"volume": 0.8, "mute": false, "gap": 0.45, "quiet": {"on": false, "from": "23:00",
     "to": "07:00"}}, "events": {"profit": {"on": true, "sound": "bell", "pitch": 0, "volume": 0.8, "tone": 1,
     "length": 1}, ...}}` (`sound` is a built-in name or `"custom:<id>"`).
  2. The user's own sound files (they want to add sounds and pick one per event):
     - `GET /api/sounds` -> `[{id, name, type, size, added, url}]`, newest first.
     - `POST /api/sounds {name, type, data}` (`data` = the file as base64, so no python-multipart dependency) -> the
       new row. Accept wav, mp3, ogg, m4a/aac, flac and webm audio; at most 5 MB decoded (413 if bigger, 415 for
       anything else). Save as `data/sounds/<id>.<ext>`; `id` = a short slug of the name plus 6 hex characters.
     - `GET /api/sounds/{id}` -> the file with its content type (`url` points here).
     - `POST /api/sounds/{id}/rename {name}` -> the row; `DELETE /api/sounds/{id}` -> `{ok: true}`.
     Until these answer, the UI keeps added sounds in the window's storage and moves them to the server by itself once
     `GET /api/sounds` works.
  3. FYI, my files: `app/main.py` now starts the window with `private_mode=False` and `storage_path=data/webview`.
     pywebview's default private mode wiped everything the window stored at every restart (one-click, TP/SL points,
     reduce motion, the setup checklist's "seen", keys on). `data/` is already gitignored.
  4. FYI: `alert_sound` stays in settings, but Settings > Trading no longer shows it; the Sounds page takes over (if
     it's false, the Sounds page starts muted, once).
- **Done (Chat A, ad46cc9):** setting `desktop_alerts` (bool, default true). Every TP/SL hit in the events feed pops up a silent Windows notification (any owner).
  2026-09-24, from Chat B (couldn't do it in the cloud): **Windows pop-up notifications** when a take profit or stop
  loss is hit, so the user sees them with the app minimised or behind other windows. The in-app card, sound and window
  title already work (UI polls `/api/events`). Idea: when the events feed records `tp`/`sl`, the server shows a
  Windows toast (e.g. `winotify` or `plyer`, Windows only, skipped elsewhere), behind a new setting
  `desktop_alerts` (default on). Tell me the setting name and I'll add the switch to Settings > Manual trading.
- **Done (Chat A, aaff90b):** all 8 backend pieces built with your shapes; small additions and two differences are in your list (For Chat B).
  2026-09-24, from the user: **backend for 11 new features** (Chat B is building all the UI at the same time; every
  panel shows "waiting for its backend" until your route answers, so build in any order and push each piece as it's
  done). Numbers match the user's list. Items 1, 4 and 5 need nothing from you.
  - **1. Real-account guard** (UI only): keep refusing real-account orders without `confirm_real`, as now.
  - **3. Connection status:** `GET /api/manual/quote` adds `connected` (terminal connected to the broker),
    `tick_age` (seconds since the symbol's last tick, worked out on the server so the broker's time offset can't skew
    it), `market_open` (bool, from the symbol's trade sessions or "no tick for 120 s on a weekend"). The UI greys out
    Buy/Sell when `!connected` or `tick_age > 10`.
  - **4. Drag SL/TP on the chart** (UI only): uses `POST /api/manual/modify`.
  - **5. Keyboard shortcuts** (UI only).
  - **6. Trailing stop + auto break-even** (must run in the app's backend, not the page, so it works with the tab
    closed): a 1 s loop over positions with a rule.
    - Settings: `manual_be_points` (0 = off; e.g. 80: once a trade is 80 points up, move SL to entry + 2 points),
      `manual_trail_points` (0 = off; SL follows price at this distance, only ever tightening). Applied to new manual
      orders (magic 0) by default.
    - `POST /api/manual/order` accepts optional `be_points` / `trail_points` (override the defaults for that order).
    - `POST /api/manual/auto {ticket, be_points?, trail_points?}` sets/clears (0) the rule for one open position
      (any owner, but warn in `comment` if it's the bot's); `GET /api/manual/auto` -> `{defaults: {be_points,
      trail_points}, tickets: {"<ticket>": {be_points, trail_points, be_done: bool, sl}}}`. Forget closed tickets.
  - **7. Alerts when TP/SL is hit:** `GET /api/events?since=<id>` -> `{last_id, events: [{id, time, kind:
    "tp"|"sl"|"close"|"open"|"be"|"trail", ticket, symbol, side, volume, price, profit, owner}]}` for every owner
    (you, bot, hermes), from MT5 deal `reason` (DEAL_REASON_TP / _SL / others = close) plus your own "be"/"trail"
    moves from item 6. `since` omitted = just return `last_id` (so the first poll doesn't replay old events). Keep the
    last ~500 in memory. The UI polls it every 3 s on every tab and plays a sound + toast.
  - **8. You vs the bot:** `GET /api/stats/compare?days=30` (0 = all) -> `{you: S, bot: S}` where S = `{trades, wins,
    losses, win_rate, net, avg_win, avg_loss, profit_factor, expectancy, best_trade, worst_trade, avg_hold_min,
    by_hour: [{hour 0-23 server time, trades, net}], by_weekday: [{day 0-6, trades, net}], curve: [{time, cum}]}`.
    "you" = closed manual deals (magic 0), "bot" = ledger trades in the current mode (accept `mode=paper|live|all`).
  - **9. Trade replay from History:** `GET /api/manual/history` rows add `open_time`, `sl`, `tp`, `reason`
    ("tp"|"sl"|"manual"|"so"), `duration_s`; allow `days` up to 90. The bot's ledger rows already have entry/exit
    times; please make sure `/api/bot/trades` rows carry `entry_time`, `exit_time`, `entry`, `exit`, `sl`, `tp` under
    those names (tell me if they differ). The chart then jumps to the trade with `/api/bars?before=`.
  - **10. Weekly summary from Hermes:** `GET /api/review/weekly?week=2026-W39` (omitted = last full week) ->
    `{week, from, to, generated_utc, source: "hermes"|"rules", went_well: [..], fix: [..], numbers: {you: S-lite,
    bot: S-lite}}` (3–5 short sentences per list; S-lite = trades, win_rate, net, profit_factor). Built from both
    item-8 stats, the bot's lessons/mistakes and the calendar. `POST /api/review/weekly {week}` makes it again (Hermes
    if it's up, rule-based text otherwise; fine as a job). Store in `data/reviews/2026-W39.json`, make one
    automatically once a week. `GET /api/review/weeks` -> list of stored weeks, newest first.
  - **12. Settings backup:** `POST /api/settings/backup` -> `{name, path}` (writes
    `data/backups/settings-YYYYMMDD-HHMM.json`); `GET /api/settings/backups` -> `[{name, time, size}]`, newest first;
    `POST /api/settings/restore {name}` or `{settings: {...}}` (from a file the user picked) -> `{ok, changed: [keys],
    ignored: [unknown keys], backup: name}` (always back up the current settings first; validate like
    `POST /api/settings`). The window can't download files, so the backend writes them.
  - **13. First-run checklist:** `GET /api/setup/checklist` -> `{done: n, total: n, items: [{id, label, ok, detail,
    action}]}` with ids `mt5` (terminal connected), `account` (logged in; detail "demo"/"real"), `data` (M1 parquet
    for the symbol), `history` (extra years downloaded, optional), `model` (trained model file), `hermes` (local
    `ready`), `mcp` (bridge running), `quiz` (bank has questions, optional). `action` = the existing route that fixes
    it (e.g. "/api/fetch", "/api/train", "/api/assistant/setup", "/api/mcp/start") or null. Add `optional: true` where
    it applies.
- **Done (Chat A, e7184e7):** market orders re-anchor SL/TP to the position's open price right after the fill; pending orders use the order price. The reply now has `sl`, `tp` (final), `price` (fill), `anchored`, and `note` when the move was refused (see For Chat B).
  2026-09-24, from the user: the Manual tab's take profit is always 160 points above and the stop loss 80 points below
  the price (editable in the ticket, flipped for sells). The UI sends `sl`/`tp` prices worked out from the quote at
  the click, plus `sl_points` and `tp_points`. Please use the points when they're there to anchor SL/TP to the real
  fill price of market orders (buy: fill − sl_points×point / fill + tp_points×point; sell the other way round), and to
  the order price for pending orders, so slippage can't shift them. Why: the user wants exactly 160/80 every time.
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

- **Done (Chat A, 1dafd69):** every losing close teaches it at once: a lesson, a 24 h caution for that setup + direction (with floors), the next Quiz build practises the chart, and the confidence rule can no longer block everything. UI fields: see the new line in your list below.
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
- 2026-09-25: Quiz tab Weak spots panel. Each group in `/api/quiz/report` (`groups[]` and `weak[]`) now has
  `grind` (false for trap groups). Please hide or disable the **Work on these** button where `grind` is false, with a
  small hint like "traps look like winners at entry; training on them only memorises". Why: the user kept getting
  "Work on these" for trap groups, which memorises charts and pushed the exam down before
  (`claude-exam-collapse-forgetting`). The report now lists real setups first, with at most 2 trap spots.
- 2026-09-24, from the user ("fix the mcp bridge"). **FYI, small edit in your file:** `app/main.py` now starts the
  bridge with `bridge.start(port)` in a background thread instead of `jobs.start("mcp", ...)`. It replaces a
  leftover bridge from an earlier session, which used to hold the port so the new one died silently. Keep that call
  if you touch it. `POST /api/mcp/start` now returns 500 `{detail}` with the real reason (your `api()` already shows
  `detail`). New `GET /api/mcp/status` -> `{running, port, ours, error?}`. The checklist's mcp `detail` carries the
  error.
- 2026-09-24, from the user, with a screenshot of the Manual chart holding 5 sells: "instead of this clunky design simply
  put the small sl and tp and instead of a big banner a small dot for where i bought they can overlap and also the
  notifications weren't working".
  **1. Chart markers (Manual chart, and the Market chart's bot trades if they use the same style):**
  - Remove the big gold "you sell 0.1" price-line banners, one per position, which stack into a wall.
  - Entry = a **small dot** where the trade opened: a candle marker at the open time and price (e.g. `setMarkers`
    `shape: "circle"`, small, green for buys and red for sells, no text; or a small canvas dot on `#chart-layer`).
    Dots may overlap.
  - SL / TP = **thin lines with just a small "SL" / "TP" axis tag** (1 px, dotted or low opacity, red / green). No
    per-position price label in the tag. Positions sharing a level may overlap; don't stack five labels.
  - Keep drag-to-move for SL/TP working on the thin lines. Hover (or selecting a position in the table) can show
    the details the banner used to show: side, lots, P/L.
  **2. Notifications "weren't working":** the user had just updated from an old copy (see the update fix), so it may
  have been the old version. The events feed passes its tests on a fake MT5. From my commit after this item,
  `logs/app.log` prints `(event #N kind ticket ...)` for every event the backend creates, so a missing notification
  can be traced to backend or UI. Please check the UI side on a real setup: `pollEvents` stops for good once it gets a
  404 (`alertsState.ok = false`), e.g. while an older server was still running. Consider retrying every ~30 s instead.
  Also check the screen pop-up window path (`pop.feed`) when the main window is in front vs behind. The user hasn't
  said which notifications failed: in-app cards, the screen pop-up, or opens / closes. Ask them if you can.
- 2026-09-24, from the user ("even with the auto update app im still on the old version"). **FYI, small edit in your
  file:** `Trading Bot.bat` now runs `".venv\Scripts\python.exe" -m app.update` instead of the silent `git pull
  --ff-only`, and everything from the update to `exit` is one `( ... )` block (cmd parses it once, so an update that
  rewrites the .bat can't garble the run; keep `)` out of `rem` lines inside it). Change it however you like; just
  keep the update step and the block.
  **UI, please:** `GET /api/status` has `version: {commit, date, branch, update: {checked, ok, updated, before,
  after, message, notes: [..]} | null}`. Show "Version <commit> · <date>" in Settings (and maybe the top bar tooltip),
  plus `update.message` (a warning style when `ok` is false) and any `notes`. Why: the user had no way to tell they
  were on an old version.
- 2026-09-24, from the user ("perfect except please make the notifications fade away in .9 seconds instead of
  immediately going away"): **notifications fade out over 0.9 s**, both the in-app cards (`#notes`) and the
  screen pop-up window (`app/static/notify.html`). What I found:
  - `app.css:856` `.note.out { animation: note-out .3s ... }` and `notify.html:27` `.note.out { animation: out .3s ... }`
    both use 0.3 s, which looks instant. Make them 0.9 s (an ease-out opacity fade; keep the small slide if you like).
  - `removeNote` in `app.js:53` gives up after `setTimeout(finish, 450)`, which would cut a 0.9 s fade short. Raise it
    to ~1100 ms (and the same in notify.html's `out()` if it has a timer).
  - Reduced motion (`.reduce-motion` / `prefers-reduced-motion`, `app.css:860-862`, and `motionOK()` in `removeNote`)
    removes cards instantly. The user may have that on (the app setting or Windows' "Animation effects" off). An
    opacity-only fade isn't motion, so please keep a 0.9 s opacity fade there too (just no slide or glide).
  - The time a card stays up before fading (`noteSecs`, default 2 s) stays as it is. **Done (Chat B, 55b0655): 0.9 s fade in both; the real culprit was the timer line's animationend ending the fade at once; reduced motion keeps an opacity fade.**
- 2026-09-24, FYI: there is now a test suite. Run `python -m pytest -q` before you push (routine step 5). It only covers the backend, so it needs nothing from you, and it passes in ~5 s. **Done (Chat B): run before every push; 26 passed at 55b0655.**
- 2026-09-24, from the user (recommendations, part 3): **honest backtest**. `POST /api/backtest/start {commission?,
  slippage?}` -> `{started, commission, slippage}` (409 while one runs); `POST /api/backtest/stop`; `GET /api/backtest`
  -> `{running, progress: {index, total, bar_time_utc, opened} | null, report: null | {generated_utc, period: {from,
  to}, costs: {commission_per_lot, slippage_points}, metrics: {trades, win_rate, net, profit_factor, expectancy,
  score, max_drawdown_pct, days, trades_per_day, stop_hits, return_pct, months: [{month, trades, net}]}, gate: [{id,
  label, value, need, ok}], passed, verdict}, log}`. Suggested: a "Backtest before going live" card on the Agent tab
  near the stage ladder: Run button, progress bar, verdict line, the gate lines with ticks, the monthly nets. Settings
  `backtest_commission` (money per lot) and `backtest_slippage` (points). **Done (Chat B, 55b0655): card on the Agent tab + the two settings.**
- 2026-09-24, from the user (recommendations, part 2):
  - **Watchdog events:** the `/api/events` feed has new kinds `agent_restart`, `agent_failed`, `agent_stuck`,
    `mt5_down`, `mt5_up`, and every event now has a `message` field (a ready sentence for these kinds, null for
    trade events). Please show them as pop-ups (warning style for failed / stuck / down). `GET /api/watchdog` ->
    `{restarts_last_hour, gave_up, stuck, mt5_down, error}`. Telegram events add `watchdog` (a checkbox in your
    Telegram section).
  - **Trade notes:** `GET /api/manual/notes` -> `{"<ticket>": {note, tags, time}}`; `POST /api/manual/notes {ticket,
    note, tags}` (empty note and no tags removes it). `POST /api/manual/order` accepts `note` and `tags` (so the
    ticket could have an optional "Why?" field), and `/api/manual/history` rows carry `note` and `tags`.
  - **Data backup:** `GET /api/backup/data` -> `{folder, daily, keep, backups: [{name, time, size, path}], error}`;
    `POST /api/backup/data` -> `{name, path, size, files}`. Settings `backup_daily` (bool), `backup_dir` (text, blank
    = data/backups/full), `backup_keep` (number). Next to the settings backup would fit. **Done (Chat B, 55b0655): watchdog pop-ups + line + sound + Telegram box, trade notes (ticket, positions, history, replay), full data backup in Settings > Backup.**
- 2026-09-24, from the user (recommendations): three new backend pieces for the UI:
  - **News:** `GET /api/news` -> `{enabled, before_min, after_min, currencies, impact, paused (sentence or null),
    events: [{time, utc, title, currency, impact, forecast, previous}], fetched, stale, error}`. Suggested: a small
    "News in 12 min: CPI" chip in the top bar or Manual tab, a "Bot paused for news" line on the Agent tab when
    `paused`, and settings for `news_pause` (switch), `news_before_min`, `news_after_min`, `news_impact` (High /
    Medium / Low checkboxes).
  - **Manual spread limit:** the quote adds `max_spread` and `spread_ok`. A market order with a wider spread gets 400
    `{error: "The spread is 25 points right now (your limit is 20)..."}`; offer "Send anyway", which resends with
    `ignore_spread: true`. Setting `manual_max_spread` (points, 0 = no limit).
  - **Is the quiz agent worth it?** `GET /api/stats/quiz?days=0&mode=all` -> `{agree, disagree, none: {trades,
    win_rate, net, profit_factor, expectancy}, verdict}`. Good next to the quiz filter switch, or on the Review tab. **Done (Chat B, 483d19c): news chip + Agent line + News pause settings, spread limit with a send-anyway click, quiz panel on Review + verdict under the quiz filter.**
- 2026-09-24, from the user: **Telegram alerts** (backend done, commit d68e93f). Please add a "Phone alerts
  (Telegram)" section in Settings:
  - switch `telegram_enabled`; a password-style field `telegram_token` (with the hint "In Telegram, message
    @BotFather, send /newbot, paste the token here");
  - a "Find my chat" button: `POST /api/telegram/detect` -> `{ok, chat_id, name}` or `{error}`. Show "Connected to
    <name>" and say "send your bot a message first" before it;
  - a "Send test" button: `POST /api/telegram/test` -> `{ok}` or `{error}`;
  - checkboxes for `telegram_events` (tp, sl, open, close, be, trail; default the first four).
  - `GET /api/telegram/status` -> `{enabled, token_set, chat_set, events, sent, error}`; show `error` if set.
    Errors come as HTTP 400 `{error}`. **Done (Chat B, 483d19c): Settings > Phone alerts with all of it.**
- 2026-09-24: `/api/sounds` is live (commit c071ee7), shapes as you specced. Notes: `type` in rows is the real type found from the file (e.g. `audio/mpeg`), not the one sent. `data` may also be a full `data:audio/...;base64,` URL. Rows added in the same second keep no set order. Errors come as `{detail}`. **Done (Chat B): Sounds page uses it (add, play, rename, delete, use for).**
- 2026-09-24: Windows pop-ups are live. The setting name is **`desktop_alerts`** (bool, default true), for Settings > Manual trading, e.g. "Windows pop-up when a TP or SL is hit". Nothing else is needed from the UI. **Done (Chat B): switch on the Sounds page > Notifications ("Also show Windows' own pop-up").**
- 2026-09-24: the Hermes tab now starts the real **Hermes Agent** app (`hermes gateway` in WSL) by itself and uses it when
  it's installed; the small local model is only the fallback. `GET /api/assistant/status` adds `agent` (`ready` |
  `starting` | `stopped` | `not_installed` | `error` | `off`) and `agent_step` (a sentence, "" when ready). Chat replies
  already carry `backend` (`hermes_agent` | `local`). Suggested UI: a small "Hermes Agent" / "Local model" tag on each
  reply or in the header, `agent_step` under the header when not ready, and a longer "thinking" state (agent tasks
  can take minutes). The Set up button now also (re)starts Hermes Agent. New settings, if you want them in
  Settings → Hermes: `hermes_agent_autostart` (bool), `hermes_agent_cmd` (text, default "hermes gateway"),
  `hermes_wsl_distro` (text, blank = default). **Done (Chat B): "Hermes Agent" / "Local model" tag in the header and on each reply, `agent_step` line, Set up for a stopped agent, a still-working timer, the 3 settings in Settings → Hermes.**
- 2026-09-24: **the 11 features' backend is live** (commit aaff90b). Everything follows your spec; notes:
  - `POST /api/review/weekly {week}` rebuilds in the background and returns `{week, working: true}`. `GET` returns
    the stored review plus `working` (true while a rebuild runs; poll every 2 s until false). A week with no review
    yet is made on the spot with rule-based text. Weeks look like `2026-W39`; bad ones give 400.
  - `POST /api/manual/order` replies add `auto` (`{be_points, trail_points, be_done, sl}` or null).
    `GET /api/manual/auto` ticket rows also carry `sl` (the current stop). `POST /api/manual/auto` returns
    `{ok, ticket, be_points, trail_points, comment}`.
  - Events: `time` is this PC's unix time. Kinds are exactly open / tp / sl / close / be / trail. For be / trail,
    `price` is the new stop.
  - `/api/stats/compare` also returns `from`, `to` and `bot_modes`; `profit_factor` is null when there are no losses
    yet. Bad `mode` gives 400.
  - `/api/bot/trades` rows now carry `entry_time` / `exit_time` (server-time epochs, the same clock as `/api/bars`),
    next to the existing `entry`, `exit`, `sl`, `tp`.
  - `/api/manual/history` `reason` is tp / sl / manual / so. SL/TP are the last ones the app saw, else the opening
    ones, else 0.
  - Checklist rows have `action: null` once `ok`. `quiz` has no route (the bank fills itself).
  - Settings `manual_be_points` / `manual_trail_points` (default 0) are new; they go in the Settings tab when you like. **Done (Chat B): UI for all 11 on these routes, tested against them.**
- 2026-09-24: `POST /api/manual/order` replies now carry `sl`, `tp` (the levels actually set), `price` (the real
  fill), `anchored` (true when sl_points/tp_points were used) and, rarely, `note` (the SL/TP couldn't be moved to
  the fill because the price already ran past it, so the quote's levels stayed). Why: the user wants exactly 160/80
  from the fill. Suggested UI: show `note` as a warning toast; the order toast can quote the final SL/TP. **Done (Chat B): the order toast quotes the final TP/SL; a `note` turns it into a warning.**
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
  bot's trade" on the board or question view. The explanation text already says so. **Done: Latest lesson box + caution chips on the Agent tab, "your bot's trade" badge in the question view (33bcaa3).**

## If only one chat is running

That chat may work in any lane. The git routine and the rules above still apply.
