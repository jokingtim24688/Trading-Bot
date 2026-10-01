"""What happens to the bot as it trades more often, on real XAUUSD M1 data.

RESULT (run it yourself): losses scale linearly with trade frequency. On the real
2026-01-07 gold data, with the demo's own 45-point spread and the EA's 8%/60-trade
sizing on $5M, opening a trade every second loses $62.7M in 5.8 hours. At the
smallest lot MT5 allows (0.01) it still loses $14,115 in the same window.

Why: every trade pays the spread on entry. SL 150 / TP 200 needs a 42.9% win rate
to break even, but a 45-point spread drags a coin-flip bot down to 30%. The
strategy must supply that 12.9-point gap on EVERY trade. Trading more often does
not create edge - it just pays the spread more times.


Each M1 candle is replayed as 60 one-second ticks (open->low->high->close path).
A trade opens every N seconds in the swing direction, SL 150 / TP 200 points,
closed at the broker's bid/ask like the real EA.
"""
import csv, random, statistics

POINT = 0.01
SPREAD_PTS = 45.0        # the demo's real gold spread (38-70 seen in screenshots)
SL_PTS, TP_PTS = 150.0, 200.0
BALANCE = 5_000_000
RISK_PCT, MAX_OPEN = 8.0, 60
USD_PER_POINT_PER_LOT = 1.0     # XAUUSD: 100oz/lot, 0.01 move = $1

rows = list(csv.DictReader(open('/home/user/Trading-Bot/simulation/xauusd_m1_2026-01-07.csv')))
bars = [(float(r['open']), float(r['high']), float(r['low']), float(r['close'])) for r in rows]

def ticks():
    """Per-second mid prices walked through each candle's real OHLC path."""
    for o, h, l, c in bars:
        legs = [o, l, h, c] if abs(l-o) < abs(h-o) else [o, h, l, c]
        for i in range(3):
            a, b = legs[i], legs[i+1]
            for s in range(20):
                yield a + (b-a)*s/20

PRICES = list(ticks())
print(f"Real XAUUSD data: {len(bars)} M1 candles -> {len(PRICES)} seconds "
      f"({len(PRICES)/3600:.1f} h), range {min(PRICES):.2f}-{max(PRICES):.2f}")

def run(every_sec, lots):
    """Open a trade every `every_sec` seconds; each lives until SL or TP."""
    open_tr, closed, gross, spread_paid = [], 0, 0.0, 0.0
    for t, mid in enumerate(PRICES):
        bid, ask = mid - SPREAD_PTS*POINT/2, mid + SPREAD_PTS*POINT/2
        still = []
        for tr in open_tr:
            px = bid if tr['buy'] else ask
            hit_tp = px >= tr['tp'] if tr['buy'] else px <= tr['tp']
            hit_sl = px <= tr['sl'] if tr['buy'] else px >= tr['sl']
            if hit_tp or hit_sl:
                gross += (TP_PTS if hit_tp else -SL_PTS) * USD_PER_POINT_PER_LOT * lots
                closed += 1
            else:
                still.append(tr)
        open_tr = still
        if t % every_sec == 0 and len(open_tr) < MAX_OPEN:
            # direction = last 60s swing, the EA's logic
            buy = mid >= PRICES[max(0, t-60)]
            entry = ask if buy else bid
            open_tr.append({'buy': buy,
                            'sl': entry - SL_PTS*POINT if buy else entry + SL_PTS*POINT,
                            'tp': entry + TP_PTS*POINT if buy else entry - TP_PTS*POINT})
            spread_paid += SPREAD_PTS * USD_PER_POINT_PER_LOT * lots
    return closed, gross, spread_paid, len(open_tr)

lots_risk = (BALANCE * RISK_PCT/100 / MAX_OPEN) / (SL_PTS * USD_PER_POINT_PER_LOT)
print(f"\nYour current settings on $5M: {RISK_PCT}% risk / {MAX_OPEN} trades"
      f" = ${BALANCE*RISK_PCT/100/MAX_OPEN:,.0f} risk per trade = {lots_risk:.1f} lots per trade")
print(f"Spread cost of ONE trade at {lots_risk:.1f} lots: ${SPREAD_PTS*lots_risk:,.0f}\n")

print(f"{'opens every':>12} | {'trades/hr':>9} | {'closed':>6} | {'net P/L':>14} | {'spread paid':>14}")
print("-"*72)
for every in (300, 60, 30, 10, 5, 1):
    closed, gross, spread, still_open = run(every, lots_risk)
    net = gross - spread
    print(f"{every:>10}s | {3600/every:>9.0f} | {closed:>6} | ${net:>13,.0f} | ${spread:>13,.0f}")

print(f"\n--- same test at the smallest possible size (0.01 lots) ---")
print(f"{'opens every':>12} | {'closed':>6} | {'net P/L':>12} | {'spread paid':>12}")
print("-"*54)
for every in (300, 60, 10, 1):
    closed, gross, spread, _ = run(every, 0.01)
    print(f"{every:>10}s | {closed:>6} | ${gross-spread:>11,.2f} | ${spread:>11,.2f}")
