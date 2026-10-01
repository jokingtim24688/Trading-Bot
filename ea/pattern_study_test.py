"""Does 'studying previous chart movements' create enough edge to beat the spread?

Strict walk-forward: learn patterns on the first 60% of the data, trade the last
40% having never seen it. No peeking - that's the only kind of test that counts.
"""
import csv, statistics
from collections import defaultdict

POINT, SPREAD = 0.01, 45.0
SL, TP = 150.0, 200.0
NEED = SL/(SL+TP)          # 42.9% win rate to break even on the money

rows = list(csv.DictReader(open('/home/user/Trading-Bot/simulation/xauusd_m1_2026-01-07.csv')))
close = [float(r['close']) for r in rows]
high  = [float(r['high'])  for r in rows]
low   = [float(r['low'])   for r in rows]
n = len(close)
split = int(n*0.6)
print(f"{n} M1 candles: learn on {split}, trade the {n-split} it has never seen.\n")

def pattern(i):
    """The 'study': shape of the last 3 candles, coded up/down/flat."""
    out = []
    for k in (3, 2, 1):
        d = close[i-k+1] - close[i-k]
        out.append('U' if d > 0.05 else 'D' if d < -0.05 else 'F')
    return ''.join(out)

# --- learn: what followed each pattern historically ---
stats = defaultdict(lambda: [0, 0])     # pattern -> [times up, total]
for i in range(3, split-5):
    nxt = close[i+5] - close[i]
    stats[pattern(i)][1] += 1
    if nxt > 0: stats[pattern(i)][0] += 1

print("What it learned (patterns with 10+ examples):")
learned = {}
for p, (up, tot) in sorted(stats.items()):
    if tot >= 10:
        rate = up/tot
        learned[p] = rate
        print(f"  after {p}: price rose {rate:5.1%} of {tot} times"
              + ("   <- leans UP" if rate > .55 else "   <- leans DOWN" if rate < .45 else ""))

# --- trade the unseen part using only what was learned ---
def trade(conf_min):
    wins = losses = skipped = 0
    for i in range(split, n-1):
        p = pattern(i)
        if p not in learned: skipped += 1; continue
        edge = learned[p] - 0.5
        if abs(edge) < conf_min: skipped += 1; continue
        buy = edge > 0
        entry = close[i] + (SPREAD*POINT/2 if buy else -SPREAD*POINT/2)
        tp = entry + TP*POINT if buy else entry - TP*POINT
        sl = entry - SL*POINT if buy else entry + SL*POINT
        for j in range(i+1, n):           # walk forward to whichever level hits first
            b, a = low[j]-SPREAD*POINT/2, high[j]+SPREAD*POINT/2
            if buy:
                if b <= sl: losses += 1; break
                if a >= tp: wins += 1; break
            else:
                if a >= sl: losses += 1; break
                if b <= tp: wins += 1; break
        else: skipped += 1
    return wins, losses, skipped

print(f"\nTrading the unseen 40%. Break-even needs {NEED:.1%} wins:")
print(f"{'min confidence':>15} | {'trades':>7} | {'win rate':>9} | {'verdict':>22}")
print("-"*62)
for conf in (0.00, 0.05, 0.10, 0.15):
    w, l, s = trade(conf)
    t = w + l
    if t == 0: print(f"{conf:>14.0%} | {0:>7} | {'-':>9} | {'no trades taken':>22}"); continue
    wr = w/t
    net = w*TP - l*SL
    print(f"{conf:>14.0%} | {t:>7} | {wr:>8.1%} | {('PROFIT +'+str(int(net))+'pt') if wr>=NEED else ('LOSS '+str(int(net))+'pt'):>22}")

print(f"""
Read it carefully: the pattern study DOES tilt the odds - but the question is
whether it tilts them past {NEED:.1%}, and by enough to pay 45 points of spread
on every single trade.

Also note the sample: {n} candles is 5.8 hours of one day. Patterns that look
strong here are mostly noise at this size. A real study needs months of M1 data
(the Train tab in your app can download it), and the result above would need to
hold across many separate weeks before it means anything.
""")
