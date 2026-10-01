# SmallAccountProNT - SmallAccountPro on NinjaTrader 8

`SmallAccountProNT.cs` is `ea/SmallAccountPro.mq5` rewritten in NinjaScript (NinjaTrader's C#) for
**CME 1-Ounce Gold futures (1OZ)**, the US-legal, CFTC-regulated way to trade gold with a small account.
One 1OZ contract moves $1 for every $1 gold moves, the same as 0.01 lots of XAUUSD.

## What was tested

`ea/futures_replay.py` on real gold, 30-minute candles, 26 Mar - 25 Sep 2026, $400 start, $2 commission
per round trip, 1-tick ($0.25) spread, risk ladder on, flat before CME's daily break:

| | Result |
|---|---|
| Trades | 407, 68% won |
| $400 became | $2,541 (+535%) |
| Worst drawdown | 48% |
| Weeks positive | 16 of 26, average +$82/week |
| Each half on its own | +253% and +297% |
| Entry candle also checked for stop/target* | $2,346 (+486%), DD 45% |

\*The replay ignored the high/low of the candle a trade opened on. NinjaTrader doesn't, so +486% is
the fairer number to compare with. Six months of one market is not proof: past results don't promise
future ones, and a 45-48% drawdown means $400 can fall to ~$210 on the way.

## Install (Windows)

1. Install NinjaTrader 8 (free) and log in. Sim101 is the built-in simulated account.
2. Copy `SmallAccountProNT.cs` to `Documents\NinjaTrader 8\bin\Custom\Strategies\`.
3. In NinjaTrader: **New > NinjaScript Editor**, open the file, press **F5**. The bottom panel must show
   no errors. (This file couldn't be compiled where it was written; send any error lines back to fix.)

## Test it in this order

1. **Strategy Analyzer** (New > Strategy Analyzer): Strategy `SmallAccountProNT`, instrument `1OZ` (front
   month), type Minute, value **30**, as much history as you have. Set **Commission** to your broker's
   (about $1 per side) and **Slippage** 1. Check: trades, win rate near 60-70%, net profit, max drawdown.
2. **Chart on Sim101**: open a 1OZ 30-minute chart, Strategies > add SmallAccountProNT, account
   **Sim101**, Starting balance **400**, enable. The top-left panel shows balance, risk, today's result and
   the last thing it did. Run it 2-4 weeks (50+ trades is better).
3. **Live**, only if the Sim101 results are close to the backtest: fund $400 and switch the account.

## Settings that matter

| Setting | Default | Note |
|---|---|---|
| Starting balance | 400 | The ladder counts from this plus the strategy's own closed profit, not the account (Sim101 holds $100,000). |
| Risk ladder | on | $5 per $100 to $599, $50 from $600, +$50 per $1,000 past $1,500. On $400 = $20 per trade. |
| Day margin per contract | 60 | Set it to your broker's 1OZ intraday margin. Trades are skipped rather than over-margined (80% cap). |
| Min / max stop | $5 / $25 | 500-2,500 points. Tighter stops lost to commission in testing. |
| No new trades after / close at | 15:30 / 16:30 New York | CME's daily break is 17:00 New York; nothing is held through it. |
| Daily loss limit | $15 | Stops for the session after -$15 realized. On $400 one full loss (-$20) hits it. |

## Differences from the MT5 EA

- 30-minute chart and wider stops (MT5 version: M15, 100-500 points, spot gold CFD).
- Stops move once per closed candle (as tested), not every tick.
- No spread filter (futures spread is normally 1 tick) and no start-up delay: it trades from the first
  closed candle after the 200 candles of history NinjaTrader loads.
- ATR is worked out as a simple average of the true range, like MT5's iATR (NinjaTrader's own ATR smooths).

## Before funding

Check the broker on NFA BASIC (https://www.nfa.futures.org/BasicNet/): NinjaTrader Clearing LLC is NFA
ID 0309379. If its status there isn't plain "Approved" as an FCM, ask NinjaTrader which FCM clears
new US accounts and check that one instead.
