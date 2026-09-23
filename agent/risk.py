"""Position sizing and pre-trade gates."""
import math
from dataclasses import dataclass
from datetime import datetime

from .config import RiskConfig


@dataclass
class SymbolSpec:
    point: float
    tick_size: float
    tick_value: float        # account currency per tick per 1 lot (loss side)
    volume_min: float
    volume_step: float
    volume_max: float
    stops_level_points: int = 0


def lots_for_risk(equity: float, risk_pct: float, stop_distance: float, spec: SymbolSpec) -> float:
    """Lots that lose `risk_pct` of equity if the stop is hit. Returns 0 if the minimum lot would over-risk."""
    if stop_distance <= 0 or spec.tick_size <= 0 or spec.tick_value <= 0:
        return 0.0
    loss_per_lot = stop_distance / spec.tick_size * spec.tick_value
    raw = equity * risk_pct / 100.0 / loss_per_lot
    lots = math.floor(raw / spec.volume_step + 1e-9) * spec.volume_step
    if lots < spec.volume_min:
        return 0.0
    decimals = max(0, -int(math.floor(math.log10(spec.volume_step)))) if spec.volume_step < 1 else 0
    return round(min(lots, spec.volume_max), decimals)


class RiskGate:
    def __init__(self, cfg: RiskConfig):
        self.cfg = cfg
        self.day = None
        self.day_start_equity = None
        self.trades_today = 0

    def roll_day(self, server_time: datetime, equity: float):
        if self.day != server_time.date():
            self.day = server_time.date()
            self.day_start_equity = equity
            self.trades_today = 0

    def daily_stop_hit(self, equity: float) -> bool:
        return equity <= self.day_start_equity * (1 - self.cfg.daily_loss_pct / 100.0)

    def check(self, server_time: datetime, equity: float, spread_px: float, median_spread_px: float, atr_px: float):
        """Return (ok, reason)."""
        self.roll_day(server_time, equity)
        c = self.cfg
        if self.daily_stop_hit(equity):
            return False, "daily loss limit"
        if self.trades_today >= c.max_trades_per_day:
            return False, "max trades today"
        h = server_time.hour
        if not (c.session_start_hour <= h < c.session_end_hour):
            return False, "outside session"
        b0, b1 = c.rollover_blackout
        in_blackout = (b0 <= h or h < b1) if b0 > b1 else (b0 <= h < b1)
        if in_blackout:
            return False, "rollover blackout"
        if atr_px <= 0 or spread_px / atr_px > c.max_spread_to_atr:
            return False, "spread too large vs ATR"
        if median_spread_px > 0 and spread_px > median_spread_px * c.max_spread_vs_median:
            return False, "spread above median"
        return True, "ok"

    def record_trade(self):
        self.trades_today += 1
