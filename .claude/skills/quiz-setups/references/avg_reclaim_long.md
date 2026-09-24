# Reclaimed session average

**Right answer when it works: BUY.** When the same setup failed fast (its stop was hit within 60
minutes), the question is a trap and the right answer is **STAY OUT** (see traps.md).

## What the question shows
The H1 structure is up and price **crosses back above the session average** (the running average price since the day's open, a stand-in for VWAP).

Questions are only asked between 10:00 and 20:00 server time (London open to late New York).

## Why pros take it
In an uptrend, dips below the day's average price are where value buyers step in. Getting back above it shows they have.

## The trade the quiz checks
- Entry: the question candle's close (plus the spread on a buy).
- Stop: 1.5 ATR from the entry.
- Target: 2R (twice the stop distance).
- It counts as a clean pro win only if the target is hit within 3 hours without first going more
  than 60% of the way to the stop. Messy winners are left out of the quiz.

## When it turns into a trap
- The average is flat and price has crossed it many times today: chop, not a trend.
- The H1 uptrend is weak (only just turned up).
- Quiet market: ATR at or below its usual, small candles (the report's biggest trap pattern; see quiz-weak-spots/references/claude-traps-quiet-markets.md).
- Holiday-thin weeks (about 20 Dec - 10 Jan; see claude-holiday-thin-january.md).
- Scheduled news (NFP, CPI, FOMC). The agent has no news input yet, so treat its answers near news as a coin flip.

## What the agent sees
`sess_avg_dist`, `h1_structure`, EMA distances, `atr_rel`, the chart. All 49 indicator inputs and the 178 chart inputs go in; these are the ones that matter most here.

## If the agent is stuck on this setup
1. Let it loop: a missed question's retries are answered on its section-mates (the 5 closest look-alikes of this
   setup with the same answer), so it learns the pattern, not one chart.
2. Read the weak-spot report (Quiz tab -> Weak spots); if this setup's traps look like its winners, no chart-only
   agent can split them. Treat its answers on this setup as a coin flip and ask Claude to add the missing input.
3. Pick the stuck squares -> Work on picked, then Continue (the memory check repairs any forgetting).
