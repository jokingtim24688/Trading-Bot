"""Chasing the highest win rate: what it actually does to the money."""
import csv
POINT, SPREAD = 0.01, 45.0
rows = list(csv.DictReader(open('/home/user/Trading-Bot/simulation/xauusd_m1_2026-01-07.csv')))
close=[float(r['close']) for r in rows]; high=[float(r['high']) for r in rows]; low=[float(r['low']) for r in rows]
n=len(close)

def test(sl, tp, step=3):
    w=l=0; pnl=0.0
    for i in range(3, n-1, step):
        buy = close[i] > close[i-3]
        e = close[i] + (SPREAD*POINT/2 if buy else -SPREAD*POINT/2)
        TPp = e + tp*POINT if buy else e - tp*POINT
        SLp = e - sl*POINT if buy else e + sl*POINT
        for j in range(i+1, n):
            b,a = low[j]-SPREAD*POINT/2, high[j]+SPREAD*POINT/2
            if buy:
                if b<=SLp: l+=1; pnl-=sl; break
                if a>=TPp: w+=1; pnl+=tp; break
            else:
                if a>=SLp: l+=1; pnl-=sl; break
                if b<=TPp: w+=1; pnl+=tp; break
    t=w+l
    return (w/t if t else 0), pnl, t

print("Same bot, same data, only the stop/target changed:\n")
print(f"{'stop':>6} {'target':>7} | {'WIN RATE':>9} | {'net points':>11} | {'verdict'}")
print("-"*58)
for sl, tp in [(600,20),(400,40),(300,60),(200,100),(150,200),(100,300),(60,400)]:
    wr, pnl, t = test(sl,tp)
    v = "money UP" if pnl>0 else "money DOWN"
    star = "  <-- highest win rate" if sl==600 else ""
    print(f"{sl:>6} {tp:>7} | {wr:>8.1%} | {pnl:>11,.0f} | {v}{star}")

print("""
That top row is the trap. A 600-point stop with a 20-point target wins most of
its trades - it looks like a world-class bot on the HUD - and still bleeds,
because the rare loss wipes out dozens of wins. Every blown-up martingale and
grid bot ever sold had a 90%+ win rate right up until the day it didn't.

What actually decides whether you make money:
    expectancy = (win rate x average win) - (loss rate x average loss)
A 35% win rate at 1:3 beats a 90% win rate at 30:1. The HUD should be judged on
Subtotal, not on the win rate line.
""")
