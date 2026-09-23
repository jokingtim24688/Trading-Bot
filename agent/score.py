"""Trade score: 1 point = $1 (account currency) of profit or loss; stop-loss hits cost extra.

    closed at +$100 (target or early)   -> +100 pts
    bot closed it early at -$20          ->  -20 pts
    stop loss hit at -$20                ->  -20 x SL_MULT = -30 pts
"""
SL_MULT = 1.5                      # penalty multiplier when the stop loss is what closed the trade
STOP_REASONS = ("sl", "stop_out")


def trade_score(pnl: float, stake: float | None = None, r: float | None = None, reason: str = "") -> float:
    pts = float(pnl or 0.0)
    if pts < 0 and reason in STOP_REASONS:
        pts *= SL_MULT
    return round(pts, 2)
