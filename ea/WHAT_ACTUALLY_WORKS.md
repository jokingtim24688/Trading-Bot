# What the people who actually make money with bots do

Researched 2026-10-01. Sources at the bottom. The short version: the bots advertising
huge returns are mostly hiding risk, the real numbers are far smaller than the
marketing, and the thing separating winners from losers is validation discipline,
not a cleverer strategy.

## The actual success rates

| Figure | Source |
|---|---|
| ~1% of day traders are consistently profitable over time | day-trading statistics 2026 |
| ~90% lose money within their first year | same |
| <10% stay profitable across multiple years | same |
| Algo strategies that *do* work average **15-25% a YEAR** | algo profitability statistics 2026 |

Documented real strategies, for calibration:
- 9.5% annual return, 23% max drawdown, invested only 17% of the time
- A 5-strategy portfolio: 742 trades, 11.5% compounded annual return

That is what good looks like. **15-25% a year, not a day.**

## Why some Myfxbook accounts show +9,000%

Almost always grid or martingale. The mechanism is well documented and always the same:

1. **No stop loss.** Losing positions are held open, not cut. Balance looks healthy
   while equity quietly collapses.
2. **Floating drawdown is invisible.** The published gain is realised profit; the
   unrealised loss sitting in open trades is not shown.
3. **Lot sizes grow after losses.** Recovery accelerates in a ranging market and
   explodes in a trending one.
4. **Trend persistence kills it.** Grids assume mean reversion. A 500-pip run with no
   pullback stacks losers until margin runs out.
5. **The account dies at the margin call, not at the reversal.** Price often *would*
   have come back - the broker liquidated first.

So the curve climbs smoothly for months and then goes vertical downward in one session.
This is the same shape as the 600/20 test in `winrate_vs_money.py`: **94.8% win rate,
still loses money**. We measured the pattern before we read about it.

## What the professionals actually do differently

It is not the strategy. It is refusing to trust one until it has survived testing.

**The confidence ladder** (how much to believe a result at each stage):

| Stage | Confidence it is real |
|---|---|
| Backtest on the data you built it on | 20% |
| Out-of-sample test (data it never saw) | 40% |
| Walk-forward analysis | 60% |
| Forward testing | 80% |
| Paper / demo trading | 90% |

Standard practice:
- **Walk-forward optimisation** - the gold standard. Optimise on a window, test on the
  next unseen window, roll forward, repeat.
- **Decay analysis** - compare out-of-sample Sharpe, profit factor, drawdown and trade
  count against the in-sample numbers. A big drop means overfitting, not bad luck.
- **Monte Carlo** - reshuffle the trade order thousands of times. If some orderings
  bust the account, the risk is real even if the one historical path looked fine.
- **Placebo tests** - run the same process on random data. If it "finds" an edge there,
  the method is broken.

## How this repo already measures up

The good news: `CandleSenseML`'s trainer already does the professional version of this -
chronological (not random) splits, a hold-out test on months it never saw, costs built
into the labels, and per-symbol gates (>=30 trades, PF >= 1.15, >= 0.05R/trade). Its
unseen-month result was PF 1.15-1.17. That is a real methodology producing a modest,
believable number - which is exactly the shape a genuine edge has.

The thing to resist is the opposite shape: a huge, smooth, exciting number.
