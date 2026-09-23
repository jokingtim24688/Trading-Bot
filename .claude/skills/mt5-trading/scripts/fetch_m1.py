#!/usr/bin/env python3
"""Download M1 bars from a running MT5 terminal (Windows) to Parquet or CSV.

    python fetch_m1.py XAUUSD --days 365 --out data/XAUUSD_M1.parquet
Raise Tools > Options > Charts > "Max bars in chart" (Unlimited) first, or history gets cut off.
"""
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import MetaTrader5 as mt5
import pandas as pd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol")
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--out", default=None)
    ap.add_argument("--terminal", default=None, help="path to terminal64.exe")
    a = ap.parse_args()

    ok = mt5.initialize(path=a.terminal) if a.terminal else mt5.initialize()
    if not ok:
        raise SystemExit(f"initialize failed: {mt5.last_error()}")
    if not mt5.symbol_select(a.symbol, True):
        raise SystemExit(f"symbol {a.symbol} not available")

    end = datetime.now(timezone.utc) + timedelta(days=1)
    start = end - timedelta(days=a.days + 1)
    frames, cursor = [], start
    while cursor < end:                      # chunk by 30 days to stay under terminal limits
        nxt = min(cursor + timedelta(days=30), end)
        r = mt5.copy_rates_range(a.symbol, mt5.TIMEFRAME_M1, cursor, nxt)
        if r is not None and len(r):
            frames.append(pd.DataFrame(r))
        cursor = nxt
    mt5.shutdown()
    if not frames:
        raise SystemExit("no data returned; check history / Max bars setting")

    df = pd.concat(frames).drop_duplicates("time").sort_values("time")
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)   # note: MT5 epoch = server time
    df = df.iloc[:-1]                                                # drop the forming bar
    out = Path(a.out or f"data/{a.symbol}_M1.parquet")
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix == ".csv":
        df.to_csv(out, index=False)
    else:
        df.to_parquet(out, index=False)
    print(f"{len(df):,} M1 bars {df['time'].iloc[0]} -> {df['time'].iloc[-1]} saved to {out}")


if __name__ == "__main__":
    main()
