"""What professional intraday traders watch, turned into model inputs.

Discretionary gold/FX/index traders rarely trade a candle in isolation. They mark levels and context first, then wait
for price to do something at those levels. The common playbook (ICT/SMC, auction-market and classic floor-trader
methods all overlap here):

- Prior-day high / low / close and today's open: the most-watched intraday levels; stops cluster just beyond them.
- Asian range: gold's quiet overnight range; London and New York often run one side of it, then trade from there.
- Opening ranges: the first 30 minutes of London (10:00 server) and New York (16:30 server). Breaks with follow-through
  are trend days; failed breaks back inside are reversal days.
- Session average price (VWAP stand-in): institutions benchmark fills to it; far above/below is stretched, reclaiming
  it is a shift in control. (Free history has no volume, so this is a time-weighted average for live/history parity.)
- Liquidity sweeps / stop hunts: price pokes beyond a recent high or low where stops sit, then closes back inside.
  Pros fade the sweep, not the breakout.
- Fair value gaps: a 3-candle imbalance (candle 1 and 3 don't overlap) that price tends to revisit.
- Higher-timeframe structure: trade M1 in the direction of H1 higher-highs/higher-lows (or lower-lows/lower-highs).
- Round numbers: $10 / $50 levels on gold attract orders and act as magnets and barriers.
- Weekly open: the reference for the week's bias.

Every feature here is causal (uses only candles up to and including the current closed one) and measured in ATRs so it
means the same thing at $1,200 and $4,000 gold. Times are broker server time (UTC+2/+3), where the New York open is
16:30 all year and London opens at 10:00.
"""
import numpy as np
import pandas as pd

ASIA = (1, 9)                 # server hours [start, end)
LONDON_OR = (10 * 60, 10 * 60 + 30)
NY_OR = (16 * 60 + 30, 17 * 60)
SWEEP_LOOKBACK = 60           # "recent high/low" for stop hunts, in M1 candles

# human names for the setups the bot card shows and the learning step groups by
SETUP_NAMES = {
    "sweep_long": "Liquidity sweep below lows",
    "sweep_short": "Liquidity sweep above highs",
    "orb_long": "Opening-range breakout up",
    "orb_short": "Opening-range breakout down",
    "pdh_test": "Testing prior-day high",
    "pdl_test": "Testing prior-day low",
    "asia_high_run": "Running the Asian high",
    "asia_low_run": "Running the Asian low",
    "avg_reclaim_long": "Reclaimed session average",
    "avg_reclaim_short": "Lost session average",
    "stretched_up": "Stretched far above session average",
    "stretched_down": "Stretched far below session average",
    "fvg_bull": "Bullish fair value gap",
    "fvg_bear": "Bearish fair value gap",
    "round_number": "At a round number",
    "h1_uptrend": "H1 structure up",
    "h1_downtrend": "H1 structure down",
}


def _running_in_window(s: pd.Series, day, in_win: np.ndarray, how: str) -> pd.Series:
    """Running max/min of `s` over the bars inside a daily window, carried forward for the rest of that day."""
    v = s.where(in_win)
    g = v.groupby(day)
    r = g.cummax() if how == "max" else g.cummin()
    return r.groupby(day).ffill()


def pro_features(df: pd.DataFrame, a_safe: pd.Series) -> pd.DataFrame:
    c, h, l, o = df["close"], df["high"], df["low"], df["open"]
    idx = df.index
    day = pd.Series(idx.normalize(), index=idx)
    minute = pd.Series(idx.hour * 60 + idx.minute, index=idx)
    f = pd.DataFrame(index=idx)

    # prior-day levels and today's open
    daily = df.groupby(day.values).agg(high=("high", "max"), low=("low", "min"), close=("close", "last"), open=("open", "first"))
    prev = daily.shift(1)
    pdh = pd.Series(prev["high"].reindex(day.values).to_numpy(), index=idx)
    pdl = pd.Series(prev["low"].reindex(day.values).to_numpy(), index=idx)
    pdc = pd.Series(prev["close"].reindex(day.values).to_numpy(), index=idx)
    d_open = pd.Series(daily["open"].reindex(day.values).to_numpy(), index=idx)
    f["pdh_dist"] = (c - pdh) / a_safe
    f["pdl_dist"] = (c - pdl) / a_safe
    f["pdc_dist"] = (c - pdc) / a_safe
    f["day_open_dist"] = (c - d_open) / a_safe
    d_hi, d_lo = h.groupby(day).cummax(), l.groupby(day).cummin()
    f["day_range_pos"] = (c - d_lo) / (d_hi - d_lo).replace(0, np.nan)

    # weekly open
    week = pd.Series(idx.to_period("W").start_time, index=idx) if idx.tz is None else \
        pd.Series(idx.tz_localize(None).to_period("W").start_time, index=idx)
    f["week_open_dist"] = (c - o.groupby(week).transform("first")) / a_safe

    # Asian range (running until it closes, then fixed for the day)
    in_asia = ((idx.hour >= ASIA[0]) & (idx.hour < ASIA[1]))
    a_hi = _running_in_window(h, day, in_asia, "max")
    a_lo = _running_in_window(l, day, in_asia, "min")
    f["asia_hi_dist"] = ((c - a_hi) / a_safe).fillna(0)
    f["asia_lo_dist"] = ((c - a_lo) / a_safe).fillna(0)

    # opening ranges: 0 inside or before the range is complete, else ATRs beyond it
    for name, (m0, m1) in (("lon", LONDON_OR), ("ny", NY_OR)):
        in_or = ((minute >= m0) & (minute < m1)).to_numpy()
        or_hi = _running_in_window(h, day, in_or, "max")
        or_lo = _running_in_window(l, day, in_or, "min")
        done = minute >= m1
        above = ((c - or_hi) / a_safe).clip(lower=0)
        below = ((c - or_lo) / a_safe).clip(upper=0)
        f[f"{name}_or_pos"] = (above + below).where(done, 0).fillna(0)

    # session average price since the day's open (VWAP stand-in)
    tp = (h + l + c) / 3
    avg = tp.groupby(day).cumsum() / tp.groupby(day).cumcount().add(1)
    f["sess_avg_dist"] = (c - avg) / a_safe

    # liquidity sweeps: pierce the recent extreme, close back inside; remembered for 5 candles
    prior_hi = h.shift(1).rolling(SWEEP_LOOKBACK).max()
    prior_lo = l.shift(1).rolling(SWEEP_LOOKBACK).min()
    sweep_lo = ((l < prior_lo) & (c > prior_lo)).astype(float)
    sweep_hi = ((h > prior_hi) & (c < prior_hi)).astype(float)
    f["sweep_long"] = sweep_lo.rolling(5, min_periods=1).max()
    f["sweep_short"] = sweep_hi.rolling(5, min_periods=1).max()
    f["break_prior_hi"] = ((c - prior_hi) / a_safe).clip(lower=0)
    f["break_prior_lo"] = ((c - prior_lo) / a_safe).clip(upper=0)

    # fair value gaps in the last 10 candles (net bullish minus bearish)
    fvg_bull = (l > h.shift(2)).astype(float)
    fvg_bear = (h < l.shift(2)).astype(float)
    f["fvg_net10"] = fvg_bull.rolling(10, min_periods=1).sum() - fvg_bear.rolling(10, min_periods=1).sum()

    # H1 market structure from completed hours only
    hr = df.resample("1h").agg({"high": "max", "low": "min"}).dropna()
    hh = (hr["high"] > hr["high"].shift(1)) & (hr["low"] > hr["low"].shift(1))
    ll = (hr["high"] < hr["high"].shift(1)) & (hr["low"] < hr["low"].shift(1))
    struct = (hh.astype(int) - ll.astype(int)).rolling(3, min_periods=1).sum()
    struct.index = struct.index + pd.Timedelta(hours=1)          # an hour is known once it has closed
    f["h1_structure"] = struct.reindex(idx, method="ffill").fillna(0)

    # round numbers: $10 and $50 on gold (scales with price for other symbols)
    step = 10 ** np.floor(np.log10(c.clip(lower=1e-9))) / 100
    for mult, name in ((1, "round_small"), (5, "round_big")):
        lvl = step * mult
        f[f"{name}_dist"] = ((c - (c / lvl).round() * lvl) / a_safe)
    return f


def active_setups(row) -> list[str]:
    """Pro setups present on this candle, from one row of build_features()."""
    def has(k):
        v = row.get(k)
        return v is not None and v == v                  # present and not NaN

    def g(k):
        return float(row.get(k)) if has(k) else 0.0

    out = []
    if g("sweep_long") > 0:
        out.append("sweep_long")
    if g("sweep_short") > 0:
        out.append("sweep_short")
    if g("lon_or_pos") > 0.2 or g("ny_or_pos") > 0.2:
        out.append("orb_long")
    if g("lon_or_pos") < -0.2 or g("ny_or_pos") < -0.2:
        out.append("orb_short")
    if has("pdh_dist") and abs(g("pdh_dist")) < 0.5:
        out.append("pdh_test")
    if has("pdl_dist") and abs(g("pdl_dist")) < 0.5:
        out.append("pdl_test")
    if g("asia_hi_dist") > 0.2:
        out.append("asia_high_run")
    if g("asia_lo_dist") < -0.2:
        out.append("asia_low_run")
    sa = g("sess_avg_dist")
    if 0 < sa < 0.3:
        out.append("avg_reclaim_long")
    elif -0.3 < sa < 0:
        out.append("avg_reclaim_short")
    elif sa > 4:
        out.append("stretched_up")
    elif sa < -4:
        out.append("stretched_down")
    if g("fvg_net10") >= 1:
        out.append("fvg_bull")
    if g("fvg_net10") <= -1:
        out.append("fvg_bear")
    if abs(g("round_big_dist")) < 0.3:
        out.append("round_number")
    if g("h1_structure") >= 2:
        out.append("h1_uptrend")
    if g("h1_structure") <= -2:
        out.append("h1_downtrend")
    return out


def primary_setup(setups: list[str], side: str) -> str:
    """The one setup a trade is filed under for learning: the first that agrees with its direction."""
    long_like = ("sweep_long", "orb_long", "asia_high_run", "avg_reclaim_long", "fvg_bull", "h1_uptrend", "stretched_down", "pdl_test")
    short_like = ("sweep_short", "orb_short", "asia_low_run", "avg_reclaim_short", "fvg_bear", "h1_downtrend", "stretched_up", "pdh_test")
    for s in setups:
        if s in (long_like if side == "buy" else short_like):
            return s
    return "no pro setup"
