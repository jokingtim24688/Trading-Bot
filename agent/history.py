"""Years of extra M1 history for training and replay.

Downloads free XAUUSD 1-minute candles (HistData, 2009 onwards, re-hosted on Hugging Face in the public dataset
fokan/xauusd-2009-2026) and saves them as data/<SYMBOL>_M1_history.parquet in the same shape as the MT5 download.

    python -m agent.history --years 5

Differences from MT5 data, handled here:
- HistData times are EST (UTC-5, no daylight saving). Most MT5 brokers use UTC+2/+3 so that the New York close is
  midnight; shifting by +7 hours lines the two up (within an hour in summer), so session filters and time-of-day
  features mean the same thing.
- There is no spread column: a typical spread is filled in (the median of your MT5 download if there is one).
- There is no volume: the model no longer uses volume, so this doesn't matter.
`load_bars()` merges both files; where they overlap, your broker's MT5 candles win.
"""
import argparse
import io
import urllib.request
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = DATA / "histdata"
BASE = "https://huggingface.co/datasets/fokan/xauusd-2009-2026/resolve/main/"
FIRST_YEAR = 2009
EST_TO_SERVER_HOURS = 7


def _files_for(years: int) -> list[str]:
    last_full = datetime.now().year - 1
    first = max(FIRST_YEAR, last_full - years + 1)
    names = [f"DAT_MT_XAUUSD_M1_{y}.csv" for y in range(first, min(last_full, 2025) + 1)]
    names.append("DAT_MT_XAUUSD_M1_202601.csv")         # partial month the dataset also carries
    return names


def _download(name: str) -> bytes:
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / name
    if cached.exists() and cached.stat().st_size > 1000:
        print(f"  {name}: cached", flush=True)
        return cached.read_bytes()
    print(f"  {name}: downloading...", flush=True)
    req = urllib.request.Request(BASE + name, headers={"User-Agent": "TradingBot/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        raw = r.read()
    cached.write_bytes(raw)
    print(f"  {name}: {len(raw) / 1e6:.1f} MB", flush=True)
    return raw


def _parse(raw: bytes) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(raw), header=None, names=["d", "t", "open", "high", "low", "close", "v"])
    est = pd.to_datetime(df["d"] + " " + df["t"], format="%Y.%m.%d %H:%M")
    df["time"] = (est + pd.Timedelta(hours=EST_TO_SERVER_HOURS)).dt.tz_localize("UTC")
    return df[["time", "open", "high", "low", "close"]]


def import_history(symbol: str = "XAUUSD", years: int = 5) -> Path:
    if symbol.upper().rstrip(".M").replace("#", "") not in ("XAUUSD", "GOLD") and not symbol.upper().startswith("XAU"):
        raise SystemExit("Extra history is only available for gold (XAUUSD).")
    mt5_file = DATA / f"{symbol}_M1.parquet"
    spread = 25
    if mt5_file.exists():
        s = pd.read_parquet(mt5_file, columns=["spread"])["spread"]
        spread = int(s.median()) if len(s) else spread
    print(f"downloading {years} year(s) of XAUUSD M1 history (spread filled as {spread} points)", flush=True)
    parts = [_parse(_download(n)) for n in _files_for(years)]
    df = pd.concat(parts).drop_duplicates("time").sort_values("time")
    df["tick_volume"] = 0
    df["spread"] = spread
    df["real_volume"] = 0
    for c in ("open", "high", "low", "close"):
        df[c] = df[c].astype("float64")
    out = DATA / f"{symbol}_M1_history.parquet"
    df.to_parquet(out, index=False)
    print(f"saved {len(df):,} candles {df['time'].iloc[0]:%Y-%m-%d} -> {df['time'].iloc[-1]:%Y-%m-%d} to {out.name}", flush=True)
    return out


def load_bars(symbol: str | None = None, path: str | None = None, include_history: bool = True) -> pd.DataFrame:
    """Candles for training/replay: the MT5 download plus extra history if present (MT5 wins on overlap)."""
    main = Path(path) if path else DATA / f"{symbol}_M1.parquet"
    frames = []
    if main.exists():
        frames.append(pd.read_parquet(main) if main.suffix == ".parquet" else pd.read_csv(main))
    sym = symbol or main.stem.replace("_M1", "")
    hist = DATA / f"{sym}_M1_history.parquet"
    if include_history and hist.exists():
        frames.insert(0, pd.read_parquet(hist))
    if not frames:
        raise SystemExit(f"No M1 data for {sym}. Fetch data first.")
    for f in frames:
        f["time"] = pd.to_datetime(f["time"], utc=True)
    df = pd.concat(frames).drop_duplicates("time", keep="last").sort_values("time").set_index("time")
    df.index = df.index.as_unit("ns")          # one resolution, whatever pandas/parquet wrote (pandas 3 uses us)
    return df[["open", "high", "low", "close", "tick_volume", "spread"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--years", type=int, default=5)
    a = ap.parse_args()
    import_history(a.symbol, a.years)


if __name__ == "__main__":
    main()
