---
name: m1-bot-lessons
description: What the user's MT5 M1 trading bot has learned from its own trades (paper, demo and real) - which hours, directions and confidence levels made or lost money, and the entry filters it now applies. Use this whenever the user asks how the bot is doing, why it skipped a trade, what it has learned, or whether it is ready to move up to demo or real money.
---

# M1 bot lessons (written by the bot)

No lessons yet. The bot rewrites this file itself (`agent/learn.py`) after its first 50 closed trades and every
50 after that, on each promotion, and when you press **Learn now** on the Agent tab.

It will list, from the bot's own ledger (`data/trades.db`):
- results by UTC hour, direction, model confidence, how trades closed, and stage (paper / demo / real);
- the entry filters it applies (`data/learned_rules.json`): losing hours to skip, a minimum confidence, or a side to stop trading.
  A group needs 20+ trades before it can create a rule, and at most 8 hours can be blocked.

Stage ladder (`agent/progression.py`): Paper (in the app) → Demo → Real · 2 open → Real · 5 open → Real · full.
Paper → Demo is automatic when the gate passes; every real-money step needs the user to type REAL; a drawdown breach
drops the bot back one stage.
