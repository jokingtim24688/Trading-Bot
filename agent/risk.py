"""Position sizing and pre-trade gates."""
import math
from dataclasses import dataclass
from datetime import datetime

from .config import MoneyConfig, RiskConfig


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


def tp_pct_for_stake(stake: float, m: MoneyConfig, small: float, large: float) -> float:
    """Take-profit % of stake: tp_pct_small_stake at small stakes, easing to tp_pct_large_stake as stakes grow."""
    if stake <= small or large <= small:
        return m.tp_pct_small_stake
    if stake >= large:
        return m.tp_pct_large_stake
    f = (math.log(stake) - math.log(small)) / (math.log(large) - math.log(small))
    return m.tp_pct_small_stake + f * (m.tp_pct_large_stake - m.tp_pct_small_stake)


def stake_plan(balance: float, margin_per_lot: float, spec: SymbolSpec, m: MoneyConfig) -> dict | None:
    """Lots, stake and exit distances for one trade under the stake rules. Price distances don't depend on side.

    Returns None if the symbol data is unusable. `forced_min` means 0.1% of balance was below the minimum lot,
    so the minimum lot is used and the stake is larger than the target.
    """
    if margin_per_lot <= 0 or spec.tick_size <= 0 or spec.tick_value <= 0:
        return None
    target = balance * m.stake_pct_of_balance / 100.0
    lots = math.floor(target / margin_per_lot / spec.volume_step + 1e-9) * spec.volume_step
    forced_min = lots < spec.volume_min
    lots = min(max(lots, spec.volume_min), spec.volume_max)
    decimals = max(0, -int(math.floor(math.log10(spec.volume_step)))) if spec.volume_step < 1 else 0
    lots = round(lots, decimals)
    stake = lots * margin_per_lot
    min_stake = spec.volume_min * margin_per_lot
    small = m.small_stake or min_stake
    large = m.large_stake or 100 * min_stake
    tp_pct = tp_pct_for_stake(stake, m, small, large)
    money_per_price = lots * spec.tick_value / spec.tick_size        # P/L for a 1.0 move in price
    sl_money = stake * m.sl_pct_of_stake / 100.0
    tp_money = stake * tp_pct / 100.0
    return {"lots": lots, "stake": round(stake, 2), "stake_target": round(target, 2), "forced_min": forced_min,
            "sl_pct": m.sl_pct_of_stake, "tp_pct": round(tp_pct, 1),
            "sl_money": round(sl_money, 2), "tp_money": round(tp_money, 2),
            "sl_dist": sl_money / money_per_price, "tp_dist": tp_money / money_per_price,
            "reward_risk": round(tp_money / sl_money, 2) if sl_money else None,
            "tp_scale": [round(small, 2), round(large, 2)],
            "worst_case_all_open": round(sl_money * m.max_open_trades, 2)}


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

    def check(self, server_time: datetime, equity: float, spread_px: float, median_spread_px: float, atr_px: float,
              bot_pnl_today: float = 0.0):
        """Return (ok, reason). The daily stop uses the bot's own P/L so trading alongside it doesn't trip it;
        a wider account-level stop still protects the whole account."""
        self.roll_day(server_time, equity)
        c = self.cfg
        if bot_pnl_today <= -self.day_start_equity * c.daily_loss_pct / 100.0:
            return False, "bot daily loss limit"
        if equity <= self.day_start_equity * (1 - c.account_daily_loss_pct / 100.0):
            return False, "account daily loss limit"
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
