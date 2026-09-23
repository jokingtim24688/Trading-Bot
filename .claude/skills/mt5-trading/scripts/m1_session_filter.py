#!/usr/bin/env python3
"""Tag M1 bars with trading session and flag poor-liquidity minutes.

    python m1_session_filter.py data/XAUUSD_M1.parquet --server-offset 3 --point 0.01
Adds columns: utc_time, session (asia/london/overlap/newyork/rollover), spread_atr, tradable.
Prints spread-to-ATR by session, which is the main M1 cost check.
"""
import argparse

import numpy as np
import pandas as pd


def session_of(hour_utc: int) -> str:
    if 21 <= hour_utc < 22:
        return "rollover"
    if 12 <= hour_utc < 16:
        return "overlap"
    if 7 <= hour_utc < 12:
        return "london"
    if 16 <= hour_utc < 21:
        return "newyork"
    return "asia"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bars")
    ap.add_argument("--server-offset", type=float, default=3, help="server time minus UTC in hours (e.g. 2 winter / 3 summer)")
    ap.add_argument("--point", type=float, default=0.01)
    ap.add_argument("--max-spread-atr", type=float, default=0.15)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    df = pd.read_parquet(a.bars) if a.bars.endswith(".parquet") else pd.read_csv(a.bars, parse_dates=["time"])
    t = pd.to_datetime(df["time"], utc=True)
    df["utc_time"] = t - pd.Timedelta(hours=a.server_offset)
    df["session"] = df["utc_time"].dt.hour.map(session_of)
    prev = df["close"].shift(1)
    tr = np.maximum(df["high"] - df["low"], np.maximum((df["high"] - prev).abs(), (df["low"] - prev).abs()))
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
    df["spread_atr"] = df["spread"] * a.point / atr.replace(0, np.nan)
    df["tradable"] = (df["session"] != "rollover") & (df["spread_atr"] <= a.max_spread_atr)

    summary = df.groupby("session").agg(bars=("close", "size"),
                                        median_spread_atr=("spread_atr", "median"),
                                        pct_tradable=("tradable", "mean"))
    summary["pct_tradable"] = (summary["pct_tradable"] * 100).round(1)
    print(summary.round(3).to_string())
    if a.out:
        (df.to_parquet if a.out.endswith(".parquet") else df.to_csv)(a.out, index=False)
        print(f"saved {a.out}")


if __name__ == "__main__":
    main()
