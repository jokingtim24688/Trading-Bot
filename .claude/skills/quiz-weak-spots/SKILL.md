---
name: quiz-weak-spots
description: Where the Trading Bot's quiz agent gets stuck - the setups and situations it keeps getting wrong, what those charts have in common (time of day, volatility, H1 trend, chasing, levels), whether the chart can separate traps from winners, and what to do about each. Rewritten automatically by the quiz; pages named claude-*.md are written by Claude from the pasted report. Use this whenever the user asks why the quiz agent fails, what it is stuck on, which setups or situations to distrust, or how to improve the quiz.
---

# Quiz weak spots

No weak-spot report yet. The quiz writes one every 5 minutes while it runs and after every run (`agent/quiz_report.py`).
Once it exists, this file lists the weak spots with a page per spot in `references/`:
- what the charts it misses have in common;
- whether traps can be told apart from winners on the chart at all;
- a suggested fix.

Pages named `claude-*.md` are written by Claude after the user pastes the report ("Copy report for Claude" on the Quiz
tab). They are never overwritten by the automatic report.

## Notes written by Claude (from the first real report, 2026-09-24)
- [claude-exam-collapse-forgetting.md](references/claude-exam-collapse-forgetting.md): the exam fell to 24% because
  it forgot (finished questions were never re-checked). Now handled by the honest finish rule, the memory check and
  the silent refresher. Judge it by the exam, not the board.
- [claude-traps-quiet-markets.md](references/claude-traps-quiet-markets.md): traps are setups in quiet, small-candle
  markets. Spread/ATR and round-number distance were the same signal. Distrust its answers in quiet markets.
- [claude-holiday-thin-january.md](references/claude-holiday-thin-january.md): the hardest questions cluster in early
  January (holiday-thin). Treat ~20 Dec to 10 Jan as no-trade.

