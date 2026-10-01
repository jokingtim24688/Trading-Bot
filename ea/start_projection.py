"""CandleSenseStart on $100 at 1:100. Simulates the EA's real mechanics."""
import random, statistics

BAL0, LEV, GOLD = 100.0, 100, 4170.0
RISK_PCT, RR = 0.02, 2.5
MIN_STOP_PTS, MINLOT, LOTSTEP = 200.0, 0.01, 0.01
USD_PT = 1.0                      # $1 per point per lot on XAUUSD
TRADES_DAY, DAYS = 1.5, 252
BREAKEVEN = 1/(1+RR)

margin001 = GOLD*100*MINLOT/LEV
print(f"$100 at 1:100 on gold:")
print(f"  0.01 lots needs ${margin001:.2f} margin  -> {int(BAL0/margin001)} position(s) affordable")
print(f"  200pt stop at 0.01 lots = ${MIN_STOP_PTS*USD_PT*MINLOT:.2f} risk = "
      f"{MIN_STOP_PTS*USD_PT*MINLOT/BAL0:.1%} of $100 (the EA targets {RISK_PCT:.0%})")
print(f"  break-even win rate at 1:{RR} = {BREAKEVEN:.1%}\n")

def lots_for(bal):
    """What the EA's sizing actually produces - note the staircase at small balances."""
    want = bal*RISK_PCT/(MIN_STOP_PTS*USD_PT)
    return max(MINLOT, (int(want/LOTSTEP))*LOTSTEP)

print("The lot staircase (why growth is lumpy at $100):")
for b in (100, 150, 200, 300, 500, 1000, 2000):
    l = lots_for(b)
    print(f"  ${b:>5,} -> {l:.2f} lots, risking ${MIN_STOP_PTS*USD_PT*l:>6.2f} "
          f"({MIN_STOP_PTS*USD_PT*l/b:>5.1%} of balance)")

def run(winrate, seed, days=DAYS):
    r=random.Random(seed); bal=BAL0; peak=bal; dd=0
    for d in range(days):
        day_start, losses = bal, 0
        for _ in range(r.choice([1,1,2,2,3])):
            if bal < 50: return 0, dd              # EA's hard floor
            if losses >= 3: break                   # EA pauses after 3 straight losses
            if (day_start-bal) >= day_start*0.06: break   # EA's 6% daily limit
            l = lots_for(bal)
            risk = MIN_STOP_PTS*USD_PT*l
            if r.random() < winrate: bal += risk*RR; losses=0
            else:                    bal -= risk;   losses+=1
            peak=max(peak,bal); dd=max(dd,(peak-bal)/peak)
    return bal, dd

print(f"\n{'if it wins':>11} | {'vs break-even':>13} | {'median after 1yr':>17} | {'per day':>9} | {'worst dd':>9} | {'busted'}")
print("-"*82)
for wr in (0.25, 0.286, 0.32, 0.35, 0.40, 0.45):
    outs=[run(wr,s) for s in range(1000)]
    ends=sorted(o[0] for o in outs)
    med=statistics.median(ends)
    bust=sum(1 for e in ends if e==0)/1000
    dd=statistics.median(o[1] for o in outs)
    tag = "below" if wr<BREAKEVEN else "above"
    daily=(med/BAL0)**(1/DAYS)-1 if med>0 else -1
    print(f"{wr:>10.1%} | {tag:>8} {abs(wr-BREAKEVEN):>4.1%} | ${med:>16,.2f} | "
          f"${BAL0*daily:>8.2f} | {dd:>8.0%} | {bust:>5.1%}")

print(f"""
How to read this: the EA's break-even is {BREAKEVEN:.1%}. Each row is "what if the
strategy really wins this often". Nobody knows CandleSenseStart's true win rate
yet - that is exactly what the demo run is for.

  - below 28.6%  -> it bleeds, slowly, exactly as the maths says it must
  - around 32%   -> modest growth, a real but unspectacular account
  - 35-40%       -> the trend-pullback setup's realistic band if it works

Even the good rows are counted in tens of dollars, because 2% of $100 is $2.
That is not the strategy underperforming - it is what $100 buys. The same EA
and the same win rate on your $5M demo multiplies every figure by 50,000.
""")
