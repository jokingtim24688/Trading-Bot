"""Live M1 loop.

    python -m agent.run --symbol XAUUSD --threshold 0.55            # paper (default, no orders)
    python -m agent.run --symbol XAUUSD --threshold 0.55 --live     # real orders, DEMO account only
    python -m agent.run ... --live --allow-real                     # real-money account (be sure)

Create a file named STOP in the working directory to flatten and exit.
"""
import argparse
import time
from pathlib import Path

from . import hardware
from .config import AgentConfig

PLAN = hardware.apply()

from .broker import Journal, LiveBroker, MT5Data, PaperBroker  # noqa: E402
from .features import atr, build_features  # noqa: E402
from .model import SignalModel  # noqa: E402
from .risk import RiskGate, lots_for_risk  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--threshold", type=float, default=0.55)
    ap.add_argument("--risk", type=float, default=None, help="risk %% per trade (default from config)")
    ap.add_argument("--terminal", default=None, help="path to terminal64.exe (optional)")
    ap.add_argument("--live", action="store_true", help="send real orders (demo account unless --allow-real)")
    ap.add_argument("--allow-real", action="store_true")
    ap.add_argument("--paper-equity", type=float, default=10_000)
    args = ap.parse_args()

    cfg = AgentConfig(symbol=args.symbol, threshold=args.threshold)
    if args.risk is not None:
        cfg.risk.risk_per_trade_pct = args.risk

    data = MT5Data(cfg.symbol, args.terminal)
    spec = data.spec()
    if args.live and not data.is_demo() and not args.allow_real:
        raise SystemExit("Account is REAL. Refusing to trade without --allow-real.")
    mode = ("demo" if data.is_demo() else "real") if args.live else "paper"
    broker = LiveBroker(data, cfg.risk.magic, mode) if args.live else PaperBroker(args.paper_equity, spec, cfg.symbol, data.tick)
    model = SignalModel.load(cfg.model_dir, cfg.symbol, cfg.hardware)
    gate = RiskGate(cfg.risk)
    journal = Journal(cfg.log_dir, cfg.symbol, "paper" if mode == "paper" else "live")
    L = cfg.labels

    print(f"[{mode}] {cfg.symbol} M1 | threshold {cfg.threshold} | risk {cfg.risk.risk_per_trade_pct}% | hw {PLAN}")
    print(f"tracking bot trades with magic {cfg.risk.magic} in data/trades.db; your own trades are left alone")
    if getattr(broker, "netting", False):
        print("NETTING account: positions on one symbol merge, so the bot won't trade while you hold this symbol.")

    def report_exits(exits, bar_time=""):
        for x in exits:
            journal.log(event="exit", bar_time=bar_time, symbol=cfg.symbol, price=x["exit"],
                        equity=broker.account_equity(), note=f"#{x['id']} {x['reason']} pnl={x['pnl']:.2f}")
            print(f"EXIT #{x['id']} {x['reason']} @ {x['exit']} pnl {x['pnl']:+.2f}")
    journal.log(event="start", symbol=cfg.symbol, note=f"mode={mode} thr={cfg.threshold}")
    last_bar = None

    try:
        while True:
            if Path("STOP").exists():
                broker.close_all()
                journal.log(event="kill_switch", symbol=cfg.symbol)
                print("STOP file found: flattened and exiting.")
                break

            report_exits(broker.sync())                    # live: catch SL/TP/manual exits within ~1s
            bar_time = data.m1_bars(1).index[-1]          # cheap poll for a new closed bar
            if bar_time == last_bar:
                time.sleep(1.0)
                continue
            last_bar = bar_time
            bars = data.m1_bars(cfg.history_bars)
            bar = bars.iloc[-1]
            spread_px = float(bar["spread"]) * spec.point
            bar_epoch = int(bar_time.timestamp())          # server-time epoch, same clock as the chart

            report_exits(broker.on_bar(bar, spread_px, bar_epoch), bar_time)

            if broker.has_position():
                continue

            feats = build_features(bars, spec.point)
            row = feats.iloc[[-1]]
            if row.isna().any(axis=1).iloc[0]:
                continue
            p_short, _, p_long = model.predict_proba(row)[0]
            a = float(atr(bars, L.atr_period).iloc[-1])
            median_spread_px = float(bars["spread"].tail(1440).median()) * spec.point
            equity = broker.account_equity()

            side = None
            if p_long >= cfg.threshold and p_long > p_short:
                side, prob = "buy", p_long
            elif p_short >= cfg.threshold and p_short > p_long:
                side, prob = "sell", p_short
            if side is None:
                continue

            ok, reason = gate.check(bar_time.to_pydatetime(), equity, spread_px, median_spread_px, a,
                                    bot_pnl_today=broker.bot_pnl_today())
            if ok and getattr(broker, "netting", False) and broker.foreign_position():
                ok, reason = False, "netting account: you hold this symbol, bot waits"
            if not ok:
                journal.log(event="skip", bar_time=bar_time, symbol=cfg.symbol, side=side, prob=round(prob, 3), note=reason)
                continue

            stop = a * L.stop_atr_mult
            min_stop = spec.stops_level_points * spec.point
            stop = max(stop, min_stop * 1.1)
            lots = lots_for_risk(equity, cfg.risk.risk_per_trade_pct, stop, spec)
            if lots <= 0:
                journal.log(event="skip", bar_time=bar_time, symbol=cfg.symbol, side=side, note="size below volume_min")
                continue

            t = data.tick()
            price = t.ask if side == "buy" else t.bid
            sl = price - stop if side == "buy" else price + stop
            tp = price + stop * L.reward_risk if side == "buy" else price - stop * L.reward_risk
            risk_money = round(stop / spec.tick_size * spec.tick_value * lots, 2)
            filled, note = broker.open(side, lots, price, sl, tp, prob=round(float(prob), 3),
                                       risk_money=risk_money, open_bar=bar_epoch + 60)
            journal.log(event="order" if filled else "reject", bar_time=bar_time, symbol=cfg.symbol, side=side,
                        lots=lots, price=price, sl=sl, tp=tp, prob=round(prob, 3), equity=equity, note=note)
            print(f"{bar_time} {side} {lots} @ {price} sl {sl:.5g} tp {tp:.5g} p={prob:.2f} -> {note}")
            if filled:
                gate.record_trade()
    except KeyboardInterrupt:
        print("interrupted (positions left as they are; server SL/TP stay active in live mode)")
    finally:
        journal.log(event="stop", symbol=cfg.symbol, equity=broker.account_equity())
        data.shutdown()


if __name__ == "__main__":
    main()
