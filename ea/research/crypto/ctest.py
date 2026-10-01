"""Spot-only, unlevered crypto rules on daily candles. Signal at the close, trade at the NEXT open,
0.3% cost per swap (Jupiter fee + slippage + network, conservative for a $250 wallet)."""
import pandas as pd, numpy as np
COST = 0.003
P = {s: pd.read_csv(f"{s}_1d.csv", index_col=0, parse_dates=True) for s in ("SOL", "BTC", "ETH")}
def run(sym, sig):
    """sig: Series of 0/1 known at each close -> held from the next open to the following open."""
    d = P[sym]; o = d.open.values; pos = sig.reindex(d.index).fillna(0).values
    eq, held, curve = 1.0, 0, []
    for i in range(1, len(d)):
        want = pos[i - 1]
        if want != held: eq *= 1 - COST; held = want
        if held and i + 1 < len(d): eq *= o[i + 1] / o[i]
        curve.append(eq)
    return pd.Series(curve, index=d.index[1:])
def stats(c):
    yrs = (c.index[-1] - c.index[0]).days / 365.25
    return (c.iloc[-1] / c.iloc[0]) ** (1 / yrs) - 1, (c / c.cummax() - 1).min()
def show(name, c, mid):
    a, dd = stats(c); a1, _ = stats(c[c.index < mid]); a2, _ = stats(c[c.index >= mid])
    print(f"{name:34s} {100*a:7.1f}%/yr  worst drop {100*dd:4.0f}%   1st half {100*a1:7.1f}%/yr  2nd half {100*a2:7.1f}%/yr")
for s in ("SOL", "BTC", "ETH"):
    d = P[s]; C = d.close; mid = d.index[len(d) // 2]
    print(f"\n== {s} {d.index[0].date()} .. {d.index[-1].date()} (halves split {mid.date()})")
    show("buy & hold", run(s, pd.Series(1, index=d.index)), mid)
    for n in (20, 50, 100, 200):
        show(f"hold when close > SMA{n}", run(s, (C > C.rolling(n).mean()).astype(int)), mid)
    for N, M in ((20, 10), (55, 20)):
        hi = d.high.rolling(N).max().shift(1); lo = d.low.rolling(M).min().shift(1)
        st, sig = 0, []
        for c, h, l in zip(C, hi, lo):
            if not st and c > h: st = 1
            elif st and c < l: st = 0
            sig.append(st)
        show(f"Donchian {N}/{M} (close-based)", run(s, pd.Series(sig, index=d.index)), mid)
