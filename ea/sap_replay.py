"""Replay SmallAccountPro.mq5's rules on real XAUUSD 15-minute candles (ea/XAUUSD_15m.csv).

The EA is meant for M1/M5; only M15 real data is available here, so this is an
approximation on a slower chart. Mirrors: EMA21/50/200 regime, pullback to EMA21 or the
middle band, RSI band + slope, ATR stop clamped to 100-500 points, TP = 1.8x, lots rounded
up to risk >= $5 then shrunk to fit 80% of free margin (1:100), break-even at +$2.50
locking +$0.50, $1.50 trail from +$4.00, -$15 daily breaker, 45-point spread. When a
candle touches both stop and target the stop is assumed first.

    python ea/sap_replay.py [csv] [start_balance] [leverage]
"""
import csv
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

PATH = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).with_name("XAUUSD_15m.csv"))
START = float(sys.argv[2]) if len(sys.argv) > 2 else 100.0
LEV = float(sys.argv[3]) if len(sys.argv) > 3 else 100.0

SPREAD, PT, OZ = 0.45, 0.01, 100           # $ spread, $ per point, oz per lot ($100 per $1 move per lot)
MIN_RISK, RR = 5.0, 1.8
MIN_SL, MAX_SL, ATR_MULT = 100 * PT, 500 * PT, 1.5
MARGIN_SHARE, MINLOT, STEP = 0.80, 0.01, 0.01
BE_TRIG, BE_LOCK, TR_START, TR_STEP = 2.50, 0.50, 4.00, 1.50
DAILY_LOSS = 15.0
TOUCH, SLOPE = 0.10, 0.05


def ema(v, n):
    k, e, out = 2 / (n + 1), None, []
    for x in v:
        e = x if e is None else e + k * (x - e)
        out.append(e)
    return out


def rsi(c, n=14):
    out, ag, al = [50.0] * len(c), 0.0, 0.0
    for i in range(1, len(c)):
        g, l = max(c[i] - c[i - 1], 0), max(c[i - 1] - c[i], 0)
        if i <= n:
            ag += g / n; al += l / n
        else:
            ag = (ag * (n - 1) + g) / n; al = (al * (n - 1) + l) / n
        out[i] = 100 - 100 / (1 + ag / al) if al > 0 else 100.0
    return out


rows = list(csv.DictReader(open(PATH)))
T = [datetime.fromisoformat(r["datetime"]).astimezone(timezone.utc) for r in rows]
O, H, L, C = ([float(r[k]) for r in rows] for k in ("open", "high", "low", "close"))
n = len(C)
e21, e50, e200, R = ema(C, 21), ema(C, 50), ema(C, 200), rsi(C)
mid = [sum(C[max(0, i - 19):i + 1]) / len(C[max(0, i - 19):i + 1]) for i in range(n)]
sd = [math.sqrt(sum((x - mid[i]) ** 2 for x in C[max(0, i - 19):i + 1]) / len(C[max(0, i - 19):i + 1])) for i in range(n)]
up = [mid[i] + 2 * sd[i] for i in range(n)]
lo = [mid[i] - 2 * sd[i] for i in range(n)]
tr = [H[0] - L[0]] + [max(H[i] - L[i], abs(H[i] - C[i - 1]), abs(L[i] - C[i - 1])) for i in range(1, n)]
atr = [sum(tr[max(0, i - 13):i + 1]) / len(tr[max(0, i - 13):i + 1]) for i in range(n)]

bal, peak, mdd = START, START, 0.0
pos, day, day_pnl = None, None, 0.0
wins = losses = 0
weekly, risks, log = defaultdict(float), [], []

for i in range(202, n):
    if T[i].date() != day:
        day, day_pnl = T[i].date(), 0.0
    if pos:
        b = pos["side"]
        hi_x = H[i] if b == 1 else H[i] + SPREAD          # longs exit at bid, shorts at ask
        lo_x = L[i] if b == 1 else L[i] + SPREAD
        hit_sl = lo_x <= pos["sl"] if b == 1 else hi_x >= pos["sl"]
        hit_tp = hi_x >= pos["tp"] if b == 1 else lo_x <= pos["tp"]
        if hit_sl or hit_tp:
            px = pos["sl"] if hit_sl else pos["tp"]
            pnl = (px - pos["entry"]) * b * OZ * pos["lots"]
            bal += pnl; day_pnl += pnl; weekly[T[i].strftime("%G-W%V")] += pnl
            wins += pnl > 0; losses += pnl <= 0
            pos = None
        else:
            per = OZ * pos["lots"]                         # $ per $1 move
            best = (H[i] - pos["entry"]) if b == 1 else (pos["entry"] - (L[i] + SPREAD))
            fav = H[i] if b == 1 else L[i] + SPREAD
            if best * per >= BE_TRIG:
                pos["sl"] = max(pos["sl"], pos["entry"] + BE_LOCK / per) if b == 1 else min(pos["sl"], pos["entry"] - BE_LOCK / per)
            if best * per >= TR_START:
                t = fav - TR_STEP / per * b
                pos["sl"] = max(pos["sl"], t) if b == 1 else min(pos["sl"], t)
    peak = max(peak, bal); mdd = max(mdd, (peak - bal) / peak)
    if pos or day_pnl <= -DAILY_LOSS or bal <= 0:
        continue

    j = i - 1                                              # the last closed bar
    a, c = atr[j], C[j]
    low12, high12 = min(L[j], L[j - 1]), max(H[j], H[j - 1])
    bull = e21[j] > e50[j] and (c > e200[j] or e21[j] - e21[j - 1] > a * SLOPE)
    bear = e21[j] < e50[j] and (c < e200[j] or e21[j - 1] - e21[j] > a * SLOPE)
    bull = bull and (low12 <= e21[j] + a * TOUCH or low12 <= mid[j] + a * TOUCH) and low12 >= lo[j] - a * TOUCH and c > e21[j]
    bear = bear and (high12 >= e21[j] - a * TOUCH or high12 >= mid[j] - a * TOUCH) and high12 <= up[j] + a * TOUCH and c < e21[j]
    bull = bull and 45 <= R[j] <= 68 and R[j] > R[j - 1]
    bear = bear and 32 <= R[j] <= 55 and R[j] < R[j - 1]
    if not (bull or bear):
        continue

    side = 1 if bull else -1
    entry = O[i] + (SPREAD if side == 1 else 0.0)
    sl_d = min(max(a * ATR_MULT, MIN_SL), MAX_SL)
    lots = max(MINLOT, math.ceil(MIN_RISK / (sl_d * OZ) / STEP - 1e-9) * STEP)
    while lots > MINLOT + 1e-9 and entry * OZ * lots / LEV > bal * MARGIN_SHARE:
        lots = round(lots - STEP, 2)
    if entry * OZ * lots / LEV > bal * MARGIN_SHARE:
        continue                                           # can't afford even the minimum lot
    risks.append(sl_d * OZ * lots)
    pos = {"side": side, "entry": entry, "lots": lots,
           "sl": entry - sl_d * side, "tp": entry + sl_d * RR * side}

trades = wins + losses
print(f"Real gold M15 {T[0]:%Y-%m-%d} to {T[-1]:%Y-%m-%d}  (EA targets M1/M5 - this is an approximation)")
print(f"Start ${START:,.2f}, 1:{LEV:.0f} leverage, 45-point spread")
print(f"Trades {trades}   wins {wins}   losses {losses}   win rate {100 * wins / trades if trades else 0:.0f}%")
if risks:
    print(f"Actual $ at risk per trade: min ${min(risks):.2f}  median ${sorted(risks)[len(risks) // 2]:.2f}  max ${max(risks):.2f}")
print(f"End balance ${bal:,.2f}  ({(bal / START - 1) * 100:+.0f}%)   worst drawdown {mdd:.0%}")
wk = sorted(weekly.items())
if wk:
    print(f"Weeks: {len(wk)}   positive {sum(1 for _, v in wk if v > 0)}   "
          f"best {max(v for _, v in wk):+.2f}   worst {min(v for _, v in wk):+.2f}   "
          f"average {sum(v for _, v in wk) / len(wk):+.2f}/week (goal +100)")
