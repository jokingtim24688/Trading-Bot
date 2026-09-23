"""Causal M1 features and triple-barrier labels.

Input: DataFrame indexed by bar time with columns open, high, low, close, tick_volume, spread
(spread in points, as MT5 returns it). Every feature at row i uses only rows <= i.
"""
import numpy as np
import pandas as pd

from .config import LabelConfig


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def build_features(df: pd.DataFrame, point: float) -> pd.DataFrame:
    c = df["close"]
    a = atr(df, 14)
    a_safe = a.replace(0, np.nan)
    f = pd.DataFrame(index=df.index)

    for n in (1, 3, 5, 15, 30, 60):
        f[f"ret_{n}"] = (c - c.shift(n)) / a_safe
    for n in (20, 50, 200, 750, 3000):          # 750 ≈ EMA50 on M15, 3000 ≈ EMA50 on H1, computed from M1
        e = _ema(c, n)
        f[f"dist_ema{n}"] = (c - e) / a_safe
        f[f"slope_ema{n}"] = (e - e.shift(5)) / a_safe
    f["rsi7"] = rsi(c, 7) / 100
    f["rsi14"] = rsi(c, 14) / 100
    f["atr_rel"] = a / a.rolling(1440, min_periods=60).median()
    mid = c.rolling(20).mean()
    sd = c.rolling(20).std()
    f["bb_pos"] = (c - mid) / (2 * sd.replace(0, np.nan))
    for n in (15, 60, 240):
        hi = df["high"].rolling(n).max()
        lo = df["low"].rolling(n).min()
        f[f"range_pos_{n}"] = (c - lo) / (hi - lo).replace(0, np.nan)
    body = (c - df["open"]) / a_safe
    f["body"] = body
    f["upper_wick"] = (df["high"] - df[["open", "close"]].max(axis=1)) / a_safe
    f["lower_wick"] = (df[["open", "close"]].min(axis=1) - df["low"]) / a_safe
    # (no volume feature: the long free history has no volume, so live and history stay comparable)
    spread_px = df["spread"].astype(float) * point
    f["spread_atr"] = spread_px / a_safe
    minute = df.index.hour * 60 + df.index.minute
    f["tod_sin"] = np.sin(2 * np.pi * minute / 1440)
    f["tod_cos"] = np.cos(2 * np.pi * minute / 1440)
    f["dow"] = df.index.dayofweek
    return f.replace([np.inf, -np.inf], np.nan).astype("float32")


def triple_barrier(df: pd.DataFrame, point: float, cfg: LabelConfig, sl_dist=None, tp_dist=None):
    """Return (label, r_long, r_short) arrays.

    Barriers: by default stop = ATR * stop_atr_mult and target = stop * reward_risk. Pass `sl_dist` / `tp_dist`
    (price distances, scalar or per-row arrays) to label with the live stake rules instead, so the model learns
    exactly the exits it will trade.
    label: 2 = long target hit before stop, 0 = short target hit before stop, 1 = neither.
    r_long / r_short: realised R (stop = -1, target = +tp/sl, timeout = mark-to-market), spread charged on entry.
    A bar that touches both barriers counts as a stop (conservative).
    """
    h, l, c = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    spread = df["spread"].to_numpy(dtype=float) * point
    n, H = len(df), cfg.horizon_bars
    if sl_dist is None:
        sl = atr(df, cfg.atr_period).to_numpy() * cfg.stop_atr_mult
        tp = sl * cfg.reward_risk
    else:
        sl = np.broadcast_to(np.asarray(sl_dist, dtype=float), (n,)).copy()
        tp = np.broadcast_to(np.asarray(tp_dist, dtype=float), (n,)).copy()
    rr = tp / sl

    label = np.ones(n, dtype=np.int8)
    wins = {}
    results = {}
    for side in ("long", "short"):
        # long: buy at ask (close + spread), exit at bid; short: sell at bid (close), exit at ask
        entry = c + spread if side == "long" else c
        done = np.zeros(n, dtype=bool)
        won = np.zeros(n, dtype=bool)
        res = np.full(n, np.nan)
        for k in range(1, H + 1):
            idx = np.arange(n) + k
            valid = idx < n
            idx = np.where(valid, idx, n - 1)
            if side == "long":
                stop_hit = l[idx] <= entry - sl
                tgt_hit = h[idx] >= entry + tp
            else:
                stop_hit = h[idx] + spread[idx] >= entry + sl
                tgt_hit = l[idx] + spread[idx] <= entry - tp
            new_stop = valid & ~done & stop_hit
            new_tgt = valid & ~done & tgt_hit & ~stop_hit
            res[new_stop] = -1.0
            res[new_tgt] = rr[new_tgt]
            won |= new_tgt
            done |= new_stop | new_tgt
        end = np.minimum(np.arange(n) + H, n - 1)
        mtm = (c[end] - entry) / sl if side == "long" else (entry - (c[end] + spread[end])) / sl
        open_ = ~done & (np.arange(n) + H < n)
        res[open_] = mtm[open_]
        wins[side], results[side] = won, res
    label[wins["long"]] = 2
    label[wins["short"]] = 0
    label[wins["long"] & wins["short"]] = 1
    r_long, r_short = results["long"], results["short"]
    tail = np.arange(n) + H >= n            # rows without a full horizon have no reliable outcome
    r_long[tail] = np.nan
    r_short[tail] = np.nan
    return label, r_long, r_short
