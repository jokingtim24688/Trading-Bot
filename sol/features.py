"""The 8 numbers every model sees for a token, from a snapshot (live feed) or from candles (history)."""
import math

import numpy as np

FEATURES = ["log_liq", "age_min", "buys_5m", "sells_5m", "buy_ratio", "log_vol_5m", "chg_5m", "top10_pct"]
LABEL_UP, LABEL_DOWN, LABEL_MIN = 25.0, -12.0, 30      # +25 % before -12 % within 30 minutes = a good buy


def vector(s: dict) -> np.ndarray:
    b, se = float(s.get("buys_5m") or 0), float(s.get("sells_5m") or 0)
    return np.array([
        math.log10(1 + max(0.0, float(s.get("liq_usd") or 0))),
        min(float(s.get("age_min") or 0), 1440.0),
        b, se, b / (b + se) if b + se else 0.5,
        math.log10(1 + max(0.0, float(s.get("vol_5m") or 0))),
        max(-100.0, min(500.0, float(s.get("chg_5m") or 0))),
        float(s.get("top10_pct") if s.get("top10_pct") is not None else 50),
    ], dtype=np.float32)


def label_path(entry: float, highs, lows) -> int | None:
    """1 when price reaches +25 % before -12 % in the next 30 candles, 0 when -12 % comes first or neither; None
    when there aren't 30 candles yet."""
    if len(highs) < LABEL_MIN or not entry:
        return None
    for h, lo in zip(highs[:LABEL_MIN], lows[:LABEL_MIN]):
        if (lo / entry - 1) * 100 <= LABEL_DOWN:
            return 0
        if (h / entry - 1) * 100 >= LABEL_UP:
            return 1
    return 0
