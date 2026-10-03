# Setups that don't pay on their own (written by Claude from the 2026-10-03 03:33 report)

## What the report showed
- "Reclaimed session average" was flagged as **impossible to tell apart on the chart**: its 1,249 traps and 362
  winners differ by at most 0.25 standard deviations on every measure.
- "Lost session average" is the weakest real setup (50% right), and its trap check also found no clear difference.
- In your quiz, Reclaimed session average has **3.4 quick traps for every clean winner**.

## What Claude checked
Every time each setup appears in the history, taken the quiz's way (its stop, 2R target, 4 hours), measured with the
quiz's own setup finder and outcome code. This ran on the sandbox's 4-year stand-in history (2021–2024, 2.0M M1
candles). That history is synthetic, not real gold, so it shows the method rather than your numbers.

| | Hit 2R | Stop first | Clean winner : quick trap |
|---|---|---|---|
| Random entries, same stop and target | 29–30% | 70% | – |
| Reclaimed session average | 28% | 72% | 1 : 3.9 |
| Every other setup | 28–31% | 69–72% | about 1 : 3.6 |
| Break-even at 2R | 33% | | |

On data with no edge in it, every setup lands exactly on the random-entry rate. Even so, the quiz still found
thousands of "clean winners" for each one. **The quiz's winners are picked with hindsight, so they exist whether or
not the setup has an edge.** Your real quiz shows the same 1 : 3.4 shape for Reclaimed session average. That's what a
setup with no edge looks like.

## Your real history (report 2026-10-03 16:57, 2009–2026)
The edge check ran on your PC over the full real gold history: about 1.04 million setups.

| | Hit 2R | ≈ R a trade |
|---|---|---|
| 16 of 18 setups ("loses on its own") | 28–30% | −0.10 to −0.17 |
| Testing prior-day high / low (580–640 found) | 31% / 34% | −0.07 / +0.01, can't tell yet |
| Break-even | 33% | 0 |

**None of the 18 setups pays when taken the quiz's way** (1.5 ATR stop, 2R target, 4 hours, spread included). They
land on the same 28–30% as random entries. The two prior-day tests are too rare to call. This matches the
earlier 22-year study: intraday M1 entries on gold have no edge after costs.

What it means:
- The quiz teaches *recognising* setups, which it does well (fades 98% finished), not *making money* from them.
- Its STAY OUT "mistakes" on real setups are the money-correct answer (see claude-stay-out-bias.md).
- Don't use the quiz's BUY or SELL second opinion as a reason to take a live trade.
- Since this report, weak spots on a losing setup no longer suggest "Work on these" or "the pro answer is BUY". Drilling
  them would teach it to take losing trades.

## Why the quiz can't learn it
- A question is a winner if price reached 2R cleanly *afterwards*, and a trap if the stop was hit within the hour.
  When the setup has no edge, which one happens is close to a coin flip. Nothing on the chart at entry can tell them
  apart, because there's nothing to tell.
- The quiz keeps only clean winners and quick traps, and makes winners about 61% of its questions. Inside the quiz,
  setups look like they win 3 times in 4; in the market, it's closer to 1 in 4.
- The session-average setups are the most extreme case: the cross of a running average happens constantly in chop.

## What changed
- The weak-spot report now has a section **"Do the setups pay on their own?"** (`quiz_report.edge_check`). It covers
  every setup the question creators found in *your* history (2009–2026 on your PC): how often it was found, its hit
  rate, how often the stop came first, clean winners vs quick traps, about how many R it makes per trade, and a verdict.
  - Each verdict accounts for sample size: "loses on its own" or "pays on its own" only when the result is more than
    2 standard errors from zero. Otherwise it says "can't tell yet".
- When a weak spot is a setup that loses on its own, its first suggested fix now says so. The agent's STAY OUT is
  the money-safe answer there.
- "Setups that lose on their own" is listed under "For Claude".

## What to do
- Read the edge table in the next report (it uses your real history). Don't let the live bot take a setup marked
  "loses on its own" just because it appeared. The quiz's BUY or SELL answer on that setup is hindsight.
- This matches the earlier 22-year study (ea/research/README.md): intraday M1 setups on gold had no edge after costs;
  only slow daily trend-following did.
- Treat Reclaimed session average and Lost session average as no-trade setups until the edge table shows them
  paying. If they stay near break-even, Claude can take them out of the quiz, or make them stay-out questions.
