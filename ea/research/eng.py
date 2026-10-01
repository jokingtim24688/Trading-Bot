"""Honest bar simulator for 1 contract of CME 1-Ounce Gold ($1 per $1). Costs: $2 round trip + 1 tick
slippage on every market/stop fill. Stops gapped through fill at the open. Stop assumed before target."""
import numpy as np, pandas as pd
COMM, TICK = 2.0, 0.25
def walk(O, H, L, C, i, side, entry, stop, target, last):
    """Bar i is the entry bar (entry already filled inside it). Returns (exit_index, exit_price)."""
    for k in range(i, last + 1):
        if k > i:   # gaps at the open
            if side == 1 and O[k] <= stop: return k, O[k] - TICK
            if side == -1 and O[k] >= stop: return k, O[k] + TICK
            if target is not None and (side == 1 and O[k] >= target or side == -1 and O[k] <= target): return k, O[k]
        if side == 1 and L[k] <= stop: return k, stop - TICK
        if side == -1 and H[k] >= stop: return k, stop + TICK
        if k > i and target is not None and (side == 1 and H[k] >= target or side == -1 and L[k] <= target): return k, target
    return last, C[last] - side * TICK          # time exit at the close of the last bar
def pnl(side, entry, exitp): return (exitp - entry) * side - COMM
def report(name, trades, split="2015-01-01"):
    """trades: DataFrame with time, pnl, risk ($ per contract at the stop)."""
    if len(trades) == 0: print(f"{name:42s} no trades"); return None
    t = trades.copy(); t["r"] = t.pnl / t.risk
    a, b = t[t.time < split], t[t.time >= split]
    yrs = t.groupby(t.time.dt.year).pnl.sum()
    pf = t.pnl[t.pnl > 0].sum() / max(1e-9, -t.pnl[t.pnl < 0].sum())
    f = lambda x: f"{x.r.mean():+.3f}R n{len(x)}" if len(x) else "-"
    print(f"{name:42s} n={len(t):5d} win {100*(t.pnl>0).mean():3.0f}%  avg {t.r.mean():+.3f}R ${t.pnl.mean():+6.2f}  PF {pf:4.2f} | "
          f"<2015 {f(a)} | >=2015 {f(b)} | yrs+ {int((yrs>0).sum())}/{len(yrs)}")
    return t
