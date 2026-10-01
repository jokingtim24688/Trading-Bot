import numpy as np, pandas as pd
from data import load15, resample
D = resample(load15(), "D"); D = D[D.index.weekday < 5]
O, H, L, C = (D[c].values for c in ("open", "high", "low", "close")); n = len(D); idx = D.index
tr = np.r_[H[0]-L[0], np.maximum(H[1:]-L[1:], np.maximum(abs(H[1:]-C[:-1]), abs(L[1:]-C[:-1])))]
atr = pd.Series(tr).rolling(20).mean().values
# 1) Connors RSI(2) dip-buy above SMA200, exit close > SMA5 (fills next open), $2.50 cost per oz-contract
d = pd.Series(C).diff(); up = d.clip(lower=0).ewm(alpha=1/2).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1/2).mean()
rsi2 = (100 - 100/(1+up/dn)).values; s200 = pd.Series(C).rolling(200).mean().values; s5 = pd.Series(C).rolling(5).mean().values
tr_, pos = [], None
for i in range(201, n-1):
    if pos is None and C[i] > s200[i] and rsi2[i] < 10: pos = (O[i+1], idx[i+1]); continue
    if pos and C[i] > s5[i]: tr_.append((pos[1], O[i+1]-pos[0]-2.5, pos[0])); pos = None
t = pd.DataFrame(tr_, columns=["time","pnl","px"]); t["pct"] = t.pnl/t.px
for nm, x in (("all", t), ("<2015", t[t.time<"2015"]), (">=2015", t[t.time>="2015"])):
    print(f"RSI2 dip-buy {nm:7s} n={len(x)} win {100*(x.pnl>0).mean():.0f}%  avg {100*x.pct.mean():+.3f}% per trade")
# 2) Daily Donchian 55/20 long-only, 2ATR stop, sized on % of equity: shares of a no-leverage gold fund
def equity(risk_pct, N=55, M=20, sa=2.0, cost=0.0005, max_expo=1.0):
    hiN = pd.Series(H).rolling(N).max().shift(1).values; loM = pd.Series(L).rolling(M).min().shift(1).values
    eq, pos, curve = 1.0, None, []
    for i in range(201, n):
        if pos:
            ex = max(pos["st"], loM[i])
            xp = O[i] if O[i] <= ex else (ex if L[i] <= ex else None)
            if xp is not None:
                eq *= 1 + pos["w"] * ((xp/pos["e"]) - 1) - pos["w"]*cost; pos = None
        if pos is None and H[i] >= hiN[i]:
            e = max(O[i], hiN[i]); st = e - sa*atr[i-1]
            w = min(max_expo, risk_pct / ((e-st)/e))
            if L[i] <= st: eq *= 1 + w*((st/e)-1) - 2*w*cost
            else: pos = {"e": e, "st": st, "w": w}; eq *= 1 - w*cost
        mark = eq * (1 + pos["w"]*(C[i]/pos["e"]-1)) if pos else eq
        curve.append((idx[i], mark))
    c = pd.Series(dict(curve)); yrs = (c.index[-1]-c.index[0]).days/365.25
    dd = (c/c.cummax()-1).min(); ann = c.iloc[-1]**(1/yrs)-1
    half = c[c.index < "2015"]; h2 = c[c.index >= "2015"]
    a1 = (half.iloc[-1]/half.iloc[0])**(365.25/(half.index[-1]-half.index[0]).days)-1
    a2 = (h2.iloc[-1]/h2.iloc[0])**(365.25/(h2.index[-1]-h2.index[0]).days)-1
    return ann, dd, a1, a2, c
bh = pd.Series(C[201:], index=idx[201:]); yrs = (bh.index[-1]-bh.index[0]).days/365.25
print(f"\nBuy & hold gold: {100*((bh.iloc[-1]/bh.iloc[0])**(1/yrs)-1):.1f}%/yr, worst drop {100*(bh/bh.cummax()-1).min():.0f}%")
for rp in (0.01, 0.02, 0.03, 0.05):
    ann, dd, a1, a2, c = equity(rp)
    print(f"Trend 55/20 long-only, risk {rp:.0%}/trade, no leverage: {100*ann:5.1f}%/yr  worst drop {100*dd:4.0f}%   2005-14 {100*a1:5.1f}%/yr  2015-26 {100*a2:5.1f}%/yr  $400 -> ${400*c.iloc[-1]:,.0f}")
