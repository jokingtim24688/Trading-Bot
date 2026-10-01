"""$5 per trade on $100 = 5% risk. What does bet size actually do?"""
import random, statistics

BAL0, RR, DAYS, TPD = 100.0, 2.5, 252, 1.5
BE = 1/(1+RR)        # 28.6% break-even at 1:2.5

def kelly(p, b=RR):
    """The mathematically optimal fraction to risk. Above this, returns FALL."""
    return max(0.0, (p*b - (1-p))/b)

print(f"At 1:{RR}, break-even is {BE:.1%}. The optimal bet size depends on the win rate:\n")
print(f"{'if it wins':>11} | {'full Kelly':>11} | {'half Kelly (safe)':>18} | {'$5 on $100 (5%) is...'}")
print("-"*74)
for wr in (0.30, 0.32, 0.35, 0.40, 0.45):
    k = kelly(wr)
    verdict = ("over-betting" if 0.05 > k else "under-betting" if 0.05 < k/2 else "about right")
    print(f"{wr:>10.1%} | {k:>10.1%} | {k/2:>17.1%} | {verdict} ({0.05/k:.1f}x Kelly)" if k>0
          else f"{wr:>10.1%} | {'no edge':>10} | {'-':>17} | any bet size loses")

def run(wr, risk, seed):
    r=random.Random(seed); bal=BAL0; peak=bal; dd=0.0
    for _ in range(int(DAYS*TPD)):
        if bal < 5: return 0.0, 1.0
        stake = bal*risk
        bal += stake*RR if r.random()<wr else -stake
        peak=max(peak,bal); dd=max(dd,(peak-bal)/peak)
    return bal, dd

for wr in (0.30, 0.35, 0.40):
    print(f"\n--- if the strategy really wins {wr:.0%} (Kelly says {kelly(wr):.1%}) ---")
    print(f"{'risk/trade':>11} {'$ on $100':>10} | {'median 1yr':>12} | {'worst 10%':>11} | "
          f"{'max drawdown':>13} | {'busted'}")
    print("-"*78)
    for risk in (0.01, 0.02, 0.05, 0.10, 0.20):
        outs=[run(wr,risk,s) for s in range(2000)]
        ends=sorted(o[0] for o in outs)
        med=statistics.median(ends); bust=sum(1 for e in ends if e==0)/2000
        dd=statistics.median(o[1] for o in outs)
        tag = "  <- $5 trades" if risk==0.05 else ""
        print(f"{risk:>10.0%} {BAL0*risk:>9.2f} | ${med:>11,.2f} | ${ends[199]:>10,.2f} | "
              f"{dd:>12.0%} | {bust:>5.1%}{tag}")

print(f"""
The shape to notice: returns rise with bet size, peak, then FALL - while the
drawdown keeps climbing. That peak is Kelly. Past it you are taking more risk
for less money, which is the worst trade available.

$5 per trade (5%) sits:
  - about right if the strategy truly wins 35%+
  - roughly 2.5x too big if it only wins 30%
and you do not yet know which, because CandleSenseStart has no live trades. That
is the real reason to start small: not timidity, but that bet size is a function
of an edge you have not measured.

Also note what 5% does to the ride even when it works: a ~{int(100*statistics.median([run(0.35,0.05,s)[1] for s in range(500)]))}% drawdown at a
winning 35%. Your $100 would spend part of the year looking like $60.
""")
