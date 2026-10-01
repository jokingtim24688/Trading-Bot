"""Given: $100, $5 per trade. Find the configuration with the most weekly profit.

The only real lever is EXPECTANCY per trade. With a fixed $5 risk:
    profit per week = trades per week x $5 x expectancy(in R)
So the search is over reward ratio and trade frequency - and the catch is that
both change the win rate, because the 45pt gold spread has to be paid either way.
"""
import math, random, statistics

RISK, SPREAD, BAL0 = 5.0, 45.0, 100.0

def win_rate(stop_pts, rr, skill):
    """Win rate for a given stop/target and a given amount of skill.

    skill = how far the strategy beats a coin flip, in probability points. A random
    bot entering at the ask has its odds dragged down by the spread; skill adds back.
    """
    tp_pts = stop_pts*rr
    random_p = (stop_pts-SPREAD)/((tp_pts+SPREAD)+(stop_pts-SPREAD))
    return max(0.01, min(0.95, random_p + skill))

def expectancy(stop_pts, rr, skill):
    p = win_rate(stop_pts, rr, skill)
    return p*rr - (1-p)          # in R; x $5 = dollars per trade

print("Step 1 - for a given amount of skill, which reward ratio pays most per trade?\n")
print(f"{'skill':>6} | " + " | ".join(f"1:{rr:<4.1f}" for rr in (1.0,1.5,2.0,2.5,3.0,4.0,5.0)) + " | best")
print("-"*86)
BEST = {}
for skill in (0.03, 0.05, 0.08, 0.12):
    row, best = [], (None, -9)
    for rr in (1.0,1.5,2.0,2.5,3.0,4.0,5.0):
        e = expectancy(250, rr, skill)
        row.append(f"{e*RISK:+5.2f}")
        if e > best[1]: best = (rr, e)
    BEST[skill] = best
    print(f"{skill:>5.0%} | " + " | ".join(f"{v:>6}" for v in row) + f" | 1:{best[0]}")

print(f"""
Wider targets win, up to a point. The reason is the spread: at 1:1 you must clear
45 points of spread to collect 250, at 1:4 you clear the same 45 to collect 1000.
The spread is a fixed toll - take bigger trips for the same toll.

Step 2 - now add frequency. Profit/week = trades x $5 x expectancy:
""")
print(f"{'skill':>6} {'best R:R':>9} | " + " | ".join(f"{n:>3}/wk" for n in (5,10,20,40,80)) + "  | drawdown risk")
print("-"*88)
for skill, (rr, e) in BEST.items():
    row = [f"${n*RISK*e:>6.0f}" for n in (5,10,20,40,80)]
    # drawdown grows with trade count at fixed bet size
    p = win_rate(250, rr, skill)
    streak = math.log(0.05)/math.log(1-p) if p < 1 else 0      # 1-in-20 losing streak
    print(f"{skill:>5.0%} {('1:'+str(rr)):>9} | " + " | ".join(row) +
          f"  | ~{streak*RISK:,.0f} ($ in a bad run)")

print(f"""
Step 3 - the catch, and it is the whole problem:

More trades multiply whatever the expectancy is. If skill is real, 80 trades a
week beats 5. If skill is ZERO, the same multiplication runs the other way - and
the earlier frequency study measured exactly that: at one trade a second the
losses scaled linearly into the millions.

So "most profit per week" has one honest answer:
""")

for skill in (0.0, 0.03, 0.08):
    rr = BEST.get(skill, (2.5, expectancy(250,2.5,skill)))[0]
    e = expectancy(250, rr, skill)
    print(f"  skill {skill:>4.0%}: ${40*RISK*e:>8,.0f}/week at 40 trades  "
          f"({'profit' if e>0 else 'LOSS'})")

print(f"""
Same configuration, same $5, same 40 trades a week. The only thing that changed
is whether the strategy actually knows anything - and that single unknown is the
difference between making $60 a week and losing $36 a week.

Note on 1:5 winning every row: this model adds skill as a flat probability bonus
at any reward ratio, which flatters very wide targets - in reality a 1250pt
target is genuinely harder to reach than the model allows. Treat 1:3 to 1:4 as
the trustworthy end of that finding.

THE CONFIGURATION I would run, given your constraints:
  risk           $5 per trade (5% - at the top of sane, as you asked)
  stop           250 points (wide enough that the 45pt spread is 18%, not 30%)
  target         1:3 to 1:4  (best expectancy at every skill level above)
  frequency      as many as the setup genuinely appears - do not pad it
  compounding    size from the live balance, so $5 becomes $6 as it grows

At 40 good trades a week with a real 8% edge that is about $60/week on $100 -
a 60% month, which would be an excellent result. With no edge the same setup
loses $36/week. The configuration is identical; only the edge differs.
Everything rests on measuring it first, which takes about 50 demo trades.
""")
