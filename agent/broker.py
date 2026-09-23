"""MT5 data + execution. `PaperBroker` simulates fills on M1 bars; `LiveBroker` sends real orders."""
import csv
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import ledger
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

    def margin_per_lot(self, side: str = "buy", price: float | None = None) -> float:
        """Margin MT5 would require for 1.00 lot at this price (uses the account's real leverage)."""
        t = mt5.symbol_info_tick(self.symbol)
        price = price or (t.ask if side == "buy" else t.bid)
        m = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL, self.symbol, 1.0, price)
        return float(m or 0.0)

    def is_demo(self) -> bool:
        return mt5.account_info().trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO

    def shutdown(self):
        mt5.shutdown()


class PaperBroker:
    """Simulated fills on closed M1 bars (stop wins if a bar touches both). Every trade goes to the ledger, and
    paper balance and open paper trades survive restarts because they're rebuilt from the ledger."""

    def __init__(self, start_equity: float, spec: SymbolSpec, symbol: str, tick_fn, mode: str = "paper"):
        self.mode = mode           # "paper" (live prices) or "replay" (historical candles)
        self.start_equity = start_equity
        self.spec = spec
        self.symbol = symbol
        self.tick_fn = tick_fn
        self.positions = ledger.open_trades(mode, symbol)
        self.clock = None          # replay sets this to the candle's UTC time (ISO), so days/hours are historical ones

    def _stamp(self):
        return self.clock() if self.clock else None

    def _pnl(self, side, entry, exit_px, lots):
        move = (exit_px - entry) if side == "buy" else (entry - exit_px)
        return move / self.spec.tick_size * self.spec.tick_value * lots

    def account_balance(self) -> float:
        return self.start_equity + ledger.realized_pnl(self.mode)

    def account_equity(self) -> float:
        return self.account_balance() + self.floating_pnl()

    def floating_pnl(self) -> float:
        if not self.positions:
            return 0.0
        t = self.tick_fn()
        return sum(self._pnl(p["side"], p["entry"], t.bid if p["side"] == "buy" else t.ask, p["lots"]) for p in self.positions)

    def bot_pnl_today(self) -> float:
        day = (self._stamp() or ledger._now())[:10]
        return ledger.realized_pnl(self.mode, day=day) + self.floating_pnl()

    def has_position(self) -> bool:
        return bool(self.positions)

    def open_count(self) -> int:
        return len(self.positions)

    def foreign_position(self) -> bool:
        return False

    def open(self, side, lots, price, sl, tp, prob=None, risk_money=None, open_bar=None, stake=None, **_):
        tid = ledger.open_trade(self.mode, self.symbol, side, lots, price, sl, tp, prob, risk_money, None, open_bar, stake,
                                open_utc=self._stamp())
        self.positions = ledger.open_trades(self.mode, self.symbol)
        return True, f"paper fill #{tid}"

    def on_bar(self, bar, spread_px, bar_epoch=None):
        exits, still_open = [], []
        for p in self.positions:
            if p["side"] == "buy":
                hit_sl, hit_tp = bar["low"] <= p["sl"], bar["high"] >= p["tp"]
            else:
                hit_sl, hit_tp = bar["high"] + spread_px >= p["sl"], bar["low"] + spread_px <= p["tp"]
            if not (hit_sl or hit_tp):
                still_open.append(p)
                continue
            exit_px = p["sl"] if hit_sl else p["tp"]
            pnl = self._pnl(p["side"], p["entry"], exit_px, p["lots"])
            ledger.close_trade(p["id"], exit_px, "sl" if hit_sl else "tp", pnl, close_bar=bar_epoch, close_utc=self._stamp())
            exits.append({"id": p["id"], "exit": exit_px, "pnl": pnl, "reason": "sl" if hit_sl else "tp"})
        self.positions = still_open
        return exits

    def sync(self):
        return []

    def open_list(self) -> list[dict]:
        return list(self.positions)

    def close_one(self, trade: dict, reason: str = "early") -> dict:
        """Close one paper trade at the current market price (bot's own decision, before SL/TP)."""
        t = self.tick_fn()
        px = t.bid if trade["side"] == "buy" else t.ask
        pnl = self._pnl(trade["side"], trade["entry"], px, trade["lots"])
        ledger.close_trade(trade["id"], px, reason, pnl, close_utc=self._stamp())
        self.positions = [p for p in self.positions if p["id"] != trade["id"]]
        return {"id": trade["id"], "exit": px, "pnl": pnl, "reason": reason}

    def close_all(self, reason="kill"):
        t = self.tick_fn()
        for p in self.positions:
            px = t.bid if p["side"] == "buy" else t.ask
            ledger.close_trade(p["id"], px, reason, self._pnl(p["side"], p["entry"], px, p["lots"]), close_utc=self._stamp())
        self.positions = []


REASONS = {}   # filled lazily from mt5 constants


def _reason(code) -> str:
    if not REASONS and mt5 is not None:
        REASONS.update({mt5.DEAL_REASON_SL: "sl", mt5.DEAL_REASON_TP: "tp", mt5.DEAL_REASON_SO: "stop_out",
                        mt5.DEAL_REASON_EXPERT: "bot/app", mt5.DEAL_REASON_CLIENT: "manual (desktop)",
                        mt5.DEAL_REASON_MOBILE: "manual (mobile)", mt5.DEAL_REASON_WEB: "manual (web)"})
    return REASONS.get(code, "closed")


def sync_ledger(modes=("demo", "real"), symbol: str | None = None) -> list[dict]:
    """Reconcile open ledger trades with MT5: close rows whose position is gone (using the real deals: exit price,
    P/L incl. commission and swap, and why it closed), and track SL/TP edits. Used by the agent and by the app."""
    closed = []
    for mode in modes:
        for t in ledger.open_trades(mode, symbol):
            pos = mt5.positions_get(ticket=t["ticket"]) if t["ticket"] else None
            if pos:
                p = pos[0]
                if (p.sl or None) != (t["sl"] or None) or (p.tp or None) != (t["tp"] or None):
                    ledger.update_levels(t["id"], sl=p.sl, tp=p.tp)
                continue
            deals = mt5.history_deals_get(position=t["ticket"]) or []
            outs = [d for d in deals if d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY)]
            if not outs:
                continue           # history not updated yet; try again next time
            last = outs[-1]
            pnl = sum(d.profit + d.commission + d.swap + getattr(d, "fee", 0.0) for d in deals)
            reason = _reason(last.reason)
            if t.get("close_hint") and last.reason == mt5.DEAL_REASON_EXPERT:
                reason = t["close_hint"]          # "early" / "kill": why the bot or app closed it
            ledger.close_trade(t["id"], last.price, reason, pnl, close_bar=int(last.time))
            closed.append({"id": t["id"], "exit": last.price, "pnl": pnl, "reason": reason})
    return closed


class LiveBroker:
    """Real orders on MT5. Only positions carrying the bot's magic number are the bot's; your own trades (magic 0)
    and Hermes' trades (another magic) are never touched or counted. `sync()` reconciles the ledger with MT5 so exits
    made by the server (SL/TP), by you in MT5, or by the kill switch are recorded with the real P/L."""

    def __init__(self, data: MT5Data, magic: int, mode: str):
        self.data = data
        self.symbol = data.symbol
        self.magic = magic
        self.mode = mode           # "demo" or "real"
        self.netting = mt5.account_info().margin_mode != mt5.ACCOUNT_MARGIN_MODE_RETAIL_HEDGING
        self.adopt_orphans()

    def account_equity(self) -> float:
        return mt5.account_info().equity

    def account_balance(self) -> float:
        return mt5.account_info().balance

    def open_count(self) -> int:
        return len(self._positions())

    def _positions(self):
        return [p for p in (mt5.positions_get(symbol=self.symbol) or []) if p.magic == self.magic]

    def has_position(self) -> bool:
        return bool(self._positions())

    def foreign_position(self) -> bool:
        """True if someone else (you, Hermes) holds a position on this symbol."""
        return any(p.magic != self.magic for p in (mt5.positions_get(symbol=self.symbol) or []))

    def floating_pnl(self) -> float:
        return sum(p.profit for p in self._positions())

    def bot_pnl_today(self) -> float:
        day = (self._stamp() or ledger._now())[:10]
        return ledger.realized_pnl(self.mode, day=day) + self.floating_pnl()

    def adopt_orphans(self):
        """Record bot positions that exist in MT5 but not in the ledger (e.g. the app crashed right after a fill)."""
        known = {t["ticket"] for t in ledger.open_trades(self.mode, self.symbol)}
        for p in self._positions():
            if p.ticket not in known:
                ledger.open_trade(self.mode, self.symbol, "buy" if p.type == mt5.POSITION_TYPE_BUY else "sell",
                                  p.volume, p.price_open, p.sl, p.tp, ticket=p.ticket, open_bar=int(p.time))

    def _filling(self):
        fm = mt5.symbol_info(self.symbol).filling_mode
        if fm & 1:
            return mt5.ORDER_FILLING_FOK
        if fm & 2:
            return mt5.ORDER_FILLING_IOC
        return mt5.ORDER_FILLING_RETURN

    def open(self, side, lots, price, sl, tp, prob=None, risk_money=None, open_bar=None, stake=None, comment="m1-agent"):
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
        # for a new market position the position ticket equals the opening order ticket
        tid = ledger.open_trade(self.mode, self.symbol, side, res.volume, res.price or price, req["sl"], req["tp"],
                                prob, risk_money, res.order, open_bar, stake)
        return True, f"filled {res.volume} @ {res.price} (ticket {res.order}, ledger #{tid})"

    def on_bar(self, bar, spread_px, bar_epoch=None):
        return self.sync()

    def sync(self) -> list[dict]:
        return sync_ledger((self.mode,), self.symbol)

    def open_list(self) -> list[dict]:
        return ledger.open_trades(self.mode, self.symbol)

    def _close_ticket(self, ticket: int) -> bool:
        pos = mt5.positions_get(ticket=ticket)
        if not pos:
            return False
        p, t = pos[0], mt5.symbol_info_tick(self.symbol)
        buy = p.type == mt5.POSITION_TYPE_BUY
        res = mt5.order_send({
            "action": mt5.TRADE_ACTION_DEAL, "symbol": self.symbol, "position": p.ticket, "volume": p.volume,
            "type": mt5.ORDER_TYPE_SELL if buy else mt5.ORDER_TYPE_BUY,
            "price": t.bid if buy else t.ask, "deviation": 30, "magic": self.magic, "type_filling": self._filling(),
        })
        return res is not None and res.retcode == mt5.TRADE_RETCODE_DONE

    def close_one(self, trade: dict, reason: str = "early") -> dict | None:
        """Close one bot position at market before SL/TP; the ledger records `reason` (scored as a smaller loss)."""
        ledger.set_close_hint(trade["id"], reason)
        if not self._close_ticket(trade["ticket"]):
            return None
        done = [x for x in self.sync() if x["id"] == trade["id"]]
        return done[0] if done else None

    def close_all(self, reason="kill"):
        for t in ledger.open_trades(self.mode, self.symbol):
            ledger.set_close_hint(t["id"], reason)
        for p in self._positions():
            t = mt5.symbol_info_tick(self.symbol)
            buy = p.type == mt5.POSITION_TYPE_BUY
            mt5.order_send({
                "action": mt5.TRADE_ACTION_DEAL, "symbol": self.symbol, "position": p.ticket, "volume": p.volume,
                "type": mt5.ORDER_TYPE_SELL if buy else mt5.ORDER_TYPE_BUY,
                "price": t.bid if buy else t.ask, "deviation": 30, "magic": self.magic,
                "type_filling": self._filling(),
            })
        self.sync()
