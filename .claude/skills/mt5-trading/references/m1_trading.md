# M1 Trading Playbook

M1 is the only timeframe used. This file covers what that means in practice.

## 1. Cost reality check (do this first for any symbol)
```
cost_points  = spread_points + commission_in_points_round_trip + expected_slippage
atr_points   = ATR(14) on M1, in points
cost_ratio   = cost_points / atr_points
```
| cost_ratio | Verdict |
|---|---|
| < 0.10 | Good for M1 |
| 0.10–0.20 | Only wider targets (≥ 1.5–2× ATR) |
| > 0.20 | Don't trade this symbol/time on M1 |
Recompute per session: the same symbol can be fine at 14:00 UTC and bad at 21:30 UTC.

## 2. Mandatory filters for any M1 system
1. **Spread filter**: skip if current spread > X × median spread (e.g. 1.5×) or > absolute cap.
2. **Session filter**: trade only liquid windows (London, NY, overlap; stock cash session).
3. **News blackout**: no new entries from 5 minutes before to 5–15 minutes after high-impact events.
4. **Rollover blackout**: no trading ~20:55–22:10 UTC.
5. **Volatility band**: skip if ATR(14) M1 is below a floor (dead market) or above a ceiling (news spike).
6. **Closed-bar logic**: evaluate signals on bar index 1 (last closed), enter at the open of the new bar.
7. **Max trades/day and daily loss stop.**

## 3. Higher-timeframe context without leaving M1
Compute context from M1 bars:
- Rolling EMA(750) on M1 ≈ EMA(50) on M15; EMA(3000) on M1 ≈ EMA(50) on H1.
- Or resample: `df.resample('15min').agg({'open':'first','high':'max','low':'min','close':'last'})`, then
  forward-fill the value back onto M1 rows (use the *previous completed* 15-minute bar to avoid look-ahead).
The chart and execution stay M1.

## 4. Setup library (mechanical templates, not recommendations)
Each lists: context → trigger → stop → exit. All are evaluated on closed M1 bars.

**A. EMA pullback in trend**
- Context: close > EMA(200) and EMA(20) > EMA(50) (long; mirror for short).
- Trigger: price pulls back to touch EMA(20), then an M1 bar closes back above EMA(20) with close > open.
- Stop: below pullback swing low or 1.0× ATR(14).
- Exit: 1.5R target, or trail under EMA(20).

**B. Opening range breakout (stocks/indices; also London open for FX/gold)**
- Range: high/low of the first 15 M1 bars of the session.
- Trigger: M1 close beyond the range + spread filter OK.
- Stop: middle of the range or opposite side.
- Exit: 1–2R or time exit after 60 bars.

**C. VWAP reclaim / reject (stocks, indices)**
- Context: session VWAP from the cash open.
- Trigger: price crosses VWAP and the next M1 bar holds on the same side with rising volume.
- Stop: back through VWAP by 0.5× ATR.
- Exit: prior high/low of day or 2R.

**D. Bollinger mean reversion in ranges**
- Context: ADX(14) < 20 (range), no news.
- Trigger: close outside BB(20,2), next bar closes back inside.
- Stop: beyond the extreme + 0.3× ATR.
- Exit: middle band.

**E. Liquidity sweep reversal**
- Context: a clear prior swing high/low (e.g. the session high).
- Trigger: M1 wicks beyond it and closes back inside; the next bar confirms.
- Stop: beyond the sweep wick.
- Exit: opposite side of the local range or 2R.

## 5. Stops & targets on M1
- ATR-based stops adapt to volatility: stop = k × ATR(14), k ∈ [0.8, 2.0].
- The broker `trade_stops_level` can exceed a tight M1 stop, so check it.
- Targets must clear costs: gross target ≥ 3 × cost_points is a sensible floor.
- Time stop: if the trade hasn't moved 0.5R in N bars (e.g. 15–30), exit.

## 6. Execution on M1
- Latency: keep ping to the broker < 50 ms if possible. The home PC should be wired Ethernet.
- Use the correct filling mode (`symbol_info().filling_mode`) to avoid 10030 errors.
- Send SL/TP with the order. If the broker requires it, send them right after the fill, but never leave a
  position naked for long.
- Prefer limit entries on pullbacks (less slippage). Stop entries on breakouts will slip.
- Log the spread and fill slippage for every trade. It's the most important M1 metric.

## 7. Backtesting M1 honestly
- MT5 Tester: Timeframe M1, "Every tick based on real ticks", realistic delay, broker commission set.
- Python: simulate with bid/ask (not just close), add spread per bar (`rates['spread']` column), and
  apply commission. Enter at next bar open ± half spread + slippage.
- Walk-forward: e.g. train 3 months → test 1 month → roll.
- Check results per session and per weekday; M1 edges are usually session-specific.

## 8. Data volume on M1
- 1 year ≈ 260 trading days × 1,440 = ~374k bars (FX/gold, 24h). Fits in RAM easily (~30 MB float32 for 20 features).
- Ticks are much larger: gold can be 50–150k ticks/day. Store as Parquet, not CSV.
- MT5 keeps history in `bases\<server>\history\<symbol>`. Python `copy_rates_range` is capped by
  "Max bars in chart", so raise it first.
