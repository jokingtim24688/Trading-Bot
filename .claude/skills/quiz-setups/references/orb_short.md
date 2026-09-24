# Opening-range breakout down

**Right answer when it works: SELL.** When the same setup failed fast (its stop was hit within 60
minutes), the question is a trap and the right answer is **STAY OUT** (see traps.md).

## What the question shows
The first close more than 0.2 ATR **below the opening range** once it is complete (London 10:00-10:30, New York 16:30-17:00 server time).

Questions are only asked between 10:00 and 20:00 server time (London open to late New York).

## Why pros take it
A clean break below the session's first half-hour range shows sellers in control; the session tends to follow.

## The trade the quiz checks
- Entry: the question candle's close (plus the spread on a buy).
- Stop: 1.5 ATR from the entry.
- Target: 2R (twice the stop distance).
- It counts as a clean pro win only if the target is hit within 3 hours without first going more
  than 60% of the way to the stop. Messy winners are left out of the quiz.

## When it turns into a trap
- A narrow range on a quiet day.
- The break runs into yesterday's low or a $50 round number.
- A break just before news.
- Late in the session.
- Quiet market: ATR at or below its usual, small candles (the report's biggest trap pattern; see quiz-weak-spots/references/claude-traps-quiet-markets.md).
- Holiday-thin weeks (about 20 Dec - 10 Jan; see claude-holiday-thin-january.md).
- Scheduled news (NFP, CPI, FOMC). The agent has no news input yet, so treat its answers near news as a coin flip.

## What the agent sees
`lon_or_pos`, `ny_or_pos`, time of day (`tod_sin`/`tod_cos`), distance to the prior-day low and round numbers, `atr_rel`. All 49 indicator inputs and the 178 chart inputs go in; these are the ones that matter most here.

## If the agent is stuck on this setup
1. Let it loop: a missed question's retries are answered on its section-mates (the 5 closest look-alikes of this
   setup with the same answer), so it learns the pattern, not one chart.
2. Read the weak-spot report (Quiz tab -> Weak spots); if this setup's traps look like its winners, no chart-only
   agent can split them. Treat its answers on this setup as a coin flip and ask Claude to add the missing input.
3. Pick the stuck squares -> Work on picked, then Continue (the memory check repairs any forgetting).
