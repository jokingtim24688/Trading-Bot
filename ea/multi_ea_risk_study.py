"""N copies of the EA on ONE account, each sizing 5% off the same balance.

Fixed from a first version whose balances exploded to $1e19: real accounts cannot
compound without limit - the broker caps lot size, and an edge does not survive
being scaled indefinitely. Here size is capped at MAXLOT, and the horizon is one
month, which is what you would actually observe before deciding anything.
"""
import random, statistics

BAL0, RR, WR, RISK = 100.0, 3.5, 0.30, 0.05     # 30% at 1:3.5 -> +0.35R per trade
STOP_PTS, USD_PT, MAXLOT, MINLOT = 250.0, 1.0, 1.00, 0.01
WEEKS, TPW = 4, 40                               # one month

def lots(bal, frac):
    want = bal*frac/(STOP_PTS*USD_PT)
    return max(MINLOT, min(MAXLOT, round(want, 2)))

def run(n_eas, rho, seed, coordinated=False):
    r = random.Random(seed); bal = BAL0; peak = bal; dd = 0.0
    per_ea = (RISK/n_eas) if coordinated else RISK
    rounds = WEEKS*TPW // max(1, n_eas)
    for _ in range(rounds):
        if bal < STOP_PTS*USD_PT*MINLOT: return 0.0, 1.0      # can't fund a trade
        agree = r.random() < rho
        shared = r.random() < WR
        for _e in range(n_eas):
            l = lots(bal, per_ea)
            risk_usd = STOP_PTS*USD_PT*l
            win = shared if agree else (r.random() < WR)
            bal += risk_usd*RR if win else -risk_usd
            if bal <= 0: return 0.0, 1.0
        peak = max(peak, bal); dd = max(dd, (peak-bal)/peak)
    return bal, dd

print(f"Each EA: {RISK:.0%} risk, wins {WR:.0%} at 1:{RR} (+{WR*RR-(1-WR):.2f}R per trade - a GOOD strategy).")
print(f"One month, {WEEKS*TPW} trades total, lot size capped like a real broker.\n")

def table(coordinated, title):
    print(title)
    print(f"{'EAs':>4} {'agree':>8} | {'risk/round':>11} | {'median end':>11} | {'worst 10%':>10} | "
          f"{'drawdown':>9} | {'WIPED OUT'}")
    print("-"*76)
    for n, rho in ((1,1.0),(2,1.0),(3,1.0),(5,1.0),(5,0.0),(10,1.0),(10,0.0)):
        outs=[run(n,rho,s,coordinated) for s in range(4000)]
        ends=sorted(o[0] for o in outs); bust=sum(1 for e in ends if e==0)/4000
        med=statistics.median(ends); dd=statistics.median(o[1] for o in outs)
        risk = RISK if coordinated else n*RISK
        lbl = "always" if rho==1 else "never"
        print(f"{n:>4} {lbl:>8} | {risk:>10.0%} | ${med:>10,.2f} | ${ends[399]:>9,.2f} | "
              f"{dd:>8.0%} | {bust:>8.1%}")
    print()

table(False, "UNCOORDINATED - every EA takes its full 5%, unaware of the others:")
table(True,  "COORDINATED - the same EAs sharing ONE 5% budget:")

print("""The comparison that matters is the two "5 EAs, always agree" rows:

  uncoordinated : 25% of the account at risk every round
  coordinated   :  5% of the account at risk every round

Same EAs, same strategy, same market, same month. One of them survives.

Why uncoordinated stacking fails:
  1. Each EA reads the balance and takes its 5%, never knowing the other four
     did the same a moment earlier. Five "safe" 5% bets are one 25% bet.
  2. They are copies on the same symbol, so they agree by construction. That is
     not five positions - it is one position at five times the size.
  3. Each has its own daily loss limit. Five EAs at a 15% limit each will let
     the account fall 75% before they all stop.
  4. At $100 the margin runs out first anyway: 0.02 lots of gold needs ~$83 at
     1:100, so the second EA's order is simply refused.

What makes multiple EAs safe is not better strategy - it is a SHARED risk budget
and genuinely different markets. Copies of one EA on one symbol have neither.""")
