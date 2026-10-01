"""$100 at 1:100 leverage on gold. What leverage does and doesn't change."""
import random, statistics

GOLD, LEV, BAL = 4170.0, 100, 100.0
MIN_LOT, USD_PT, SL_PTS = 0.01, 1.0, 150.0
margin_per_001 = GOLD*100*MIN_LOT/LEV
risk_per_001   = SL_PTS*USD_PT*MIN_LOT

print(f"Gold ${GOLD:,.0f}/oz, 1:{LEV} leverage, ${BAL:.0f} balance\n")
print(f"  0.01 lots = {100*MIN_LOT:.0f} oz = ${GOLD*100*MIN_LOT:,.0f} of gold")
print(f"  margin to hold it      : ${margin_per_001:,.2f}  <- what leverage controls")
print(f"  loss if the 150pt stop hits: ${risk_per_001:,.2f}  <- leverage does NOT change this")
print(f"\n  So with ${BAL:.0f} you can hold {int(BAL/margin_per_001)} position(s) at once,")
print(f"  and each one risks ${risk_per_001:.2f} = {risk_per_001/BAL:.1%} of the account.")

print(f"""
This is the part worth getting straight: raising leverage from 1:100 to 1:500
would let you open 5x more positions, but each stop-out still costs the same
${risk_per_001:.2f}. Leverage buys you POSITION SIZE, not profit. The reason $25 failed
earlier was never leverage - it was that $1.50 is 6% of $25 but only 1.5% of $100.
""")

print(f"At ${BAL:.0f}, risking {risk_per_001/BAL:.1%} per trade is proper risk. Here is what that earns:\n")
print(f"{'daily return':>13} | {'per day':>9} | {'after 1 month':>14} | {'after 1 year':>13} | {'after 3 years':>14}")
print("-"*74)
for r in (0.001, 0.002, 0.005, 0.01):
    lbl = {0.001:"0.1% steady",0.002:"0.2% good",0.005:"0.5% excellent",0.01:"1% elite"}[r]
    print(f"{lbl:>13} | ${BAL*r:>8.2f} | ${BAL*(1+r)**21:>13,.2f} | ${BAL*(1+r)**252:>12,.2f} | ${BAL*(1+r)**756:>13,.2f}")

def run(start, daily, risk, days, seed):
    rnd=random.Random(seed); bal=start
    for d in range(days):
        if bal < risk_per_001: return 0.0
        bal *= (1 + rnd.gauss(daily, risk*1.8))
        if bal<=0: return 0.0
    return bal

print(f"\nSimulated 500 times with real day-to-day swings (0.2%/day edge, {risk_per_001/BAL:.1%} risk):\n")
print(f"{'horizon':>10} | {'median':>11} | {'worst 10%':>11} | {'best 10%':>11} | {'busted'}")
print("-"*62)
for days,lbl in ((21,"1 month"),(126,"6 months"),(252,"1 year"),(756,"3 years")):
    ends=sorted(run(BAL,0.002,risk_per_001/BAL,days,s) for s in range(500))
    bust=sum(1 for e in ends if e==0)/500
    print(f"{lbl:>10} | ${statistics.median(ends):>10,.2f} | ${ends[49]:>10,.2f} | ${ends[449]:>10,.2f} | {bust:>5.1%}")

print(f"""
So: ${BAL:.0f} at 1:100 is a real, survivable account - unlike $25. But the daily
number is ${BAL*0.002:.2f}, because 0.2% of $100 is 20 cents. Compounding is doing its
job; it is just starting from $100.

To reach $10,000/day you need the balance, not more leverage or more trades:
   $10,000/day at 0.2%/day = ${10000/0.002:,.0f} of capital.
Your $5M demo is already there. A $100 live account and a $5M demo are the same
bot - only the zeroes differ.
""")
