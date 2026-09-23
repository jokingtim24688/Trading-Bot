"""Agent configuration. The timeframe is fixed to M1 on purpose and is not a CLI option."""
from dataclasses import dataclass, field

TIMEFRAME = "M1"          # locked: every data request and signal uses 1-minute bars
BAR_SECONDS = 60


@dataclass
class HardwareConfig:
    physical_cores: int = 6       # Ryzen 5 7600
    logical_threads: int = 12
    gpu_name_hint: str = "RTX 4060"
    gpu_vram_gb: int = 8
    train_on_gpu: bool = True     # XGBoost device="cuda" when available
    live_predict_threads: int = 2 # leave cores for the MT5 terminal


@dataclass
class LabelConfig:
    atr_period: int = 14
    stop_atr_mult: float = 1.2    # stop distance = ATR * mult
    reward_risk: float = 1.5      # take profit = stop * RR (keep >= 1)
    horizon_bars: int = 240       # bars a training label may take to reach its stop/target (4 hours of M1)


@dataclass
class MoneyConfig:
    """How much goes into each trade and where it exits, all measured against the trade's stake (its margin).

    stake       = stake_pct_of_balance % of balance, committed as margin (minimum lot if that's too small)
    stop loss   = trade has lost sl_pct_of_stake % of its stake
    take profit = trade is up tp_pct % of its stake, where tp_pct slides from tp_pct_small_stake (stakes at or
                  below small_stake) down to tp_pct_large_stake (stakes at or above large_stake), log-scaled between.
                  0 = auto: small_stake = the minimum lot's stake, large_stake = 100x that (1.00 lot on XAUUSD).
    """
    stake_pct_of_balance: float = 0.1
    sl_pct_of_stake: float = 25.0
    tp_pct_small_stake: float = 200.0
    tp_pct_large_stake: float = 50.0
    small_stake: float = 0.0            # account currency; 0 = auto (minimum lot's stake)
    large_stake: float = 0.0            # account currency; 0 = auto (100x the minimum lot's stake)
    max_open_trades: int = 25           # bot positions open at the same time (1 on netting accounts)
    max_spread_to_stop: float = 0.35    # skip if the spread alone would eat 35%+ of the stop distance


@dataclass
class RiskConfig:
    risk_per_trade_pct: float = 0.5
    daily_loss_pct: float = 3.0          # bot's OWN losses today (your manual trades don't count)
    account_daily_loss_pct: float = 6.0  # whole-account safety net: bot pauses if the account is down this much today
    max_trades_per_day: int = 100       # new entries per day (at most one per M1 candle)
    max_spread_to_atr: float = 0.15
    max_spread_vs_median: float = 1.8
    # Server-time hours when new entries are allowed (typical GMT+2/+3 broker: London open .. NY afternoon)
    session_start_hour: int = 9
    session_end_hour: int = 22
    rollover_blackout: tuple = (23, 1)   # server hours [start, end) with no entries; wraps midnight
    magic: int = 260923


@dataclass
class AgentConfig:
    symbol: str = "XAUUSD"
    threshold: float = 0.55
    history_bars: int = 5000      # bars fetched each cycle (enough warm-up for EMA 3000)
    model_dir: str = "models"
    log_dir: str = "logs"
    hardware: HardwareConfig = field(default_factory=HardwareConfig)
    labels: LabelConfig = field(default_factory=LabelConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    money: MoneyConfig = field(default_factory=MoneyConfig)
