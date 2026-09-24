# Traps are quiet, small-candle markets (written by Claude from the 2026-09-24 report)

## What the report showed
Every weak spot in the report was a trap group: a setup appeared, but its stop was hit within the hour, so the pro
answer is STAY OUT.
- Practice right was 17–60%, and the exam was 0–7% in every setup.
- The usual mistake was taking the trade (BUY on bullish setups, SELL on bearish ones).

The trap check agreed across all eight setups. Compared with the setup's winners, traps happen:

| Measure | Traps | Winners |
|---|---|---|
| Volatility (ATR vs its usual) | 1.0–1.3× | 1.5–2.4× |
| "Spread/ATR" | 0.31–0.50 | 0.18–0.26 |
| Distance to a $50 round number (ATRs) | 41–61 | 21–27 |

## These are one pattern, not three
- The downloaded history (HistData) has no real spread. The quiz fills in one estimated spread, so **spread/ATR only
  measures how small the candles are**.
- Round-number distance is measured in ATRs, so it also grows when candles shrink.
- The trap check was really saying the same thing three times: **traps come when candles are small and the market
  is quiet.** The report now merges measures that move together and words spread/ATR as candle size.

## The market reason
Sweeps, breakouts and pullbacks need follow-through: other traders piling in after the trigger.
- In a quiet market (small candles, low ATR relative to its usual) there is little follow-through. A 2R target is
  far away in candle terms, and the stop gets hit by ordinary noise.
- In active markets (London/NY with news flow), the same trigger has fuel behind it.

Pros check the volatility regime before trading a setup, e.g. "is today's range normal or dead?". They skip
triggers in dead tape.

## Why the agent can't learn it yet
Within each trap group, the ones it misses are the traps that **look like winners**: higher volatility (1.3–2.1×)
and bigger candles. It has learned "active market plus setup means take it", which is right for winners, so the
active-looking traps fool it. Separating those needs information the chart doesn't carry:
- News timing (a spike that reverses).
- Real volume.
- The day's range so far vs normal.

## How to use this
- Treat the quiz agent's BUY/SELL on a setup in a **quiet market** (ATR near or below its usual, small candles) as a
  coin flip, whatever confidence it shows.
- For the live bot, a volatility-regime filter is the pro fix: skip setups when ATR is below ~1.2× its usual. That's
  a candidate rule for the learned-rules / Settings, not yet automatic.
- Possible builder/input improvements:
  - Real spread from MT5 for recent years instead of the estimate.
  - "The day's range so far vs the 20-day average range".
  - A news-time flag (NFP, CPI, FOMC).
