"""MT5 data + execution. `PaperBroker` simulates fills on M1 bars; `LiveBroker` sends real orders."""
import csv
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .risk import SymbolSpec

try:
    import MetaTrader5 as mt5   # Windows only
except ImportError:            # allows importing the package elsewhere (tests, docs)
    mt5 = None


class Journal:
    FIELDS = ["time_utc", "bar_time", "event", "symbol", "side", "lots", "price", "sl", "tp", "prob", "equity", "note"]

    def __init__(self, log_dir: str, symbol: str, mode: str):
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        self.path = Path(log_dir) / f"journal_{symbol}_M1_{mode}.csv"
        new = not self.path.exists()
        self.f = open(self.path, "a", newline="")
        self.w = csv.DictWriter(self.f, fieldnames=self.FIELDS)
        if new:
            self.w.writeheader()

    def log(self, **row):
        row.setdefault("time_utc", datetime.now(timezone.utc).isoformat(timespec="seconds"))
        self.w.writerow({k: row.get(k, "") for k in self.FIELDS})
        self.f.flush()


class MT5Data:
    def __init__(self, symbol: str, terminal_path: str | None = None):
        if mt5 is None:
            raise RuntimeError("MetaTrader5 package not available (Windows + `pip install MetaTrader5`).")
        ok = mt5.initialize(path=terminal_path) if terminal_path else mt5.initialize()
        if not ok:
            raise RuntimeError(f"mt5.initialize failed: {mt5.last_error()}")
        if not mt5.symbol_select(symbol, True):
            raise RuntimeError(f"symbol {symbol} not found on this account")
        self.symbol = symbol

    def spec(self) -> SymbolSpec:
        i = mt5.symbol_info(self.symbol)
        return SymbolSpec(point=i.point, tick_size=i.trade_tick_size,
                          tick_value=i.trade_tick_value_loss or i.trade_tick_value,
                          volume_min=i.volume_min, volume_step=i.volume_step, volume_max=i.volume_max,
                          stops_level_points=i.trade_stops_level)

    def m1_bars(self, n: int) -> pd.DataFrame:
        """Last n CLOSED M1 bars (the forming bar is dropped)."""
        r = mt5.copy_rates_from_pos(self.symbol, mt5.TIMEFRAME_M1, 1, n)
        if r is None or len(r) == 0:
            raise RuntimeError(f"no M1 data: {mt5.last_error()}")
        df = pd.DataFrame(r)
        df["time"] = pd.to_datetime(df["time"], unit="s")   # server time, naive
        return df.set_index("time")

    def tick(self):
        return mt5.symbol_info_tick(self.symbol)

    def is_demo(self) -> bool:
        return mt5.account_info().trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO

    def shutdown(self):
        mt5.shutdown()


class PaperBroker:
    """Tracks one simulated position per symbol; SL/TP checked on each closed M1 bar (stop first if both)."""

    def __init__(self, equity: float, spec: SymbolSpec):
        self.equity = equity
        self.spec = spec
        self.pos = None

    def account_equity(self) -> float:
        return self.equity

    def has_position(self) -> bool:
        return self.pos is not None

    def open(self, side, lots, price, sl, tp, **_):
        self.pos = {"side": side, "lots": lots, "entry": price, "sl": sl, "tp": tp}
        return True, "paper fill"

    def on_bar(self, bar, spread_px):
        if not self.pos:
            return None
        p = self.pos
        if p["side"] == "buy":
            hit_sl, hit_tp = bar["low"] <= p["sl"], bar["high"] >= p["tp"]
        else:
            hit_sl, hit_tp = bar["high"] + spread_px >= p["sl"], bar["low"] + spread_px <= p["tp"]
        if not (hit_sl or hit_tp):
            return None
        exit_px = p["sl"] if hit_sl else p["tp"]
        move = (exit_px - p["entry"]) if p["side"] == "buy" else (p["entry"] - exit_px)
        pnl = move / self.spec.tick_size * self.spec.tick_value * p["lots"]
        self.equity += pnl
        self.pos = None
        return {"exit": exit_px, "pnl": pnl, "reason": "sl" if hit_sl else "tp"}

    def close_all(self, price=None):
        self.pos = None


class LiveBroker:
    def __init__(self, data: MT5Data, magic: int):
        self.data = data
        self.symbol = data.symbol
        self.magic = magic

    def account_equity(self) -> float:
        return mt5.account_info().equity

    def _positions(self):
        return [p for p in (mt5.positions_get(symbol=self.symbol) or []) if p.magic == self.magic]

    def has_position(self) -> bool:
        return bool(self._positions())

    def _filling(self):
        fm = mt5.symbol_info(self.symbol).filling_mode
        if fm & 1:
            return mt5.ORDER_FILLING_FOK
        if fm & 2:
            return mt5.ORDER_FILLING_IOC
        return mt5.ORDER_FILLING_RETURN

    def open(self, side, lots, price, sl, tp, comment="m1-agent"):
        digits = mt5.symbol_info(self.symbol).digits
        req = {
            "action": mt5.TRADE_ACTION_DEAL, "symbol": self.symbol, "volume": float(lots),
            "type": mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL,
            "price": price, "sl": round(sl, digits), "tp": round(tp, digits), "deviation": 20,
            "magic": self.magic, "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC, "type_filling": self._filling(),
        }
        chk = mt5.order_check(req)
        if chk is None or chk.retcode != 0:
            return False, f"order_check failed: {getattr(chk, 'comment', mt5.last_error())}"
        res = mt5.order_send(req)
        if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
            return False, f"order_send retcode {getattr(res, 'retcode', None)} {getattr(res, 'comment', mt5.last_error())}"
        return True, f"filled {res.volume} @ {res.price}"

    def on_bar(self, bar, spread_px):
        return None   # the server manages SL/TP

    def close_all(self, price=None):
        for p in self._positions():
            t = mt5.symbol_info_tick(self.symbol)
            buy = p.type == mt5.POSITION_TYPE_BUY
            mt5.order_send({
                "action": mt5.TRADE_ACTION_DEAL, "symbol": self.symbol, "position": p.ticket, "volume": p.volume,
                "type": mt5.ORDER_TYPE_SELL if buy else mt5.ORDER_TYPE_BUY,
                "price": t.bid if buy else t.ask, "deviation": 30, "magic": self.magic,
                "type_filling": self._filling(),
            })
