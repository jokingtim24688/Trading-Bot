"""Live M1 loop.

    python -m agent.run --symbol XAUUSD --threshold 0.55            # paper (default, no orders)
    python -m agent.run --symbol XAUUSD --threshold 0.55 --live     # real orders, DEMO account only
    python -m agent.run ... --live --allow-real                     # real-money account (be sure)

Create a file named STOP in the working directory to flatten and exit.
"""
import argparse
import json
import time
from pathlib import Path

from . import hardware
from .config import AgentConfig

PLAN = hardware.apply()

from .broker import Journal, LiveBroker, MT5Data, PaperBroker  # noqa: E402
from .features import atr, build_features  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

from . import learn, ledger, score as scoring  # noqa: E402
from .model import SignalModel  # noqa: E402
from .practice import Practice  # noqa: E402
from .pro import SETUP_NAMES, active_setups, primary_setup  # noqa: E402
from .risk import RiskGate, stake_plan  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--threshold", type=float, default=0.55)
    ap.add_argument("--stake-pct", type=float, default=None, help="margin per trade, %% of balance (default 0.1)")
    ap.add_argument("--sl-pct", type=float, default=None, help="stop when this %% of the stake is lost (default 25)")
    ap.add_argument("--tp-small", type=float, default=None, help="take-profit %% of stake for small stakes (default 200)")
    ap.add_argument("--tp-large", type=float, default=None, help="take-profit %% of stake for large stakes (default 50)")
    ap.add_argument("--small-stake", type=float, default=None, help="stake (account currency) at/below which --tp-small applies")
    ap.add_argument("--large-stake", type=float, default=None, help="stake at/above which --tp-large applies")
    ap.add_argument("--max-open", type=int, default=None, help="max bot trades open at once (default 10)")
    ap.add_argument("--ref-leverage", type=float, default=None, help="size stop/target as if leverage were 1:N (0 = real)")
    ap.add_argument("--no-early-exit", action="store_true", help="always hold trades until SL or TP")
    ap.add_argument("--no-learned", action="store_true", help="ignore the bot's learned rules (data/learned_rules.json)")
    ap.add_argument("--practice", action="store_true", help="paper only: trade the model's top 10%% setups instead of the threshold")
    ap.add_argument("--sl-score-mult", type=float, default=None, help="score penalty multiplier when a stop loss hits (default 1.5)")
    ap.add_argument("--terminal", default=None, help="path to terminal64.exe (optional)")
    ap.add_argument("--live", action="store_true", help="send real orders (demo account unless --allow-real)")
    ap.add_argument("--allow-real", action="store_true")
    ap.add_argument("--paper-equity", type=float, default=10_000)
    args = ap.parse_args()

    cfg = AgentConfig(symbol=args.symbol, threshold=args.threshold)
    m = cfg.money
    for arg, attr in (("stake_pct", "stake_pct_of_balance"), ("sl_pct", "sl_pct_of_stake"), ("tp_small", "tp_pct_small_stake"),
                      ("tp_large", "tp_pct_large_stake"), ("small_stake", "small_stake"), ("large_stake", "large_stake"),
                      ("max_open", "max_open_trades"), ("ref_leverage", "ref_leverage")):
        if getattr(args, arg) is not None:
            setattr(m, attr, getattr(args, arg))
    if args.no_early_exit:
        m.early_exit = False
    if args.sl_score_mult is not None:
        scoring.SL_MULT = args.sl_score_mult

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

    max_open = 1 if getattr(broker, "netting", False) else m.max_open_trades
    print(f"[{mode}] {cfg.symbol} M1 | threshold {cfg.threshold} | stake {m.stake_pct_of_balance}% of balance | "
          f"SL -{m.sl_pct_of_stake}% / TP +{m.tp_pct_small_stake}->{m.tp_pct_large_stake}% of stake | "
          f"max {max_open} open | hw {PLAN}")
    rule = model.meta.get("exit_rule") or {}
    if not rule.get("margin_rate"):
        print("WARNING: this model was trained with ATR exits, not the stake rules. Retrain on the Train tab.")
    print(f"tracking bot trades with magic {cfg.risk.magic} in data/trades.db; your own trades are left alone")
    if getattr(broker, "netting", False):
        print("NETTING account: positions on one symbol merge, so the bot won't trade while you hold this symbol.")

    status_path = Path(cfg.log_dir).parent / "data" / "agent_status.json"
    probs = {"buy": None, "sell": None, "need": None, "setups": []}
    practice = Practice() if args.practice and mode == "paper" else None
    if practice:
        print("practice mode: trading the model's top 10% setups (paper only)")

    def say(bar_time, decision, reason=""):
        """One line per closed candle in the live log + data/agent_status.json for the Market tab."""
        hhmm = str(bar_time)[11:16]
        pb, ps = probs["buy"], probs["sell"]
        need = probs["need"] if practice is not None and probs["need"] else cfg.threshold
        conf = f"buy {pb:.1%} / sell {ps:.1%} (needs {need:.1%})" if pb is not None else "model warming up"
        print(f"{hhmm} {conf} -> {decision}{': ' + reason if reason else ''}", flush=True)
        try:
            status_path.parent.mkdir(exist_ok=True)
            status_path.write_text(json.dumps({
                "time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "bar": hhmm, "mode": mode,
                "symbol": cfg.symbol, "p_buy": pb, "p_sell": ps, "threshold": cfg.threshold, "need": need,
                "practice": practice is not None, "setups": [SETUP_NAMES[k] for k in probs["setups"]],
                "decision": decision,
                "reason": reason, "open": broker.open_count(), "max_open": max_open}))
        except OSError:
            pass

    def report_exits(exits, bar_time=""):
        for x in exits:
            row = next((r for r in ledger.recent(50) if r["id"] == x["id"]), {})
            pts = row.get("score")
            journal.log(event="exit", bar_time=bar_time, symbol=cfg.symbol, price=x["exit"],
                        equity=broker.account_equity(), note=f"#{x['id']} {x['reason']} pnl={x['pnl']:.2f} score={pts}")
            print(f"EXIT #{x['id']} {x['reason']} @ {x['exit']} pnl {x['pnl']:+.2f}"
                  + (f" score {pts:+.1f}" if pts is not None else ""))
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

            feats = build_features(bars, spec.point)
            row = feats.iloc[[-1]]
            if row.isna().any(axis=1).iloc[0]:
                say(bar_time, "waiting", "not enough history for the indicators yet")
                continue
            p_short, _, p_long = model.predict_proba(row)[0]
            probs["setups"] = active_setups(row.iloc[0].to_dict())
            probs.update(buy=float(p_long), sell=float(p_short))

            # early exit: close a trade before its stop when the model has clearly turned against it
            if m.early_exit:
                for t in broker.open_list():
                    own, opp = (p_long, p_short) if t["side"] == "buy" else (p_short, p_long)
                    if opp >= cfg.threshold and opp >= m.early_exit_ratio * own:
                        x = broker.close_one(t, "early")
                        if x:
                            report_exits([x], bar_time)

            if broker.open_count() >= max_open:
                say(bar_time, "holding", f"{max_open}/{max_open} trades already open")
                continue
            a = float(atr(bars, L.atr_period).iloc[-1])
            median_spread_px = float(bars["spread"].tail(1440).median()) * spec.point
            equity = broker.account_equity()

            side = None
            if p_long >= cfg.threshold and p_long > p_short:
                side, prob = "buy", p_long
            elif p_short >= cfg.threshold and p_short > p_long:
                side, prob = "sell", p_short
            if practice is not None:
                side, prob, cut = practice.decide(p_long, p_short)
                probs["need"] = cut
                if side is None:
                    say(bar_time, "waiting for a strong setup",
                        "practice mode enters on the best ~10% of readings (about 1 candle in 10)" if cut else
                        f"practice mode: learning what a strong reading looks like ({len(practice.seen)}/60 candles)")
                    continue
            if side is None:
                say(bar_time, "waiting for a strong setup", "no side reached the needed confidence on this candle")
                continue

            if not args.no_learned:
                why = learn.block_reason(learn.load_rules(), "buy" if side == "buy" else "sell", float(prob),
                                         datetime.now(timezone.utc).hour, setup=primary_setup(probs["setups"], side))
                if why:
                    journal.log(event="skip", bar_time=bar_time, symbol=cfg.symbol, side=side, prob=round(prob, 3), note=why)
                    say(bar_time, f"skipped {side}", why)
                    continue

            ok, reason = gate.check(bar_time.to_pydatetime(), equity, spread_px, median_spread_px, a,
                                    bot_pnl_today=broker.bot_pnl_today())
            if ok and getattr(broker, "netting", False) and broker.foreign_position():
                ok, reason = False, "netting account: you hold this symbol, bot waits"
            if not ok:
                journal.log(event="skip", bar_time=bar_time, symbol=cfg.symbol, side=side, prob=round(prob, 3), note=reason)
                say(bar_time, f"skipped {side}", reason)
                continue

            t = data.tick()
            price = t.ask if side == "buy" else t.bid
            plan = stake_plan(broker.account_balance(), data.margin_per_lot(side, price), spec, m, price)
            if plan is None:
                journal.log(event="skip", bar_time=bar_time, symbol=cfg.symbol, side=side, note="no margin data")
                say(bar_time, f"skipped {side}", "no margin data from MT5")
                continue
            min_stop = spec.stops_level_points * spec.point
            if plan["sl_dist"] <= min_stop:
                journal.log(event="skip", bar_time=bar_time, symbol=cfg.symbol, side=side,
                            note=f"stop {plan['sl_dist']:.5g} inside broker stops level {min_stop:.5g}")
                say(bar_time, f"skipped {side}", "stop is inside the broker's minimum distance")
                continue
            if spread_px > plan["sl_dist"] * m.max_spread_to_stop:
                journal.log(event="skip", bar_time=bar_time, symbol=cfg.symbol, side=side,
                            note=f"spread {spread_px:.5g} is over {int(m.max_spread_to_stop * 100)}% of the stop")
                say(bar_time, f"skipped {side}", f"spread {spread_px:.2f} is too wide for the stop")
                continue
            lots = plan["lots"]
            sl = price - plan["sl_dist"] if side == "buy" else price + plan["sl_dist"]
            tp = price + plan["tp_dist"] if side == "buy" else price - plan["tp_dist"]
            filled, note = broker.open(side, lots, price, sl, tp, prob=round(float(prob), 3),
                                       risk_money=plan["sl_money"], open_bar=bar_epoch + 60, stake=plan["stake"],
                                       setup=primary_setup(probs["setups"], side))
            note += (f" | stake {plan['stake']} ({'min lot' if plan['forced_min'] else str(m.stake_pct_of_balance) + '% of balance'})"
                     f" SL -{plan['sl_money']} TP +{plan['tp_money']} ({plan['tp_pct']}%) open {broker.open_count()}/{max_open}")
            journal.log(event="order" if filled else "reject", bar_time=bar_time, symbol=cfg.symbol, side=side,
                        lots=lots, price=price, sl=sl, tp=tp, prob=round(prob, 3), equity=equity, note=note)
            print(f"{bar_time} {side} {lots} @ {price} sl {sl:.5g} tp {tp:.5g} p={prob:.2f} -> {note}")
            say(bar_time, f"OPENED {side.upper()}" if filled else f"order rejected ({side})", "" if filled else note)
            if filled:
                gate.record_trade()
    except KeyboardInterrupt:
        print("interrupted (positions left as they are; server SL/TP stay active in live mode)")
    finally:
        journal.log(event="stop", symbol=cfg.symbol, equity=broker.account_equity())
        data.shutdown()


if __name__ == "__main__":
    main()
