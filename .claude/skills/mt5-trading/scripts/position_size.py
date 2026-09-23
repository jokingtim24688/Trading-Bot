#!/usr/bin/env python3
"""Lot size from risk % and stop distance.

Manual specs (works anywhere):
    python position_size.py --equity 10000 --risk 1 --entry 2650.00 --stop 2647.60 \
        --tick-size 0.01 --tick-value 1.0 --step 0.01 --min-lot 0.01
Read specs from a running MT5 terminal (Windows):
    python position_size.py --symbol XAUUSD --risk 0.5 --entry 2650 --stop 2647.6
"""
import argparse
import math


def lots_for_risk(equity, risk_pct, stop_distance, tick_size, tick_value, step, vmin, vmax):
    loss_per_lot = stop_distance / tick_size * tick_value
    raw = equity * risk_pct / 100 / loss_per_lot
    lots = math.floor(raw / step + 1e-9) * step
    return raw, (0.0 if lots < vmin else min(lots, vmax)), loss_per_lot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol")
    ap.add_argument("--equity", type=float)
    ap.add_argument("--risk", type=float, required=True, help="percent of equity, e.g. 0.5")
    ap.add_argument("--entry", type=float, required=True)
    ap.add_argument("--stop", type=float, required=True)
    ap.add_argument("--tick-size", type=float)
    ap.add_argument("--tick-value", type=float, help="account currency per tick per 1.00 lot")
    ap.add_argument("--step", type=float, default=0.01)
    ap.add_argument("--min-lot", type=float, default=0.01)
    ap.add_argument("--max-lot", type=float, default=100.0)
    a = ap.parse_args()

    if a.symbol:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            raise SystemExit(f"MT5 initialize failed: {mt5.last_error()}")
        mt5.symbol_select(a.symbol, True)
        i = mt5.symbol_info(a.symbol)
        a.tick_size, a.tick_value = i.trade_tick_size, (i.trade_tick_value_loss or i.trade_tick_value)
        a.step, a.min_lot, a.max_lot = i.volume_step, i.volume_min, i.volume_max
        a.equity = a.equity or mt5.account_info().equity
        mt5.shutdown()

    if None in (a.equity, a.tick_size, a.tick_value):
        raise SystemExit("need --equity, --tick-size and --tick-value (or --symbol with MT5 running)")

    dist = abs(a.entry - a.stop)
    raw, lots, lpl = lots_for_risk(a.equity, a.risk, dist, a.tick_size, a.tick_value, a.step, a.min_lot, a.max_lot)
    risk_money = a.equity * a.risk / 100
    print(f"stop distance     : {dist:g} ({dist / a.tick_size:.0f} ticks)")
    print(f"loss per 1.00 lot : {lpl:,.2f}")
    print(f"risk budget       : {risk_money:,.2f} ({a.risk}% of {a.equity:,.2f})")
    print(f"exact lots        : {raw:.4f}")
    if lots == 0:
        print(f"LOTS              : 0 -> even {a.min_lot} lot would risk {lpl * a.min_lot:,.2f}; widen budget or skip trade")
    else:
        print(f"LOTS              : {lots:g} (actual risk {lpl * lots:,.2f})")


if __name__ == "__main__":
    main()
