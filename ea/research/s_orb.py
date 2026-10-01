import numpy as np, pandas as pd, sys
from data import load15
from eng import walk, pnl, report, TICK
d = load15(); d = d[d.index.weekday < 5]
O, H, L, C = (d[c].values for c in ("open", "high", "low", "close"))
mins = (d.index.hour * 60 + d.index.minute).values
day = d.index.normalize().values
starts = np.r_[0, np.flatnonzero(day[1:] != day[:-1]) + 1, len(d)]
def orb(s, ln, stop_mode, rr, cut=16 * 60 + 15, both=True):
    rows = []
    for a, b in zip(starts[:-1], starts[1:]):
        m = mins[a:b]
        orr = np.flatnonzero((m >= s) & (m < s + ln)) + a
        if len(orr) < ln // 15: continue
        hi, lo = H[orr].max(), L[orr].min(); rng = hi - lo
        if rng <= 0: continue
        after = np.flatnonzero((m >= s + ln) & (m <= cut)) + a
        if len(after) == 0: continue
        last = after[-1]
        for k in after:
            up, dn = H[k] >= hi + TICK, L[k] <= lo - TICK
            if up and dn: break
            if up or dn:
                side = 1 if up else -1
                lvl = hi + TICK if up else lo - TICK
                e = (max(O[k], lvl) + TICK) if up else (min(O[k], lvl) - TICK)
                st = (lo if up else hi) if stop_mode == "full" else (hi + lo) / 2
                risk = abs(e - st)
                if risk < 1: break
                tg = e + side * rr * risk if rr else None
                xi, xp = walk(O, H, L, C, k, side, e, st, tg, last)
                if side == 1 or both:
                    rows.append((d.index[k], pnl(side, e, xp), risk + 2.0))
                break
    return pd.DataFrame(rows, columns=["time", "pnl", "risk"])
if __name__ == "__main__":
    for s, nm in ((3 * 60, "London 03:00"), (8 * 60 + 20, "COMEX 08:20"), (9 * 60 + 30, "NY 09:30")):
        for ln in (15, 30, 60):
            for sm in ("full", "half"):
                for rr in (None, 1.0, 2.0):
                    report(f"ORB {nm} {ln}m stop={sm} tgt={rr}", orb(s, ln, sm, rr))
