# Gold strategy research with honest fills (2026-10-01)

22 years of real gold (2004-06 to 2025-09, BaseMax/XAUUSD-LSTM, MIT, + 2026 data in `ea/`), New York time.
Fills: entry next open + 1 tick, stops gapped through fill at the open, stop before target in the same
candle, $2 round trip per 1OZ contract. Run: `python s_orb.py`, `python s_trend.py`, `python s_trend2.py 4h`,
`python s_final.py`.

| Family | Result |
|---|---|
| Opening-range breakout (London / COMEX / NY, 54 versions) | all lose, 0/23 years positive |
| Donchian trend on 1-hour candles | lose |
| Donchian trend on 4-hour candles | only long lookbacks (100-200 bars) win |
| Donchian trend on daily candles (18 versions) | all win in both 2004-14 and 2015-26 |
| RSI(2) dip-buy, daily | +0.11% per trade, too small to matter |
| SmallAccountPro (M15/M30 pullback) | loses once stops fill honestly |

Catch: gold's daily range is now ~$95, so a daily-trend stop is ~$190 per 1OZ contract - 47% of $400.
Without leverage (fund shares sized by risk), daily 55/20 long-only made ~6%/yr with a 20% worst drop
(buy & hold: 11.3%/yr, 45% worst drop).
