"""Replay SmallAccountPro's rules as CME 1-Ounce Gold (1OZ) futures, the legal US route to gold.

Builds on sap_replay.py and changes only what futures change:
  - one contract = 1 oz = $1 per $1 move (the same as 0.01 lots of XAUUSD)
  - margin is a flat $ per contract (day margin, since every trade closes before the break)
  - commission per contract, round trip (NinjaTrader all-in is ~$0.80-1.06 per side)
  - spread at least one tick ($0.25 = 25 points)
  - flat by 20:45 UTC, no new entries after 19:30 UTC (CME's daily break is 21:00 UTC in summer)
  - wider stops: with $400 the ladder risks $20, so one contract can carry a 500-2500 pt stop and
    the commission becomes a small share of each trade instead of eating the whole edge.

    python ea/futures_replay.py [csv] [start] [min_sl_pts] [max_sl_pts] [commission_rt] [spread_pts]
Defaults: ea/XAUUSD_30m.csv 400 500 2500 2.00 25, risk ladder on.
"""
import subprocess
import sys
from pathlib import Path

here = Path(__file__).parent
a = sys.argv[1:] + [None] * 6
csv_path = a[0] or str(here / "XAUUSD_30m.csv")
start, lo, hi = a[1] or "400", a[2] or "500", a[3] or "2500"
comm, spread = a[4] or "2.00", a[5] or "25"

s = (here / "sap_replay.py").read_text()
edits = [
    ('"XAUUSD": (0.01,    100,    45, "q"),', f'"XAUUSD": (0.01,    100,    {spread}, "q"),'),
    ("MIN_SL, MAX_SL, ATR_MULT = 100 * PT, 500 * PT, 1.5", f"MIN_SL, MAX_SL, ATR_MULT = {lo} * PT, {hi} * PT, 1.5"),
    ("EURUSD_APPROX, GBPUSD_APPROX = 1.15, 1.34", f"EURUSD_APPROX, GBPUSD_APPROX = 1.15, 1.34\nCOMM, DAY_MARGIN = {comm}, 60.0"),
    ('def margin(price, lots):\n    if KIND == "q":', 'def margin(price, lots):\n    return round(lots / 0.01) * DAY_MARGIN\n    if KIND == "q":'),
    ('            pnl = (px - pos["entry"]) * b * usd_per_price(pos["entry"]) * pos["lots"]',
     '            pnl = (px - pos["entry"]) * b * usd_per_price(pos["entry"]) * pos["lots"] - COMM * round(pos["lots"] / 0.01)'),
    ('    if pos:\n        b = pos["side"]',
     '    if pos and (T[i].hour, T[i].minute) >= (20, 45):\n'
     '        b = pos["side"]\n'
     '        px = O[i] if b == 1 else O[i] + SPREAD\n'
     '        pnl = (px - pos["entry"]) * b * usd_per_price(pos["entry"]) * pos["lots"] - COMM * round(pos["lots"] / 0.01)\n'
     '        bal += pnl; day_pnl += pnl; weekly[T[i].strftime("%G-W%V")] += pnl\n'
     '        wins += pnl > 0; losses += pnl <= 0\n'
     '        pos = None\n'
     '    if pos:\n        b = pos["side"]'),
    ('    j = i - 1                                              # the last closed bar',
     '    if T[i].hour > 19 or (T[i].hour == 19 and T[i].minute >= 30):\n        continue\n'
     '    j = i - 1                                              # the last closed bar'),
]
for old, new in edits:
    assert old in s, f"sap_replay.py changed - can't find: {old[:50]}"
    s = s.replace(old, new, 1)
print(f"CME 1-Ounce Gold futures: stops {lo}-{hi} pts, ${comm} round trip, {spread}pt spread, flat by 20:45 UTC")
sys.exit(subprocess.run([sys.executable, "-c", s, csv_path, start, "100", "XAUUSD", "1"]).returncode)
