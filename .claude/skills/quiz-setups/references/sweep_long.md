# Liquidity sweep below lows

**Right answer when it works: BUY.** When the same setup failed fast (its stop was hit within 60
minutes), the question is a trap and the right answer is **STAY OUT** (see traps.md).

## What the question shows
In the last 5 candles price dipped **below the lowest low of the previous hour** (60 M1 candles) and closed back above it: a stop run under an obvious low. The question is asked on the first candle it appears.

Questions are only asked between 10:00 and 20:00 server time (London open to late New York).

## Why pros take it
Stops and breakout sells sit just under an obvious low. When they are triggered and price closes straight back above, the sellers are used up and the trapped ones have to buy back. Pros buy that failure to break down.

## The trade the quiz checks
- Entry: the question candle's close (plus the spread on a buy).
- Stop: Just beyond the sweep's wick: the most extreme price of the last 5 candles plus 0.2 ATR of room, kept between 0.8 and 3 ATR from the entry.
- Target: 2R (twice the stop distance).
- It counts as a clean pro win only if the target is hit within 3 hours without first going more
  than 60% of the way to the stop. Messy winners are left out of the quiz.

## When it turns into a trap
- The H1 structure is clearly down: in a real downtrend the low usually breaks for good.
- Several sweeps of the same low in a row: the level is being worn down, not defended.
- The sweep is a news spike (NFP, CPI, FOMC) that is still moving.
- Quiet market: ATR at or below its usual, small candles (the report's biggest trap pattern; see quiz-weak-spots/references/claude-traps-quiet-markets.md).
- Holiday-thin weeks (about 20 Dec - 10 Jan; see claude-holiday-thin-january.md).
- Scheduled news (NFP, CPI, FOMC). The agent has no news input yet, so treat its answers near news as a coin flip.

## What the agent sees
`sweep_long`, `break_prior_lo`, `h1_structure`, distance to the prior-day low and the Asian low, `atr_rel`, and the last 40 candles of the chart. All 49 indicator inputs and the 178 chart inputs go in; these are the ones that matter most here.

## If the agent is stuck on this setup
1. Let it loop: a missed question's retries are answered on its section-mates (the 5 closest look-alikes of this
   setup with the same answer), so it learns the pattern, not one chart.
2. Read the weak-spot report (Quiz tab -> Weak spots); if this setup's traps look like its winners, no chart-only
   agent can split them. Treat its answers on this setup as a coin flip and ask Claude to add the missing input.
3. Pick the stuck squares -> Work on picked, then Continue (the memory check repairs any forgetting).
