"""Train the M1 model from a bar file and print out-of-sample results per threshold.

    python -m agent.train data/XAUUSD_M1.parquet --symbol XAUUSD --point 0.01
"""
import argparse

from . import hardware
from .config import AgentConfig

PLAN = hardware.apply()

import numpy as np  # noqa: E402  (after thread env vars are set)
import pandas as pd  # noqa: E402

from . import history  # noqa: E402
from .features import build_features, triple_barrier  # noqa: E402
from .model import SignalModel  # noqa: E402


THRESHOLDS = (0.08, 0.1, 0.12, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.7)


def evaluate(proba, r_long, r_short, thresholds=THRESHOLDS):
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
    ap.add_argument("--margin-rate", type=float, default=0.0,
                    help="margin per lot / (price * value per 1.0 move per lot); >0 labels with the stake rules")
    ap.add_argument("--sl-pct", type=float, default=25.0, help="stop = this %% of the stake lost")
    ap.add_argument("--tp-pct", type=float, default=200.0, help="target = this %% of the stake gained")
    ap.add_argument("--horizon", type=int, default=None, help="max bars a label may take (default from config)")
    ap.add_argument("--no-history", action="store_true", help="ignore the extra downloaded history")
    args = ap.parse_args()

    cfg = AgentConfig(symbol=args.symbol)
    print("hardware plan:", PLAN)
    df = history.load_bars(args.symbol, args.bars, include_history=not args.no_history)
    print(f"training data: {len(df):,} M1 candles {df.index[0]:%Y-%m-%d} -> {df.index[-1]:%Y-%m-%d}", flush=True)
    if args.horizon:
        cfg.labels.horizon_bars = args.horizon
    X = build_features(df, args.point)
    if args.margin_rate > 0:
        # stake rules: distance = pct * margin_rate * price, independent of lot size (see agent/risk.stake_plan)
        base = args.margin_rate * df["close"].to_numpy()
        sl_d, tp_d = base * args.sl_pct / 100, base * args.tp_pct / 100
        print(f"labels: stake rules, stop -{args.sl_pct}% / target +{args.tp_pct}% of stake "
              f"(~ {sl_d[-1]:.2f} / {tp_d[-1]:.2f} price at the last close), horizon {cfg.labels.horizon_bars} bars")
        y, r_long, r_short = triple_barrier(df, args.point, cfg.labels, sl_d, tp_d)
    else:
        print("labels: ATR stop/target (pass --margin-rate to use the stake rules)")
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
    rr = args.tp_pct / args.sl_pct if args.margin_rate > 0 else cfg.labels.reward_risk
    print(f"\nReward:risk {rr:.2f}:1, so the break-even win rate is {100 / (1 + rr):.1f}% (before commission).")
    print("Out-of-sample (test) results, R after spread; commission not included:")
    table = evaluate(proba, r_long[cut:], r_short[cut:])
    print(table.to_string(index=False))
    good = table[(table.trades >= 100) & (table.avg_R > 0)]
    suggested = float(good.sort_values("total_R", ascending=False).threshold.iloc[0]) if len(good) else None
    print(f"\nSuggested threshold: {suggested}" if suggested is not None else
          "\nNo threshold made money on the test period with 100+ trades. Don't run this model beyond Paper mode.")

    model.meta.update({"suggested_threshold": suggested, "breakeven_win_pct": round(100 / (1 + rr), 1),
                       "test_table": table.to_dict(orient="records"),
                       "exit_rule": {"margin_rate": args.margin_rate, "sl_pct": args.sl_pct, "tp_pct": args.tp_pct,
                                      "horizon": cfg.labels.horizon_bars},
                       "symbol": args.symbol, "point": args.point, "timeframe": "M1",
                       "train_end": str(X_tr.index[-1]), "test_start": str(X_te.index[0])})
    model.save(cfg.model_dir, args.symbol)
    print(f"\nsaved model to {cfg.model_dir}/{args.symbol}_M1.json")


if __name__ == "__main__":
    main()
