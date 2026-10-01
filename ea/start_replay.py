"""Replay CandleSenseStart's exact rules on real XAUUSD 15-minute candles.

Data: getdata-finance/xauusd-15m-ohlcv-metals-historical-data (free sample, real gold,
2026-03-26 to 2026-09-25, UTC). Download it next to this file as XAUUSD_15m.csv, or pass
a path: python ea/start_replay.py path/to/XAUUSD_15m.csv [risk_percent]

Mirrors CandleSenseStart.mq5 v1.11 rule for rule:
  trend    H1 EMA50 vs EMA200 on the last CLOSED hour
  setup    last closed M15 bar dipped to the EMA20 and closed back with the trend,
           and the bar before it closed on the other side
  entry    at the open of the next bar (the EA checks once per new M15 bar)
  stop     max(ATR14 x 1.5, 250 points), target 3.5x the stop
  manage   at 1R: stop to entry + 10 pts, then trail at ATR x 2
  sizing   5% of balance; if even 0.01 lots would risk over 1.5x that, the trade is skipped
  limits   one trade at a time, London/NY hours 07-20 GMT on weekdays, stop for the day
           after -15% or 3 losses in a row, halt under $50
  costs    45-point spread (the demo's real gold spread), paid on every entry

Where a candle touches both the stop and the target, the stop is assumed first - the
replay errs against the EA, never for it.
"""
import csv
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

PATH = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).with_name("XAUUSD_15m.csv"))
RISK = float(sys.argv[2]) / 100 if len(sys.argv) > 2 else 0.05
START = 100.0
SPREAD = 0.45                     # $ per oz = 45 points
OZ_PER_LOT, MINLOT, STEP, LEV = 100, 0.01, 0.01, 100
ATR_MULT, MIN_STOP, RR, MAX_SPREAD_VS_STOP = 1.5, 2.50, 3.5, 0.25
BE_R, BE_LOCK, TRAIL_MULT = 1.0, 0.10, 2.0
DAILY_LOSS, PAUSE_AFTER, FLOOR = 0.15, 3, 50.0
SESSION = (7, 20)


def ema(values, n):
    out, k, e = [], 2 / (n + 1), None
    for v in values:
        e = v if e is None else e + k * (v - e)
        out.append(e)
    return out


def load(path):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            t = datetime.fromisoformat(r["datetime"]).astimezone(timezone.utc)
            rows.append((t, float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])))
    return rows


bars = load(PATH)
T = [b[0] for b in bars]; O = [b[1] for b in bars]; H = [b[2] for b in bars]
L = [b[3] for b in bars]; C = [b[4] for b in bars]
n = len(bars)

# M15 indicators
ema20 = ema(C, 20)
tr = [H[0] - L[0]] + [max(H[i] - L[i], abs(H[i] - C[i - 1]), abs(L[i] - C[i - 1])) for i in range(1, n)]
atr = [sum(tr[max(0, i - 13):i + 1]) / min(14, i + 1) for i in range(n)]   # iATR = SMA of true range

# H1 closes built from the M15 bars, then EMA50/200 on them
hour_key = [t.replace(minute=0, second=0) for t in T]
h1_close, h1_index = {}, []
for i, k in enumerate(hour_key):
    h1_close[k] = C[i]
keys = sorted(h1_close)
e50 = dict(zip(keys, ema([h1_close[k] for k in keys], 50)))
e200 = dict(zip(keys, ema([h1_close[k] for k in keys], 200)))
pos_of = {k: j for j, k in enumerate(keys)}


def trend_at(i):
    """Bias from the last CLOSED hour before bar i opens."""
    j = pos_of[hour_key[i]] - 1
    if j < 200:
        return 0                          # not enough hours for EMA200 yet
    k = keys[j]
    return 1 if e50[k] > e200[k] else -1


bal, peak, maxdd = START, START, 0.0
day, day_start, streak, halted = None, START, 0, False
pos = None
log, weekly = [], defaultdict(float)
wins = losses = skipped = 0
first_tradeable = None

for i in range(2, n):
    t = T[i]
    if t.date() != day:
        day, day_start, streak = t.date(), bal, 0

    # ---- manage the open trade on this bar ----
    if pos:
        buy = pos["side"] == 1
        lo_px = L[i] if buy else L[i] + SPREAD          # longs exit at bid, shorts at ask
        hi_px = H[i] if buy else H[i] + SPREAD
        hit_sl = lo_px <= pos["sl"] if buy else hi_px >= pos["sl"]
        hit_tp = hi_px >= pos["tp"] if buy else lo_px <= pos["tp"]
        if hit_sl or hit_tp:
            px = pos["sl"] if hit_sl else pos["tp"]          # stop first if both
            pnl = (px - pos["entry"]) * pos["side"] * OZ_PER_LOT * pos["lots"]
            bal += pnl
            weekly[t.strftime("%G-W%V")] += pnl
            kind = "TP" if hit_tp and not hit_sl else ("BE/trail" if pnl >= 0 else "SL")
            if pnl >= 0:
                wins += 1; streak = 0
            else:
                losses += 1; streak += 1
            log.append(f"{t:%m-%d %H:%M}  close {'BUY ' if buy else 'SELL'} {kind:<8} {pnl:+8.2f}  bal ${bal:8.2f}")
            pos = None
        else:
            r = ((H[i] - pos["entry"]) if buy else (pos["entry"] - (L[i] + SPREAD))) / pos["risk"]
            if r >= BE_R:
                be = pos["entry"] + BE_LOCK * pos["side"]
                trail = (H[i] - atr[i] * TRAIL_MULT) if buy else (L[i] + SPREAD + atr[i] * TRAIL_MULT)
                new = max(be, trail) if buy else min(be, trail)
                if (buy and new > pos["sl"]) or (not buy and new < pos["sl"]):
                    pos["sl"] = new
    peak = max(peak, bal); maxdd = max(maxdd, (peak - bal) / peak)

    # ---- the EA's entry check, once per new bar ----
    if halted or pos:
        continue
    if bal < FLOOR:
        halted = True
        log.append(f"{t:%m-%d %H:%M}  STOPPED: balance under ${FLOOR:.0f}")
        continue
    if (day_start - bal) >= day_start * DAILY_LOSS or streak >= PAUSE_AFTER:
        continue
    if t.weekday() >= 5 or not (SESSION[0] <= t.hour < SESSION[1]):
        continue
    bias = trend_at(i)
    if bias == 0:
        continue
    if first_tradeable is None:
        first_tradeable = t

    a = atr[i - 1]
    stop = max(a * ATR_MULT, MIN_STOP)
    if SPREAD > stop * MAX_SPREAD_VS_STOP:
        continue
    e1, e2 = ema20[i - 1], ema20[i - 2]
    c1, c2, l1, h1 = C[i - 1], C[i - 2], L[i - 1], H[i - 1]
    if bias == 1 and not (l1 <= e1 and c1 > e1 and c2 <= e2):
        continue
    if bias == -1 and not (h1 >= e1 and c1 < e1 and c2 >= e2):
        continue

    entry = O[i] + (SPREAD if bias == 1 else 0.0)
    risk_usd = bal * RISK
    lots = max(MINLOT, int(risk_usd / (stop * OZ_PER_LOT) / STEP) * STEP)
    if stop * OZ_PER_LOT * lots > risk_usd * 1.5:      # v1.11: min lot too big for this account
        skipped += 1
        continue
    if entry * OZ_PER_LOT * lots / LEV > bal:
        log.append(f"{t:%m-%d %H:%M}  skip: not enough margin for {lots:.2f} lots")
        continue
    pos = {"side": bias, "entry": entry, "lots": lots, "risk": stop,
           "sl": entry - stop * bias, "tp": entry + stop * RR * bias}
    log.append(f"{t:%m-%d %H:%M}  OPEN  {'BUY ' if bias == 1 else 'SELL'} {lots:.2f} lots @ {entry:8.2f}"
               f"  stop {stop/0.01:4.0f}pts  risking ${stop*OZ_PER_LOT*lots:5.2f}")

days = (T[-1] - first_tradeable).days if first_tradeable else 0
trades = wins + losses
print(f"Real gold, {n} M15 candles, {T[0]:%Y-%m-%d} to {T[-1]:%Y-%m-%d}")
print(f"EMA200 on H1 needs 200 hours of history, so the replay could first trade on "
      f"{first_tradeable:%Y-%m-%d}. (Live in MT5 that history is already loaded - no wait.)")
print(f"Risk {RISK:.0%} per trade, $100 start, 45-point spread.\n")
print("First 25 things it did:")
for line in log[:25]:
    print("  " + line)
print(f"  ... ({len(log)} log lines in total)\n")
print(f"Trades: {trades}   wins (incl. break-even/trail exits >= 0): {wins}   losses: {losses}   "
      f"win rate {100 * wins / trades if trades else 0:.0f}%")
print(f"Setups skipped because the smallest lot would risk too much: {skipped}")
print(f"Balance: ${START:,.2f} -> ${bal:,.2f}   ({(bal / START - 1) * 100:+.0f}%)   worst drawdown {maxdd:.0%}"
      f"   over {days} days")
print("\nWeek by week:")
for w in sorted(weekly):
    print(f"  {w}: {weekly[w]:+8.2f}")
