"""Trade score: points = % gained or lost on the trade's stake; stop-loss hits cost extra.

    +200% of stake (full take profit)      -> +200 pts
    closed by the bot at -10% of stake     ->  -10 pts
    stop loss hit at -25% of stake         ->  -25 x SL_MULT = -37.5 pts
"""
SL_MULT = 1.5                      # penalty multiplier when the stop loss is what closed the trade
SL_PCT_FALLBACK = 25.0             # used when a trade has no recorded stake (e.g. adopted orphan): -1R = -25% of stake
STOP_REASONS = ("sl", "stop_out")


def trade_score(pnl: float, stake: float | None, r: float | None, reason: str) -> float:
    if stake:
        pct = 100.0 * pnl / stake
    elif r is not None:
        pct = r * SL_PCT_FALLBACK
    else:
        return 0.0
    if pct < 0 and reason in STOP_REASONS:
        pct *= SL_MULT
    return round(pct, 1)
