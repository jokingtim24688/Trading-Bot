# Traps (all setups)

**Right answer: STAY OUT.** A trap is one of the 18 setups that appeared exactly as in a winning question, but a trade
taken the pro way hit its stop within 60 minutes. The quiz asks it so the agent learns *when not to*
take a setup, not only when to.

## Why they're hard
The chart at the question candle often looks just like a winner. What decides it is usually not on the chart:
- Quiet markets: small candles, ATR at or below usual. The report's biggest pattern.
- News releases (NFP, CPI, FOMC). The agent has no news input yet.
- Holiday-thin weeks around New Year.

## How the quiz handles them
- Traps are about 15% of a quiz (at most 30% when other groups run out).
- A trap is dropped from the bank when its look-alikes mostly have the other answer, because then no one could tell.
- Missed traps are retried on section-mates (other traps of the same setup), so the agent learns the trap pattern
  rather than one chart.

## What to do when traps stay stuck
- Read the weak-spot report's "trap check": if it says the chart can't separate traps from winners, the fix is a
  new input, not more training.
- The candidates are a news-time flag, today's range against a normal day, and the real spread from MT5.
- Ask Claude to add them.
- Meanwhile, treat the agent's BUY/SELL on a setup in a quiet market as a coin flip.

Each setup's own trap signs are on its page.
