"""Buy low / sell high on real gold data, risking 0.1% per trade.

"Low" and "high" are measured against a rolling window: buy when price sits in the
bottom band of the last N candles, sell when it sits in the top band, close when it
returns to the middle. This is textbook mean reversion - the honest version of
"buy low, close high".
"""
import csv, statistics

POINT, SPREAD = 0.01, 45.0
BAL0, RISK = 100.0, 0.001          # 0.1% per trade
USD_PT_LOT, MINLOT = 1.0, 0.01

rows = list(csv.DictReader(open('/home/user/Trading-Bot/simulation/xauusd_m1_2026-01-07.csv')))
close = [float(r['close']) for r in rows]
high  = [float(r['high'])  for r in rows]
low   = [float(r['low'])   for r in rows]
n = len(close)
print(f"Real XAUUSD M1: {n} candles, {min(low):.2f}-{max(high):.2f} "
      f"({(max(high)-min(low))/POINT:.0f} points of range)\n")

def backtest(window, band, sl_pts, tp_pts, verbose=False):
    bal, wins, losses, spread_paid = BAL0, 0, 0, 0.0
    i = window
    while i < n-1:
        w = close[i-window:i]
        lo, hi = min(w), max(w)
        rng = hi - lo
        if rng <= 0: i += 1; continue
        pos = (close[i]-lo)/rng                    # 0 = at the low, 1 = at the high
        side = 1 if pos <= band else (-1 if pos >= 1-band else 0)
        if side == 0: i += 1; continue

        # size from 0.1% of balance; the minimum lot is a hard floor
        lots = max(MINLOT, round(bal*RISK/(sl_pts*USD_PT_LOT), 2))
        entry = close[i] + (SPREAD*POINT/2 if side==1 else -SPREAD*POINT/2)
        tp = entry + side*tp_pts*POINT
        sl = entry - side*sl_pts*POINT
        spread_paid += SPREAD*USD_PT_LOT*lots

        for j in range(i+1, n):
            b, a = low[j]-SPREAD*POINT/2, high[j]+SPREAD*POINT/2
            if side == 1:
                if b <= sl: bal -= sl_pts*USD_PT_LOT*lots; losses += 1; break
                if a >= tp: bal += tp_pts*USD_PT_LOT*lots; wins += 1; break
            else:
                if a >= sl: bal -= sl_pts*USD_PT_LOT*lots; losses += 1; break
                if b <= tp: bal += tp_pts*USD_PT_LOT*lots; wins += 1; break
        else:
            j = n-1
        i = j+1
    t = wins+losses
    return bal, wins, losses, t, spread_paid

print("Giving it a fair run across sensible settings (0.1% risk, real 45pt spread):\n")
print(f"{'window':>7} {'band':>6} {'stop':>6} {'target':>7} | {'trades':>7} {'win%':>6} | "
      f"{'end balance':>12} {'spread paid':>12}")
print("-"*78)
best = None
for window in (30, 60, 120):
    for band in (0.1, 0.2, 0.3):
        for sl, tp in ((150,150),(200,200),(300,300),(200,400)):
            bal, w, l, t, sp = backtest(window, band, sl, tp)
            if t < 3: continue
            if best is None or bal > best[0]: best = (bal, window, band, sl, tp, t, w)
            print(f"{window:>7} {band:>6.0%} {sl:>6} {tp:>7} | {t:>7} {100*w/t if t else 0:>5.0f}% | "
                  f"${bal:>11,.2f} ${sp:>11,.2f}")

bal, window, band, sl, tp, t, w = best
print(f"""
Best of all {3*3*4} settings: window {window}, band {band:.0%}, {sl}/{tp}
  -> ${bal:,.2f} from ${BAL0:.2f} over {n/60:.1f} hours, {t} trades, {100*w/t:.0f}% wins

And that is the BEST one, chosen with hindsight after seeing every result - the
single most optimistic number this data can produce. A setting picked in advance
would do worse.
""")

# what 0.1% per trade actually means at this balance
lots = max(MINLOT, round(BAL0*RISK/(200*USD_PT_LOT), 2))
print(f"The sizing problem at $100 with 0.1% risk:")
print(f"  0.1% of $100 = ${BAL0*RISK:.2f} intended risk per trade")
print(f"  but the smallest lot (0.01) with a 200pt stop risks ${200*USD_PT_LOT*MINLOT:.2f}")
print(f"  -> you are actually risking {200*USD_PT_LOT*MINLOT/BAL0:.1%}, not 0.1% - {200*USD_PT_LOT*MINLOT/(BAL0*RISK):.0f}x more.")
print(f"  0.1% risk only becomes real above ${200*USD_PT_LOT*MINLOT/RISK:,.0f}.")
