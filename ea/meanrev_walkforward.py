"""The same mean-reversion bot, but choosing settings WITHOUT hindsight."""
import csv
POINT, SPREAD = 0.01, 45.0
BAL0, RISK, MINLOT, USD = 100.0, 0.001, 0.01, 1.0

rows=list(csv.DictReader(open('/home/user/Trading-Bot/simulation/xauusd_m1_2026-01-07.csv')))
close=[float(r['close']) for r in rows]; high=[float(r['high']) for r in rows]; low=[float(r['low']) for r in rows]
n=len(close); mid=n//2

def bt(window, band, sl_pts, tp_pts, lo_i, hi_i):
    bal, w, l = BAL0, 0, 0
    i = max(lo_i, window)
    while i < hi_i-1:
        win = close[i-window:i]
        lo, hi = min(win), max(win); rng = hi-lo
        if rng<=0: i+=1; continue
        pos=(close[i]-lo)/rng
        side = 1 if pos<=band else (-1 if pos>=1-band else 0)
        if side==0: i+=1; continue
        lots=max(MINLOT, round(bal*RISK/(sl_pts*USD),2))
        entry=close[i]+(SPREAD*POINT/2 if side==1 else -SPREAD*POINT/2)
        tp=entry+side*tp_pts*POINT; sl=entry-side*sl_pts*POINT
        for j in range(i+1, hi_i):
            b,a = low[j]-SPREAD*POINT/2, high[j]+SPREAD*POINT/2
            if side==1:
                if b<=sl: bal-=sl_pts*USD*lots; l+=1; break
                if a>=tp: bal+=tp_pts*USD*lots; w+=1; break
            else:
                if a>=sl: bal-=sl_pts*USD*lots; l+=1; break
                if b<=tp: bal+=tp_pts*USD*lots; w+=1; break
        else: j=hi_i-1
        i=j+1
    return bal, w, l

GRID=[(wd,bd,sl,tp) for wd in (30,60,120) for bd in (.1,.2,.3)
      for sl,tp in ((150,150),(200,200),(300,300),(200,400))]

# pick the winner on the FIRST half only - no knowledge of the second
scored=sorted(((bt(*g, 0, mid)[0], g) for g in GRID), reverse=True)
best_bal, best = scored[0]
print(f"Chosen on the first half only (hours 0-2.9):")
print(f"  best setting: window {best[0]}, band {best[1]:.0%}, {best[2]}/{best[3]}")
print(f"  it made ${best_bal:.2f} there\n")

bal, w, l = bt(*best, mid, n)
t=w+l
print(f"Now trading the second half it never saw (hours 2.9-5.8):")
print(f"  ${bal:.2f} from $100, {t} trades, {100*w/t if t else 0:.0f}% wins")
print(f"  -> {'PROFIT' if bal>BAL0 else 'LOSS'} of ${abs(bal-BAL0):.2f}\n")

# how did every setting do in-sample vs out-of-sample?
ins=[]; outs=[]
for g in GRID:
    a=bt(*g,0,mid)[0]; b=bt(*g,mid,n)[0]
    ins.append(a); outs.append(b)
good_in=sum(1 for x in ins if x>BAL0); good_out=sum(1 for x in outs if x>BAL0)
print(f"Across all {len(GRID)} settings:")
print(f"  profitable on the half they were measured on : {good_in}/{len(GRID)}")
print(f"  profitable on the half they never saw        : {good_out}/{len(GRID)}")
print(f"  average result in-sample  : ${sum(ins)/len(ins):.2f}")
print(f"  average result out-of-sample: ${sum(outs)/len(outs):.2f}")

print(f"""
This is the whole lesson in two numbers. Picking the best setting from a table
you have already seen is not a strategy - it is reading yesterday's lottery
numbers. The 24% day from the previous test was that, and it did not survive
contact with data it had not been fitted to.

It also explains why manual trading can FEEL more profitable: a person remembers
the good day and tests nothing. The bot is held to a standard the discretionary
trader never applies to themselves.
""")
