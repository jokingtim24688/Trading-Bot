# Spot crypto trend rules on daily candles (2026-10-01)

Data: Binance daily klines (SOLUSDT 2020-08 .., BTC/ETHUSDT 2017-08 .. 2026-09-26), fetched through the
public `data-api.binance.vision/api/v3/klines` endpoint; saved as `{SOL,BTC,ETH}_1d.csv` (not committed).
Rules: signal at the close, swap at the next open, 0.3% per swap, no leverage (USDC <-> coin, like a
Jupiter swap). `python ctest.py`.

| SOL | %/yr | worst drop | 2020-23 | 2023-26 |
|---|---|---|---|---|
| buy & hold | 77 | -96% | 72 | 82 |
| hold when close > SMA50 | 118 | -70% | 186 | 66 |
| hold when close > SMA200 | 78 | -67% | 82 | 75 |
| Donchian 55/20 | 101 | -71% | 205 | 32 |

BTC/ETH: SMA50 beat holding in both halves (BTC 97/24 vs 63/19; ETH 76/32 vs 60/1); most other rules
only won in the first half. Trend rules mainly cut the crash (-96% -> -67/-70%); returns come from
crypto rising. $250 at 100%/yr is ~$5/week, not $100.
