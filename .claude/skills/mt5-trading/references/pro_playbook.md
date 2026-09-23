# How professional intraday traders read gold (and how the bot uses it)

Professional intraday traders (prop-firm, bank-desk and full-time discretionary traders) share a routine more than a
secret indicator. They do their preparation before the session, trade a few repeatable setups at pre-marked levels,
size so that one loss is small, and review every trade. This page covers that routine. The last section says how each
idea became a model input in `agent/pro.py`.

## Contents
1. Pre-session preparation
2. Levels they mark
3. Sessions and timing
4. The setups they trade
5. Risk and execution habits
6. What they avoid
7. Review
8. How the bot encodes this

## 1. Pre-session preparation
- **Economic calendar:** check for US CPI, NFP, FOMC, PCE, jobless claims and Fed speakers. Most pros are flat or
  standing aside from 2 minutes before to 5 minutes after a red-folder release. Gold can move $10–30 on the release
  candle, and the spread widens several times over.
- **Higher-timeframe bias:** read D1, H4 and H1 structure. Higher highs and higher lows mean buying pullbacks; lower
  lows and lower highs mean selling rallies. A range means fading its edges. M1 is only used for timing the entry.
- **Drivers:** the US dollar (DXY) and US real yields (10-year TIPS) move gold inversely. Risk-off flows lift it.
  Big moves in these are context, not entry signals.
- **Plan:** write down 2–3 scenarios, such as "if London sweeps the Asian low and reclaims it, look for longs to the
  prior-day high". Then trade the plan and don't improvise.

## 2. Levels they mark
| Level | Why it matters |
|---|---|
| Prior-day high / low / close | The most-watched intraday references; stop orders cluster just beyond them |
| Today's open, weekly open | Bias anchors: above the open means buyers are in control for that period |
| Asian session high / low | Gold's quiet overnight range; London often raids one side, and NY often runs the other |
| London / NY opening range (first 30 min) | Breakout-and-hold means a trend day; a failed break back inside means a reversal day |
| Session VWAP | The institutional fill benchmark. Far from it is stretched; a reclaim is a shift in control |
| Round numbers ($10, $50, $100) | Option strikes and resting orders; they act as magnets and barriers |
| Recent swing highs / lows | Where stops rest; the targets of stop hunts |

## 3. Sessions and timing (broker server time, UTC+2/+3)
- **Asia (01:00–09:00):** a thin range. Pros mostly mark it and don't trade it.
- **London open (10:00):** the first real volume. It often fakes one way first, sweeping the Asian range.
- **New York open (15:20 COMEX gold pit / 16:30 US stocks):** the highest volume. It often continues or reverses
  London's move.
- **London–NY overlap (15:20–18:30):** the best liquidity and the tightest spreads for M1 work.
- **After 21:00, and rollover (23:00–01:00):** spreads widen and pros don't open new trades.

## 4. The setups they trade
1. **Liquidity sweep (stop hunt) reversal:** price pushes through a recent high or low, or the Asian or prior-day
   extreme, triggers the stops, then closes back inside. Enter against the sweep with a stop just beyond the wick.
   The target is the other side of the range or VWAP.
2. **Opening-range breakout:** the London or NY 30-minute range breaks with a strong candle and holds on a retest.
   Enter on the retest with a stop inside the range. Skip it if the break came straight after a news spike.
3. **VWAP reclaim / rejection:** in a trend, price pulls back to VWAP and holds. Trend-following entries sit there.
   When price is stretched 3–4 ATR away from VWAP, pros fade it back toward the average.
4. **Fair value gap retest:** a strong 3-candle impulse leaves a gap (candle 1 and candle 3 don't overlap). Price
   often returns to fill it, so enter at the gap in the impulse's direction.
5. **Prior-day high/low break-and-retest, or failure:** acceptance above the prior-day high with a retest that holds
   means going with it. A fast poke and rejection is a sweep (setup 1).
6. **With higher-timeframe structure only:** most pros take M1 entries only in the H1/H4 direction unless it is an
   obvious sweep at a major level.

## 5. Risk and execution habits
- Risk per trade is fixed and small, 0.25–1% of the account. There is a daily max loss (often 2–3%); when it's hit,
  they're done for the day.
- The stop goes where the idea is proven wrong (beyond the sweep wick or the range), never at an arbitrary dollar
  amount. Size comes from the stop distance.
- They want targets of at least 1.5–3R. Many take partial profits at 1R, move the stop to break-even, and trail the
  rest.
- They use limit orders at levels when possible, and avoid market orders in fast, wide-spread moments.
- One to three good setups a day is normal. Waiting is the job.

## 6. What they avoid
- Trading the middle of the day's range with no level nearby.
- Chasing a candle that has already moved 2–3 ATR.
- Re-entering straight after a loss to "win it back" (revenge trading).
- Trading through red-folder news, rollover, or holiday-thin markets.
- Moving a stop further away.

## 7. Review
They journal every trade: the setup, the level, the session, screenshots, R result, and whether the plan was
followed. Each week they cut the setups that lose and size up the ones that work. The bot does the same
automatically in `agent/learn.py`, through the "By pro setup" table in the m1-bot-lessons skill and its blocked
setups.

## 8. How the bot encodes this (`agent/pro.py`)
All inputs are causal (they use only closed candles) and measured in ATRs:
- **Prior-day levels:** `pdh_dist`, `pdl_dist`, `pdc_dist`
- **Opens:** `day_open_dist`, `week_open_dist`; position in the day's range: `day_range_pos`
- **Asian range:** `asia_hi_dist`, `asia_lo_dist`
- **Opening ranges:** `lon_or_pos`, `ny_or_pos` (0 while inside the range, ATRs beyond it after the break)
- **Session average price:** `sess_avg_dist`. This is a time-weighted VWAP stand-in, because the free history has
  no volume.
- **Liquidity sweeps:** `sweep_long`, `sweep_short` (active for 5 candles); fresh breaks of the 60-candle high/low:
  `break_prior_hi`, `break_prior_lo`
- **Fair value gaps:** `fvg_net10` (bullish minus bearish gaps in the last 10 candles)
- **H1 structure:** `h1_structure` (−3 to +3, from completed hours)
- **Round numbers:** `round_small_dist` ($10 on gold), `round_big_dist` ($50)

`active_setups()` turns these into named setups, which the Market-tab bot card shows as "Pro read". Each trade is
filed under the setup that matches its direction (`ledger.setup`). `learn.py` groups results by setup and stops
taking setups that keep losing, but never more than half of them.

The model decides how much weight each input gets. Nothing here is a hard-coded rule except the learned blocks.
News is not in the model; stand aside manually around red-folder releases.
