"""Daily-bar trend following on gold (1 contract 1OZ, holds overnight)."""
import numpy as np, pandas as pd
from data import load15, resample
from eng import report, COMM, TICK
D = resample(load15(), "D"); D = D[D.index.weekday < 5]
O, H, L, C = (D[c].values for c in ("open", "high", "low", "close")); n = len(D)
tr = np.r_[H[0] - L[0], np.maximum(H[1:] - L[1:], np.maximum(abs(H[1:] - C[:-1]), abs(L[1:] - C[:-1])))]
atr = pd.Series(tr).rolling(20).mean().values
sma = lambda k: pd.Series(C).rolling(k).mean().values
def donchian(N, M, stop_atr, longs=True, shorts=True, filt=None):
    hiN = pd.Series(H).rolling(N).max().shift(1).values; loN = pd.Series(L).rolling(N).min().shift(1).values
    hiM = pd.Series(H).rolling(M).max().shift(1).values; loM = pd.Series(L).rolling(M).min().shift(1).values
    rows, pos = [], None
    for i in range(max(N, M, 200) + 1, n):
        if pos:
            s, e, st = pos["side"], pos["e"], pos["st"]
            ex = max(st, loM[i]) if s == 1 else min(st, hiM[i])          # stop = tighter of initial and M-day channel
            if s == 1 and O[i] <= ex: xp = O[i] - TICK
            elif s == -1 and O[i] >= ex: xp = O[i] + TICK
            elif s == 1 and L[i] <= ex: xp = ex - TICK
            elif s == -1 and H[i] >= ex: xp = ex + TICK
            else: continue
            rows.append((D.index[i], (xp - e) * s - COMM, pos["risk"])); pos = None
            continue                                                       # re-entry from next day
        up = longs and H[i] >= hiN[i] + TICK and (filt is None or filt[i - 1] > 0)
        dn = shorts and L[i] <= loN[i] - TICK and (filt is None or filt[i - 1] < 0)
        if up and dn: continue
        if up or dn:
            s = 1 if up else -1; lvl = hiN[i] + TICK if up else loN[i] - TICK
            e = (max(O[i], lvl) + TICK) if up else (min(O[i], lvl) - TICK)
            st = e - s * stop_atr * atr[i - 1]
            # same-day stop check (conservative)
            if (s == 1 and L[i] <= st) or (s == -1 and H[i] >= st):
                rows.append((D.index[i], (st - e) * s - TICK - COMM, abs(e - st) + COMM)); continue
            pos = {"side": s, "e": e, "st": st, "risk": abs(e - st) + COMM}
    return pd.DataFrame(rows, columns=["time", "pnl", "risk"])
if __name__ == "__main__":
    bh = C[-1] - C[200]; print(f"buy & hold 1 contract from {D.index[200].date()}: ${bh:,.0f}")
    trend = np.sign(sma(50) - sma(200))
    for N, M in ((20, 10), (55, 20), (100, 50)):
        for sa in (2.0, 3.0):
            report(f"Donchian {N}/{M} stop {sa}ATR both", donchian(N, M, sa))
            report(f"Donchian {N}/{M} stop {sa}ATR long-only", donchian(N, M, sa, shorts=False))
            report(f"Donchian {N}/{M} stop {sa}ATR w/ 50>200 filter", donchian(N, M, sa, filt=trend))
