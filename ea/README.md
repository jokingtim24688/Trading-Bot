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

## CandleSenseSwing.mq5

A much simpler style, built from your own description: "where the chart is going", very low
take profits, stacking lots of trades at once (up to 60) instead of waiting for one high-quality
setup.

**How it decides direction**: an EMA (`TrendEMA`, default 50) on `EntryTF` (default M5) - if it
has sloped upward for `TrendConfirmBars` bars in a row, it's an uptrend (and vice versa). No
FVG/order block/killzone logic at all - that's the whole point of this one being simpler.

**How it trades**: every time the trend direction holds and price has moved at least
`MinStackPoints` since the last entry in that direction, it opens another market order with a
**fixed** stop (`SL_Points`, default 150) and target (`TP_Points`, default 200) - not ATR-based.
It keeps doing this until `MaxOpenTrades` (default 60) are open at once.

**Why it isn't simply "60x normal risk"**: with 60 trades open, if the market reversed hard and
every single one hit its stop at the same time, a flat per-trade risk % would mean 60x your
normal per-trade loss. Instead, `MaxTotalRiskPct` (default 8%) caps what **all** open trades
losing together would cost, and splits that budget across `MaxOpenTrades`, so the worst case is
capped no matter how many trades have stacked. Raise `MaxTotalRiskPct` carefully - at 150/200
points SL/TP on gold, spread and commission eat into every single one of those trades, so a high
trade count also means higher total costs, not just higher total risk.

**This is a high-turnover style.** Demo-test it for a while and watch the HUD's Earned vs Lost
line before even considering it live - fixed-point SL/TP with no setup filter will take a lot of
small losses to catch the trend moves that pay for them.
