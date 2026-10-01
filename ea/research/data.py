"""Download XAU_15m_data.csv from https://github.com/BaseMax/XAUUSD-LSTM (MIT) into this folder.
Gold 15m bars in New York time: BaseMax 2004-06..2025-09 (MIT, broker time = NY+7h) + getdata 2026-03..09 (UTC)."""
import pandas as pd, numpy as np
from pathlib import Path
H = Path(__file__).parent
def load15():
    p = H / "gold15_ny.parquet"
    if p.exists(): return pd.read_parquet(p)
    a = pd.read_csv(H / "XAU_15m_data.csv", sep=";")
    a.index = pd.to_datetime(a.Date, format="%Y.%m.%d %H:%M") - pd.Timedelta(hours=7)
    a = a.rename(columns=str.lower)[["open", "high", "low", "close"]]
    b = pd.read_csv(H.parent / "XAUUSD_15m.csv")
    b.index = pd.to_datetime(b.datetime, utc=True).dt.tz_convert("America/New_York").dt.tz_localize(None)
    b = b[["open", "high", "low", "close"]]
    d = pd.concat([a, b]).sort_index(); d = d[~d.index.duplicated()]
    d.to_parquet(p); return d
def resample(d, rule):
    # bars stamped by OPEN time; CME day starts 18:00 NY -> offset so daily bars = trading days
    if rule == "D":
        g = d.copy(); g.index = g.index + pd.Timedelta(hours=6)   # 18:00 -> 00:00 next day
        r = g.resample("D").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
        return r
    return d.resample(rule).agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
if __name__ == "__main__":
    d = load15(); print(len(d), d.index[0], d.index[-1]); print(resample(d, "D").tail(3))
