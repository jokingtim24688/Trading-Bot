# EAs in this folder

- **`CandleSenseICT.mq5`** - the advanced, setup-quality-scored EA (FVG + Order Block + killzones).
  Few trades, high selectivity. See its own section below.
- **`CandleSenseSwing.mq5`** - a simple trend-direction "stacker": no FVG/OB scoring, just trades
  with the chart's current EMA-slope direction repeatedly, up to many concurrent trades, each with
  a fixed SL/TP in points. See "CandleSenseSwing.mq5" below.

# CandleSenseICT.mq5

One advanced, single-file EA for gold (XAUUSD) on MT5, instead of the multi-file ML pipeline
(`CandleSenseML`, `CandleSenseMulti`) built earlier. Built by combining ideas from real,
MIT-licensed open-source gold EAs with the parts of `CandleSense.mq5` worth keeping.

## Where the ideas came from

- **Fair Value Gap (FVG) detection + 0-100 quality score** (gap size, displacement strength,
  H1 trend alignment, freshness, premium/discount) and **Order Block confluence bonus**:
  adapted from [foeed/FvgGold-EA](https://github.com/foeed/FvgGold-EA) (MIT license, verified
  before use) - a real gold EA with a 45% win rate and +48.7% over a 6-month backtest.
- **Killzones** (London open, NY, London/NY overlap in GMT): the standard ICT session-filter
  idea used by most public gold EAs researched (FvgGold-EA, Gold ICT OrderBlock Expert,
  BAKOMEGoldScalper).
- **Liquidity sweep detection**: kept from `CandleSense.mq5` (a stop-hunt wick beyond a recent
  swing high/low that closes back inside), now used as a confluence bonus for an FVG rather
  than its own standalone signal.
- **Risk-based position sizing via `OrderCalcProfit()`**: the fix `CandleSense.mq5` v1.50 made
  to its own 10x sizing bug, applied here from the start instead of a generic tick-value guess.
- **Self-learning setup weights**: unique to this repo, not borrowed. Each of the 4 setup
  combinations (FVG only / FVG+OB / FVG+sweep / FVG+OB+sweep) is scored from its own closed
  trades (global variables, survives restarts); a combination with a losing track record needs
  a higher score to fire again, the same idea `CandleSense.mq5` used for its 8 rule-based
  signals.

## What it does NOT do (kept out on purpose, to stay auditable)

- No martingale, no grid, no averaging down.
- No multi-symbol / portfolio logic - one EA, one chart, gold only (though nothing in the FVG/OB
  math is gold-specific; it would run on any symbol, untested).
- No news-calendar filter yet (the app's own `agent/news.py` has one; porting it into an EA is a
  natural next step if you want it).

## Installing it

Same as `CandleSense.mq5`: open **MetaEditor** (Tools -> MetaEditor in MT5), **File -> Open**,
navigate to your **Experts** folder, copy `CandleSenseICT.mq5` there, open it and press **F7** to
compile. Attach it to an **XAUUSD H1 or M15 chart** (the `SetupTF` input controls which
timeframe it actually trades on - default M15 - independent of the chart's own timeframe).

## Testing it (no live MT5 from this cloud session)

This session can't reach your MT5 terminal, so I could not run it through the Strategy Tester or
place a live test trade. Two ways to verify it yourself:

1. **Strategy Tester (recommended first step)**: Ctrl+R -> Expert: CandleSenseICT -> Symbol
   XAUUSD -> Model "Every tick based on real ticks" -> pick a few months of history -> Start.
   Check the compile log first (MetaEditor's "Errors" tab after F7) in case your broker's MQL5
   build differs from what was written here.
2. **Ask the `mt5-m1-trader` subagent** (on your own PC, where it has live `mcp__mt5__*` tools):
   it can run `mt5_symbol_spec`, place a tiny demo-account test order, and check the EA's
   `Print()` log lines for sane sizing before you leave it running.

## Key inputs worth tuning first

| Input | Default | What it does |
|---|---|---|
| `MinScore` | 55 | Raise this first if it's trading too often / on weak setups |
| `RiskPercent` | 0.5 | % of balance risked per trade |
| `MaxTradesPerDay` / `MaxOpenTrades` | 6 / 2 | Caps on new entries |
| `UseKillzones`, `KZ_*` | on, 7-10 & 12-16 GMT | Check your broker's GMT offset (`GMT_Offset_Hours`) |
| `RiskRewardRatio` | 2.0 | Fixed target distance = stop distance x this |
| `UseLearning` | on | Turn off to keep all 4 setup types trading at equal weight |

Run it on demo first, same as every EA in this repo.

## CandleSenseSwing.mq5 (v2)

Trades **every swing of the chart, both ways** - no confidence filter. v1 waited for an EMA to
slope the same way for 3 bars and sat out most swings; v2 reads the chart's own swing highs and
lows on `EntryTF` (default M1):

- last confirmed swing was a **low** -> the chart is swinging up -> it **buys**;
- last confirmed swing was a **high** -> swinging down -> it **sells**.

A swing high/low is a bar that beats `SwingStrength` (default 2) bars on each side. There is
always a current swing, so it always has a direction. The first trade of each new swing goes in
at once; further trades stack every `MinStackPoints` (default 60) the price travels with it, up to
`MaxOpenTrades` (60). Every trade has the fixed `SL_Points` 150 / `TP_Points` 200.

Sizing: `MaxTotalRiskPct` (8%) caps what all open trades would lose together if every stop hit at
once, split across `MaxOpenTrades`.

HUD: current swing (UP/DOWN and from which price), trades, win rate (with the 43% break-even for
150/200), open trades, earned, lost, subtotal.

**v2.10**: every `EntryEverySeconds` (5) it opens another trade with the current swing (a timer,
not just new bars), until 60 are open. If price breaks back past the swing point, the direction
flips at once. `MinStackPoints` is now 0 (off) by default. `MaxSpreadPoints` raised 40 -> 120
(the demo's gold spread was 38-70 points, so 40 blocked most entries). The HUD's "Last:" line
shows the last trade or the reason it skipped.

More swings = more trades = more spread paid. Demo-test it and watch the win rate line.
