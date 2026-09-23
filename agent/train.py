"""Train the M1 model from a bar file and print out-of-sample results per threshold.

    python -m agent.train data/XAUUSD_M1.parquet --symbol XAUUSD --point 0.01
"""
import argparse

from . import hardware
from .config import AgentConfig

PLAN = hardware.apply()

import numpy as np  # noqa: E402  (after thread env vars are set)
import pandas as pd  # noqa: E402

from .features import build_features, triple_barrier  # noqa: E402
from .model import SignalModel  # noqa: E402


def load_bars(path: str) -> pd.DataFrame:
    df = pd.read_parquet(path) if path.endswith(".parquet") else pd.read_csv(path)
    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df = df.set_index("time")
    return df.sort_index()


def evaluate(proba, r_long, r_short, thresholds=(0.45, 0.5, 0.55, 0.6, 0.65, 0.7)):
    rows = []
    for t in thresholds:
        go_long = (proba[:, 2] >= t) & (proba[:, 2] > proba[:, 0])
        go_short = (proba[:, 0] >= t) & (proba[:, 0] > proba[:, 2])
        r = np.concatenate([r_long[go_long], r_short[go_short]])
        r = r[~np.isnan(r)]
        rows.append({
            "threshold": t, "trades": len(r),
            "win_pct": round(100 * (r > 0).mean(), 1) if len(r) else 0.0,
            "avg_R": round(r.mean(), 3) if len(r) else 0.0,
            "total_R": round(r.sum(), 1),
        })
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bars")
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--point", type=float, default=0.01, help="symbol_info().point (0.01 for most XAUUSD feeds)")
    ap.add_argument("--test-frac", type=float, default=0.25)
    args = ap.parse_args()

    cfg = AgentConfig(symbol=args.symbol)
    print("hardware plan:", PLAN)
    df = load_bars(args.bars)
    X = build_features(df, args.point)
    y, r_long, r_short = triple_barrier(df, args.point, cfg.labels)

    ok = X.notna().all(axis=1).to_numpy() & ~np.isnan(r_long) & ~np.isnan(r_short)
    ok[:3000] = False                                   # EMA 3000 warm-up
    X, y, r_long, r_short = X[ok], y[ok], r_long[ok], r_short[ok]

    # chronological split with a gap of one label horizon so train labels don't peek into test
    n = len(X)
    cut = int(n * (1 - args.test_frac))
    gap = cfg.labels.horizon_bars
    va_cut = int(cut * 0.85)
    X_tr, y_tr = X.iloc[:va_cut - gap], y[:va_cut - gap]
    X_va, y_va = X.iloc[va_cut:cut - gap], y[va_cut:cut - gap]
    X_te = X.iloc[cut:]

    print(f"rows: train {len(X_tr)}, valid {len(X_va)}, test {len(X_te)}; class balance {np.bincount(y, minlength=3)}")
    model = SignalModel.train(X_tr, y_tr, X_va, y_va, use_gpu=PLAN["xgb_cuda"], hw=cfg.hardware)
    proba = model.predict_proba(X_te)
    print("\nOut-of-sample (test) results, R after spread; commission not included:")
    print(evaluate(proba, r_long[cut:], r_short[cut:]).to_string(index=False))

    model.meta.update({"symbol": args.symbol, "point": args.point, "timeframe": "M1",
                       "train_end": str(X_tr.index[-1]), "test_start": str(X_te.index[0])})
    model.save(cfg.model_dir, args.symbol)
    print(f"\nsaved model to {cfg.model_dir}/{args.symbol}_M1.json")


if __name__ == "__main__":
    main()
