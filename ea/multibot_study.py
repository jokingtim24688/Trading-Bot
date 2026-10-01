"""Does running more bots make more money? It depends entirely on correlation."""
import random, statistics, math

DAYS, START = 252, 100.0
EDGE = 0.002          # each bot: 0.2%/day average
VOL  = 0.02           # with 2%/day swing

def run_portfolio(n, rho, seed, scale_to_same_risk=False):
    """n bots, pairwise correlation rho. Each risks 1/n of the account unless we
    deliberately scale back up to the same total risk a single bot would take."""
    r = random.Random(seed)
    bal = START
    # if uncorrelated, n bots at 1/n size swing less; scaling restores the risk budget
    port_vol_factor = math.sqrt((1 + (n-1)*rho) / n)
    size = (1/port_vol_factor) if scale_to_same_risk else 1.0
    for _ in range(DAYS):
        common = r.gauss(0, 1)                       # the shared market move
        tot = 0.0
        for _b in range(n):
            own = r.gauss(0, 1)                      # this bot's own idea
            z = math.sqrt(rho)*common + math.sqrt(1-rho)*own
            tot += (EDGE + VOL*z) / n                # each bot runs 1/n of the money
        bal *= (1 + tot*size)
        if bal <= 1: return 0.0
    return bal

def report(title, scale):
    print(f"\n{title}")
    print(f"{'bots':>5} | {'correlation':>12} | {'median after 1yr':>17} | {'worst 10%':>11} | {'swing':>8}")
    print("-"*68)
    for n, rho in ((1,0.0),(3,1.0),(3,0.7),(3,0.3),(3,0.0),(10,1.0),(10,0.3),(10,0.0)):
        ends = sorted(run_portfolio(n, rho, s, scale) for s in range(2000))
        med = statistics.median(ends)
        lbl = "(single bot)" if n==1 else ("identical" if rho==1 else f"{rho:.0%}")
        vol = statistics.pstdev(ends)
        print(f"{n:>5} | {lbl:>12} | ${med:>16,.2f} | ${ends[199]:>10,.2f} | ${vol:>7,.0f}")

report("A. Same total money, split between the bots (each runs 1/n of the account):", False)
report("B. Same again, but risk scaled back up to what ONE bot would have taken:", True)

print(f"""
What this says:

A) Splitting the money between correlated bots changes almost nothing. Three bots
   on gold with similar models ARE one bot - they see the same candles and reach
   the same conclusion. You get the same return with the same swings, minus the
   extra spread each one pays.

   Splitting between UNCORRELATED bots doesn't raise the return either - but look
   at the swing column: it falls hard. Same money, steadier ride.

B) That steadiness is the prize, because you can spend it. Running the same risk
   across n uncorrelated bots lets each take a bigger position for the same total
   wobble - and THAT is where the extra return comes from. At correlation 0 the
   gain is roughly sqrt(n): 3 bots ~1.7x, 10 bots ~3.2x.

   At correlation 1.0 (identical bots) scaling up just multiplies the risk. Same
   shape, bigger numbers, nothing gained.

So: more bots pay you only to the extent they DISAGREE. Three gold bots with the
same model is one bot wearing three hats. Three bots on gold, an index and a
currency is a portfolio.
""")
