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

## Install (Windows only - NinjaTrader Desktop doesn't run on Mac)

1. **Make a free account**: https://account.ninjatrader.com/register - enter your email, click the link
   it sends you, pick a username and password. Then click **"Not ready for live trading? Try risk-free
   simulated trading."** and finish the form. No card needed. This starts a 2-week trial with live CME
   data; after that the data is 10 minutes delayed until you fund an account.
   (NinjaTrader's own steps: https://support.ninjatrader.com/s/article/How-Can-I-Get-a-Free-Trial-of-NinjaTrader)
2. **Download NinjaTrader Desktop**: log in at https://account.ninjatrader.com/ and click
   **Download Desktop Platform** (https://support.ninjatrader.com/s/article/NinjaTrader-Desktop-Installation-Guide).
   Run the installer, open NinjaTrader and log in with the same username and password. The **Sim101**
   account (practice money) is created for you.
3. **Add the strategy**: copy `SmallAccountProNT.cs` to
   `Documents\NinjaTrader 8\bin\Custom\Strategies\`. In NinjaTrader's Control Center:
   **New > NinjaScript Editor**, open Strategies > SmallAccountProNT, press **F5**. The bottom of the
   editor must show no errors (a sound plays when it compiles). It couldn't be compiled where it was
   written, so send any error lines back to fix.
   If Windows keeps Documents in OneDrive and NinjaTrader says "Access to the path is denied", see
   https://support.ninjatrader.com/s/article/Unhandled-exception-Access-to-the-path-is-denied-OneDrive-Error

## Test it in this order

1. **Commission**: Control Center > **Accounts** tab, right-click **Backtest** > Edit account, set the
   Commission template to your NinjaTrader plan (about $1 per side for 1OZ). Do the same for **Sim101**.
2. **Backtest - Strategy Analyzer** (New > Strategy Analyzer). Left panel:
   - Strategy **SmallAccountProNT**; Instrument **1OZ** (front month; type `1OZ` in the box). Don't use
     MGC instead - Micro Gold is 10x bigger per contract.
   - Type **Minute**, Value **30**; dates: the last 6-12 months.
   - **Include commission: True**, Slippage **1**, Starting balance **400**. Click **Run**.
   - Check the Summary tab: trades, % profitable (tested ~68%), net profit, max drawdown, and the
     Trades tab for anything odd. Send a screenshot back to compare with the replay.
3. **Practice live - Sim101**: New > Chart, instrument 1OZ, 30 Minute. Right-click the chart >
   **Strategies** > add SmallAccountProNT, Account **Sim101**, Starting balance **400**, tick **Enabled**,
   OK. The top-left panel shows balance, risk per trade, today's result and the last thing it did. Leave
   the PC and NinjaTrader on during market hours (Sun 6pm - Fri 5pm New York, break 5-6pm daily). Run it
   2-4 weeks (50+ trades is better) and compare with the backtest.
4. **Live**, only if Sim101 is close to the backtest: from the dashboard click **Start Application**,
   fund $400, then pick the live account instead of Sim101 in step 3.

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
