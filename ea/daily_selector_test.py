"""Does picking the best-performing strategy carry over to the next period?

That is the whole premise of "find the best performing one every day". If the
winner of period N is no better than random in period N+1, the selector is just
chasing noise - and will reliably pick the strategy about to stop working.
"""
import csv
POINT, SPREAD = 0.01, 45.0
rows = list(csv.DictReader(open('/home/user/Trading-Bot/simulation/xauusd_m1_2026-01-07.csv')))
close=[float(r['close']) for r in rows]; high=[float(r['high']) for r in rows]; low=[float(r['low']) for r in rows]

# a family of plausible strategies: (lookback for direction, stop, target)
STRATS = [(3,150,200),(3,200,100),(5,150,200),(5,100,300),(10,150,200),
          (10,300,60),(20,150,200),(20,200,100),(30,150,200),(30,100,300)]

def run(sid, lo, hi_):
    look, sl, tp = STRATS[sid]
    pnl=0.0; t=0
    for i in range(max(lo,look+1), hi_-1, 3):
        buy = close[i] > close[i-look]
        e = close[i] + (SPREAD*POINT/2 if buy else -SPREAD*POINT/2)
        TPp = e+tp*POINT if buy else e-tp*POINT
        SLp = e-sl*POINT if buy else e+sl*POINT
        for j in range(i+1, hi_):
            b,a = low[j]-SPREAD*POINT/2, high[j]+SPREAD*POINT/2
            if buy:
                if b<=SLp: pnl-=sl; t+=1; break
                if a>=TPp: pnl+=tp; t+=1; break
            else:
                if a>=SLp: pnl-=sl; t+=1; break
                if b<=TPp: pnl+=tp; t+=1; break
    return pnl, t

n=len(close); segs=6; size=n//segs
print(f"Split the day into {segs} periods of ~{size} minutes. Rank all "
      f"{len(STRATS)} strategies in each.\n")

ranks=[]
for s in range(segs):
    lo, hi_ = s*size, (s+1)*size
    scores = sorted(((run(i,lo,hi_)[0], i) for i in range(len(STRATS))), reverse=True)
    ranks.append([i for _,i in scores])
    best = scores[0]
    print(f"  period {s+1}: best was strategy #{best[1]} ({best[0]:+.0f} pts)")

print("\nNow the real question - did each period's winner stay good?\n")
print(f"{'picked after':>13} | {'strategy':>9} | {'next period rank':>17} | {'result'}")
print("-"*62)
carried = 0
for s in range(segs-1):
    champ = ranks[s][0]
    nxt_rank = ranks[s+1].index(champ)+1
    pnl,_ = run(champ, (s+1)*size, (s+2)*size)
    ok = nxt_rank <= 3
    carried += ok
    print(f"{'period '+str(s+1):>13} | {'#'+str(champ):>9} | {str(nxt_rank)+' of '+str(len(STRATS)):>17} | "
          f"{pnl:+.0f} pts {'(held up)' if ok else '(fell off)'}")

avg = sum(ranks[s+1].index(ranks[s][0])+1 for s in range(segs-1))/(segs-1)
print(f"""
The winner's average rank next period: {avg:.1f} out of {len(STRATS)}.
Pure chance would be {(len(STRATS)+1)/2:.1f}.

{'Picking the recent winner carried over.' if avg < (len(STRATS)+1)/2 - 1.5 else
 'Picking the recent winner did NOT carry over - it landed near random.'}

This is the classic trap in "use whatever worked yesterday": strategy
performance mean-reverts. The one that just had a hot streak is often the one
whose market conditions just ended. Selecting on a single day of results picks
noise; you need many weeks per candidate before a ranking means anything.
""")
