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

Status: idle. Last: quiz builds no longer stop near 18k questions (2026-09-24).

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

Status: design review done (see Progress.md); waiting for the user to pick the first changes.

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
- (none yet)

### For Chat B (from Chat A)
- 2026-09-24: Quiz tab has a new build shortfall line (`#quiz-build-note`, one `.build-note` rule in app.css using `--warn`). Restyle as you like; keep the id.

## If only one chat is running

That chat may work in any lane. The git routine and the rules above still apply.
