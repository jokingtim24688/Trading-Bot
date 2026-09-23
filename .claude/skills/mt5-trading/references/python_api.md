# Python MetaTrader5 API (M1)

`pip install MetaTrader5 pandas numpy`. **Windows only**: it talks to a running `terminal64.exe` on the same
machine. On Linux/Mac run MT5 + Python under Wine, or use a Windows VPS.

## Connect
```python
import MetaTrader5 as mt5
TF = mt5.TIMEFRAME_M1   # locked

if not mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe"):
    raise SystemExit(f"initialize failed: {mt5.last_error()}")
# optional explicit login (otherwise uses the terminal's logged-in account)
# mt5.login(12345678, password="...", server="Broker-Demo")
print(mt5.terminal_info().trade_allowed, mt5.account_info().trade_mode)  # trade_mode 0 = demo
```
Keep credentials in environment variables or a `.env` file that's in `.gitignore`, never in code.

## Symbols
```python
mt5.symbol_select("XAUUSD", True)           # add to Market Watch
info = mt5.symbol_info("XAUUSD")           # point, digits, trade_contract_size, volume_min/step/max,
                                           # trade_tick_size, trade_tick_value, trade_stops_level, filling_mode
tick = mt5.symbol_info_tick("XAUUSD")      # bid, ask, last, time_msc
stocks = mt5.symbols_get(group="*.US")     # search
```

## M1 data
```python
import pandas as pd
from datetime import datetime, timezone

rates = mt5.copy_rates_from_pos("XAUUSD", TF, 0, 5000)              # latest 5000 bars; row -1 is the forming bar
rates = mt5.copy_rates_range("XAUUSD", TF,
                             datetime(2026, 1, 1, tzinfo=timezone.utc),
                             datetime(2026, 9, 1, tzinfo=timezone.utc))
df = pd.DataFrame(rates)
df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)          # timestamps are SERVER time encoded as epoch
df = df.set_index("time")  # columns: open high low close tick_volume spread real_volume
closed = df.iloc[:-1]      # drop forming bar before computing signals

ticks = mt5.copy_ticks_range("XAUUSD", start, end, mt5.COPY_TICKS_ALL)  # bid/ask/last/volume/flags
```
Note: MT5 returns bar times in the **server's** time zone but labelled as epoch seconds. Treat them as server
time and convert with a known offset if you need true UTC.

## Filling mode helper
```python
def filling_for(symbol):
    fm = mt5.symbol_info(symbol).filling_mode   # bitmask: 1 = FOK, 2 = IOC
    if fm & 1: return mt5.ORDER_FILLING_FOK
    if fm & 2: return mt5.ORDER_FILLING_IOC
    return mt5.ORDER_FILLING_RETURN
```

## Market order with SL/TP
```python
def market_order(symbol, side, lots, sl, tp, magic=260923, comment="agent"):
    tick = mt5.symbol_info_tick(symbol)
    price = tick.ask if side == "buy" else tick.bid
    req = {
        "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": float(lots),
        "type": mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL,
        "price": price, "sl": float(sl), "tp": float(tp), "deviation": 20,
        "magic": magic, "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC, "type_filling": filling_for(symbol),
    }
    check = mt5.order_check(req)                       # validates margin/params without sending
    if check is None or check.retcode != 0:
        return check
    return mt5.order_send(req)                         # result.retcode == mt5.TRADE_RETCODE_DONE (10009)
```

## Other requests
```python
# Pending buy limit
{"action": mt5.TRADE_ACTION_PENDING, "type": mt5.ORDER_TYPE_BUY_LIMIT, "price": p, ...}
# Modify SL/TP of a position
{"action": mt5.TRADE_ACTION_SLTP, "position": ticket, "symbol": s, "sl": new_sl, "tp": new_tp}
# Close a position: opposite deal referencing the ticket
{"action": mt5.TRADE_ACTION_DEAL, "position": ticket, "symbol": s, "volume": vol,
 "type": mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY,
 "price": bid_or_ask, "deviation": 20, "type_filling": filling_for(s)}
# Cancel pending
{"action": mt5.TRADE_ACTION_REMOVE, "order": order_ticket}
```

## Positions, orders, history
```python
mt5.positions_get(symbol="XAUUSD")        # open positions (tuple of namedtuples)
mt5.orders_get()                          # pending orders
mt5.history_deals_get(date_from, date_to) # filled deals → journal
mt5.account_info()                        # balance, equity, margin, margin_free, margin_level, leverage
```

## Wait for each new M1 bar (low CPU)
```python
import time
last = None
while True:
    bar = mt5.copy_rates_from_pos(sym, TF, 1, 1)[0]   # last CLOSED bar
    if bar["time"] != last:
        last = bar["time"]
        on_new_bar()
    time.sleep(1.0)    # poll 1s; wakes within ~1s of the bar close
```

## Errors
`mt5.last_error()` → (code, message). Trade result `retcode` table: see `mt5_platform.md` § 16.
Call `mt5.shutdown()` on exit.
