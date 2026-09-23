"""Replay: run the bot on downloaded M1 history, as fast as you like.

    python -m agent.replay data/XAUUSD_M1.parquet --symbol XAUUSD --days 30

Every candle is scored by the trained model up front (one batch, fast), then the bot steps through the candles with
the same rules as live: practice mode (top-10% setups) or the fixed threshold, learned rules, risk gates, stake-based
exits, early exits, max open trades. Trades go into the ledger as mode "replay" (they feed learning and stats, not the
Paper -> Demo gate). Speed and pause are read live from data/replay_control.json (the app's slider writes it); progress
and the recent candles go to data/replay_state.json for the Market tab chart.

By default it replays the model's out-of-sample test period (candles the model never trained on), so results aren't
flattered by memorised data.
"""
import argparse
import json
import time
from collections import namedtuple
from datetime import datetime, timezone
from pathlib import Path

from . import hardware
from .config import AgentConfig

PLAN = hardware.apply()

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from . import learn, ledger, score as scoring  # noqa: E402
from .broker import PaperBroker  # noqa: E402
from .features import atr, build_features  # noqa: E402
from .model import SignalModel  # noqa: E402
from .practice import Practice  # noqa: E402
from .risk import RiskGate, SymbolSpec, stake_plan  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONTROL = ROOT / "data" / "replay_control.json"
STATE = ROOT / "data" / "replay_state.json"
Tick = namedtuple("Tick", "bid ask")


def read_control() -> dict:
    try:
        return json.loads(CONTROL.read_text())
    except (OSError, ValueError):
        return {"speed": 20, "paused": False, "stop": False}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bars")
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--point", type=float, default=0.01)
    ap.add_argument("--days", type=float, default=30, help="how many days of history to replay (from the start point)")
    ap.add_argument("--from", dest="start", default="test", help="'test' (model's unseen period), 'end' (last N days) or a date")
    ap.add_argument("--threshold", type=float, default=0.15)
    ap.add_argument("--practice", action="store_true")
    ap.add_argument("--balance", type=float, default=10_000)
    ap.add_argument("--stake-pct", type=float, default=None)
    ap.add_argument("--sl-pct", type=float, default=None)
    ap.add_argument("--tp-small", type=float, default=None)
    ap.add_argument("--tp-large", type=float, default=None)
    ap.add_argument("--max-open", type=int, default=None)
    ap.add_argument("--ref-leverage", type=float, default=None)
    ap.add_argument("--margin-rate", type=float, default=0.05, help="real margin rate (0.05 = 1:20) for lot sizing")
    ap.add_argument("--tick-size", type=float, default=0.01)
    ap.add_argument("--tick-value", type=float, default=1.0)
    ap.add_argument("--volume-min", type=float, default=0.01)
    ap.add_argument("--volume-step", type=float, default=0.01)
    ap.add_argument("--no-early-exit", action="store_true")
    ap.add_argument("--no-learned", action="store_true")
    ap.add_argument("--sl-score-mult", type=float, default=None)
    ap.add_argument("--fresh", action="store_true", help="clear previous replay trades first")
    args = ap.parse_args()

    cfg = AgentConfig(symbol=args.symbol, threshold=args.threshold)
    m = cfg.money
    for arg, attr in (("stake_pct", "stake_pct_of_balance"), ("sl_pct", "sl_pct_of_stake"), ("tp_small", "tp_pct_small_stake"),
                      ("tp_large", "tp_pct_large_stake"), ("max_open", "max_open_trades"), ("ref_leverage", "ref_leverage")):
        if getattr(args, arg) is not None:
            setattr(m, attr, getattr(args, arg))
    if args.sl_score_mult is not None:
        scoring.SL_MULT = args.sl_score_mult
    spec = SymbolSpec(point=args.point, tick_size=args.tick_size, tick_value=args.tick_value,
                      volume_min=args.volume_min, volume_step=args.volume_step, volume_max=100)

    from .history import load_bars
    df = load_bars(args.symbol, args.bars)
    model = SignalModel.load(cfg.model_dir, cfg.symbol, cfg.hardware)

    # choose the window
    if args.start == "test" and model.meta.get("test_start"):
        start = pd.Timestamp(model.meta["test_start"])
        start = start.tz_localize("UTC") if start.tzinfo is None else start
        where = "the model's unseen test period"
    elif args.start == "end":
        start = df.index[-1] - pd.Timedelta(days=args.days)
        where = f"the last {args.days:g} days"
    else:
        start = pd.Timestamp(args.start, tz="UTC") if args.start not in ("test", "end") else df.index[0]
        where = f"from {start.date()}"
    start = pd.Timestamp(start).as_unit("ns").floor("min")
    end = start + pd.Timedelta(days=args.days)
    i0 = max(int(df.index.searchsorted(start)), 3000)          # features need 3000 bars of warm-up
    i1 = min(int(df.index.searchsorted(end)), len(df))
    if i1 - i0 < 10:
        raise SystemExit("Not enough candles in that window. Fetch more history or pick another start.")

    print(f"replay {cfg.symbol} M1: {df.index[i0]} -> {df.index[i1 - 1]} ({i1 - i0:,} candles, {where})")
    print("scoring every candle with the model...", flush=True)
    feats = build_features(df.iloc[: i1], args.point)
    proba = np.full((i1, 3), np.nan)
    ok = feats.iloc[i0:i1].notna().all(axis=1).to_numpy()
    if ok.any():
        proba[i0:i1][ok] = model.predict_proba(feats.iloc[i0:i1][ok])
    atr_s = atr(df.iloc[: i1], cfg.labels.atr_period).to_numpy()
    spread_med = (df["spread"].astype(float).rolling(1440, min_periods=1).median() * args.point).to_numpy()
    print(f"done. practice mode {'on' if args.practice else 'off'} | threshold {cfg.threshold} | max {m.max_open_trades} open "
          f"| exits at 1:{m.ref_leverage or 'real'}", flush=True)

    if args.fresh:
        with ledger._conn() as c:
            c.execute("DELETE FROM trades WHERE mode='replay'")
    cur = {"px": float(df["close"].iloc[i0]), "spread": float(df["spread"].iloc[i0]) * args.point}
    broker = PaperBroker(args.balance, spec, cfg.symbol, lambda: Tick(cur["px"], cur["px"] + cur["spread"]), mode="replay")
    gate = RiskGate(cfg.risk)
    practice = Practice() if args.practice else None
    O, H, L, C = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    SP = df["spread"].to_numpy(dtype=float) * args.point
    T = ((df.index - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1)).to_numpy().astype(int)   # any resolution
    start_wall = time.time()
    last_state = 0.0
    last_decision = ""
    stats = {"opened": 0}
    need = {"v": None}

    def write_state(i, decision, reason, done=False):
        lo = max(0, i - 299)
        bars = [{"time": int(T[k]), "open": float(O[k]), "high": float(H[k]), "low": float(L[k]), "close": float(C[k])}
                for k in range(lo, i + 1)]
        p = proba[i]
        STATE.write_text(json.dumps({
            "running": not done, "done": done, "symbol": cfg.symbol, "index": i - i0 + 1, "total": i1 - i0,
            "bar_time_utc": str(df.index[i]), "bars": bars, "speed": read_control().get("speed", 20),
            "p_buy": None if np.isnan(p[2]) else float(p[2]), "p_sell": None if np.isnan(p[0]) else float(p[0]),
            "threshold": cfg.threshold, "need": need["v"] if practice and need["v"] else cfg.threshold,
            "practice": bool(practice), "decision": decision, "reason": reason,
            "open": broker.open_count(), "max_open": m.max_open_trades, "balance": round(broker.account_balance(), 2),
            "stats": ledger.stats("replay"), "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")}))

    i = i0
    try:
        while i < i1:
            ctl = read_control()
            if ctl.get("stop"):
                print("stopped from the app")
                break
            if ctl.get("paused"):
                if time.time() - last_state > 0.5:
                    write_state(i - 1 if i > i0 else i0, "paused", "")
                    last_state = time.time()
                time.sleep(0.2)
                continue
            speed = max(1.0, float(ctl.get("speed", 20)))

            cur.update(px=float(C[i]), spread=float(SP[i]))
            bar = {"open": O[i], "high": H[i], "low": L[i], "close": C[i]}
            for x in broker.on_bar(bar, SP[i], int(T[i])):
                print(f"{df.index[i]:%Y-%m-%d %H:%M} EXIT #{x['id']} {x['reason']} pnl {x['pnl']:+.2f}")

            decision, reason = "waiting for a strong setup", ""
            p = proba[i]
            if not np.isnan(p).any():
                p_short, p_long = float(p[0]), float(p[2])
                if not args.no_early_exit:
                    for t in broker.open_list():
                        own, opp = (p_long, p_short) if t["side"] == "buy" else (p_short, p_long)
                        if opp >= cfg.threshold and opp >= m.early_exit_ratio * own:
                            broker.close_one(t, "early")
                side = prob = None
                if practice is not None:
                    side, prob, cut = practice.decide(p_long, p_short)
                    need["v"] = cut
                elif p_long >= cfg.threshold and p_long > p_short:
                    side, prob = "buy", p_long
                elif p_short >= cfg.threshold and p_short > p_long:
                    side, prob = "sell", p_short
                if side and broker.open_count() >= m.max_open_trades:
                    decision, reason = "holding", f"{m.max_open_trades} trades open"
                elif side:
                    why = None if args.no_learned else learn.block_reason(learn.load_rules(), side, prob, df.index[i].hour)
                    okg, rsn = gate.check(df.index[i].tz_convert(None).to_pydatetime(), broker.account_equity(), SP[i],
                                          spread_med[i], atr_s[i], bot_pnl_today=broker.bot_pnl_today())
                    price = C[i] + SP[i] if side == "buy" else C[i]
                    plan = stake_plan(broker.account_balance(), price * (spec.tick_value / spec.tick_size) * args.margin_rate,
                                      spec, m, price)
                    if why:
                        decision, reason = f"skipped {side}", why
                    elif not okg:
                        decision, reason = f"skipped {side}", rsn
                    elif SP[i] > plan["sl_dist"] * m.max_spread_to_stop:
                        decision, reason = f"skipped {side}", "spread too wide for the stop"
                    else:
                        sl = price - plan["sl_dist"] if side == "buy" else price + plan["sl_dist"]
                        tp = price + plan["tp_dist"] if side == "buy" else price - plan["tp_dist"]
                        broker.open(side, plan["lots"], price, sl, tp, prob=round(prob, 3), risk_money=plan["sl_money"],
                                    open_bar=int(T[i]) + 60, stake=plan["stake"])
                        gate.record_trade()
                        stats["opened"] += 1
                        decision = f"OPENED {side.upper()}"
                        print(f"{df.index[i]:%Y-%m-%d %H:%M} {side.upper()} {plan['lots']} @ {price:.2f} "
                              f"sl {sl:.2f} tp {tp:.2f} p={prob:.2f}", flush=True)
            else:
                decision = "warming up"

            if time.time() - last_state > 0.2 or decision.startswith("OPENED") and decision != last_decision:
                write_state(i, decision, reason)
                last_state = time.time()
            last_decision = decision
            i += 1
            time.sleep(1.0 / speed)
    finally:
        # trades still open when the history runs out never finished: drop them so they don't skew stats or lessons
        with ledger._conn() as c:
            dropped = c.execute("DELETE FROM trades WHERE mode='replay' AND status='open'").rowcount
        broker.positions = []
        if dropped:
            print(f"{dropped} trade(s) were still open when the history ended; not counted.")
        write_state(min(i, i1 - 1), "finished", "", done=True)
        st = ledger.stats("replay")
        print(f"\nreplay finished: {stats['opened']} trades opened this run | all replay trades: {st['closed']} closed, "
              f"win {st['win_pct']}%, net {st['net_pnl']:+.2f}, score {st['score']:+.1f} pts, PF {st['profit_factor']} "
              f"| took {time.time() - start_wall:.0f}s", flush=True)


if __name__ == "__main__":
    main()
