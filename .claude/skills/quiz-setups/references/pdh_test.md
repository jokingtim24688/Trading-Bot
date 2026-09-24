# Testing prior-day high

**Right answer when it works: SELL.** When the same setup failed fast (its stop was hit within 60
minutes), the question is a trap and the right answer is **STAY OUT** (see traps.md).

## What the question shows
Price came up to **within 0.4 ATR below yesterday's high** (it was more than 0.8 ATR below it 3 candles earlier) and printed a down candle.

Questions are only asked between 10:00 and 20:00 server time (London open to late New York).

## Why pros take it
A first test of yesterday's high that is sold shows sellers defending it.

## The trade the quiz checks
- Entry: the question candle's close (plus the spread on a buy).
- Stop: 1.5 ATR from the entry.
- Target: 2R (twice the stop distance).
- It counts as a clean pro win only if the target is hit within 3 hours without first going more
  than 60% of the way to the stop. Messy winners are left out of the quiz.

## When it turns into a trap
- Repeated tests of the high.
- A strong H1 uptrend: the high is likely to break.
- Quiet market: ATR at or below its usual, small candles (the report's biggest trap pattern; see quiz-weak-spots/references/claude-traps-quiet-markets.md).
- Holiday-thin weeks (about 20 Dec - 10 Jan; see claude-holiday-thin-january.md).
- Scheduled news (NFP, CPI, FOMC). The agent has no news input yet, so treat its answers near news as a coin flip.

## What the agent sees
`pdh_dist`, `body`, `h1_structure`, `day_range_pos`, `atr_rel`. All 49 indicator inputs and the 178 chart inputs go in; these are the ones that matter most here.

## If the agent is stuck on this setup
1. Let it loop: a missed question's retries are answered on its section-mates (the 5 closest look-alikes of this
   setup with the same answer), so it learns the pattern, not one chart.
2. Read the weak-spot report (Quiz tab -> Weak spots); if this setup's traps look like its winners, no chart-only
   agent can split them. Treat its answers on this setup as a coin flip and ask Claude to add the missing input.
3. Pick the stuck squares -> Work on picked, then Continue (the memory check repairs any forgetting).
