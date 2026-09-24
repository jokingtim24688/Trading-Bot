# Holiday-thin markets: early January (written by Claude from the 2026-09-24 report)

## What the report showed
The "hardest" example questions in the trap weak spots cluster in the first half of January, across many years:
2010-01-08, 2010-01-18, 2012-01-10, 2014-01-13, 2015-01-06 (twice), 2018-01-31, 2019-01-08, 2020-01-13, 2021-01-04,
2022-01-31, 2024-01-15 and 2026-01-06. Several were answered hundreds of times with only ~5% right (e.g. Q10653:
523/9,592).

## Why
- Late December and the first trading days of January are **holiday-thin**: banks and funds are away and volume is
  low. The first Friday of January also brings the NFP report.
- Price makes sharp moves that don't follow through, which is exactly what makes a setup a trap. See
  claude-traps-quiet-markets.md.
- These questions are also near-contradictions for the agent: a January sweep looks like any other sweep, but
  resolves differently.

## How to use this
- Treat roughly 20 Dec – 10 Jan as a **no-trade window** for the live bot, and distrust the quiz agent's answers
  there. The weak-spot report now checks month bunching and will flag it if the misses concentrate in a month.
- Possible builder change: leave that window out of the quiz entirely, or label setups there as "stay out". Not done
  automatically yet; ask Claude if you want it.
- Also treat single-day patterns in small groups (e.g. "50% on a Tuesday" from 12 questions) as chance. The report
  now flags groups under 30 questions.
