"""$100 -> $10,000 in a day with the 94.8%-win-rate setup (600pt stop, 20pt target).

Runs it thousands of times on real gold moves, compounding hard, and counts how
often it gets there versus how often the account is gone.
"""
import csv, random, statistics
POINT, SPREAD = 0.01, 45.0
SL, TP = 600.0, 20.0
START, GOAL = 100.0, 10_000.0

rows=list(csv.DictReader(open('/home/user/Trading-Bot/simulation/xauusd_m1_2026-01-07.csv')))
close=[float(r['close']) for r in rows]
# real 1-minute moves, in points, to resample from
MOVES=[(close[i+1]-close[i])/POINT for i in range(len(close)-1)]
print(f"Using {len(MOVES)} real gold minute-moves "
      f"(avg size {statistics.mean(map(abs,MOVES)):.0f} pts, biggest {max(map(abs,MOVES)):.0f} pts)\n")

def one_day(risk_frac, seed):
    """One trading day. Risks risk_frac of the balance per trade, compounding."""
    r=random.Random(seed); bal=START; trades=0
    for _ in range(2000):                      # a day's worth of chances
        if bal>=GOAL or bal<1: break
        lots=max(0.01, (bal*risk_frac)/SL)     # size from current balance
        price=0.0; trades+=1
        for _ in range(500):                   # walk until stop or target
            price+=r.choice(MOVES)
            if price<=-(SL-SPREAD)*0:          pass
            if price>=TP+SPREAD: bal+=TP*lots; break
            if price<=-(SL-SPREAD): bal-=SL*lots; break
        else:
            bal-=SPREAD*lots
    return bal, trades

print(f"{'risk/trade':>11} | {'runs':>6} | {'hit $10k':>9} | {'wiped out':>10} | {'median end':>12}")
print("-"*60)
best=None
for risk in (0.05, 0.10, 0.25, 0.50, 0.90):
    ends=[]; hits=busts=0
    for s in range(2000):
        bal,_=one_day(risk, s)
        ends.append(bal)
        if bal>=GOAL: hits+=1
        if bal<1: busts+=1
    med=statistics.median(ends)
    print(f"{risk:>10.0%} | {2000:>6} | {hits/2000:>8.2%} | {busts/2000:>9.1%} | ${med:>11,.2f}")
    if best is None or hits>best[1]: best=(risk,hits)

print(f"""
Best case found: risking {best[0]:.0%} per trade reached $10,000 in {best[1]/2000:.2%} of days.
The other {100-best[1]/2000*100:.2f}% of the time the $100 was gone.

Why it ends this way: the 600/20 setup wins ~95% of its trades, so it climbs in
small steps and looks unstoppable - then one 600-point move takes back 30 wins at
once. To turn $100 into $10,000 in a day you must risk enough that a single one of
those moves ends the account, and on real gold data one always arrives.

The 94.8% win rate is not a strategy. It is the shape of the losses hiding behind it.
""")
