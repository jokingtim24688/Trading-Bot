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
from collections import Counter, namedtuple
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
from .pro import SETUP_NAMES, active_setups, primary_setup  # noqa: E402
from .risk import RiskGate, SymbolSpec, stake_plan  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONTROL = ROOT / "data" / "replay_control.json"
STATE = ROOT / "data" / "replay_state.json"
Tick = namedtuple("Tick", "bid ask")
SERVER_UTC_OFFSET_H = 2     # candle times are broker server time (UTC+2 winter / +3 summer); ledger times are UTC


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
    ap.add_argument("--days", type=float, default=30, help="days of history to replay from the start point (0 = all of it)")
    ap.add_argument("--from", dest="start", default="test",
                    help="'test' (model's unseen period), 'end' (last N days), 'all' (from the first candle) or a date")
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
    ap.add_argument("--hours", default=None, help="server-time hours new entries are allowed, e.g. 9-22 (default all day)")
    ap.add_argument("--quiz-filter", action="store_true", help="only enter when the quiz agent picks the same side")
    ap.add_argument("--sl-score-mult", type=float, default=None)
    ap.add_argument("--fresh", action="store_true", help="clear previous replay trades first")
    ap.add_argument("--strict-filters", action="store_true",
                    help="also apply the live spread-vs-ATR filter (off by default: history spreads are estimates, and on "
                         "cheaper/quieter years it blocks nearly every candle; the spread-vs-stop cost check always applies)")
    ap.add_argument("--commission", type=float, default=0.0, help="round-turn commission per 1.0 lot (account money)")
    ap.add_argument("--slippage", type=float, default=0.0, help="points of slippage on every market fill (entry, stop, early exit)")
    ap.add_argument("--db", default=None, help="ledger file to use instead of data/trades.db (the backtest keeps its own)")
    ap.add_argument("--state", default=None, help="progress file instead of data/replay_state.json")
    ap.add_argument("--control", default=None, help="control file instead of data/replay_control.json")
    ap.add_argument("--report", default=None, help="write the backtest report (JSON; a .md next to it) when done")
    args = ap.parse_args()
    global STATE, CONTROL
    if args.db:
        ledger.DB = Path(args.db)
    if args.state:
        STATE = Path(args.state)
    if args.control:
        CONTROL = Path(args.control)

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
    elif args.start == "end" and args.days > 0:
        start = df.index[-1] - pd.Timedelta(days=args.days)
        where = f"the last {args.days:g} days"
    elif args.start in ("all", "end", "test"):
        start = df.index[0]
        where = "all downloaded history (includes candles the model trained on, so results look better than live)"
    else:
        start = pd.Timestamp(args.start, tz="UTC")
        where = f"from {start.date()}"
    start = pd.Timestamp(start).as_unit("ns").floor("min")
    end = start + pd.Timedelta(days=args.days) if args.days > 0 else df.index[-1] + pd.Timedelta(minutes=1)
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
    cur = {"px": float(df["close"].iloc[i0]), "spread": float(df["spread"].iloc[i0]) * args.point, "i": i0}
    broker = PaperBroker(args.balance, spec, cfg.symbol, lambda: Tick(cur["px"], cur["px"] + cur["spread"]), mode="replay")
    broker.commission_per_lot, broker.slippage_px = args.commission, args.slippage * args.point
    offset = pd.Timedelta(hours=SERVER_UTC_OFFSET_H)
    utc_iso = lambda k: (df.index[k] - offset).strftime("%Y-%m-%dT%H:%M:%S+00:00")    # noqa: E731
    broker.clock = lambda: utc_iso(cur["i"])  # trades get the replayed candle's date/hour, not today's
    if not args.strict_filters:
        cfg.risk.max_spread_to_atr = float("inf")
    if args.hours:
        cfg.risk.session_start_hour, cfg.risk.session_end_hour = (int(x) for x in args.hours.split("-"))
    gate = RiskGate(cfg.risk)
    skips = Counter()                                  # why candles with a signal didn't become trades
    practice = Practice() if args.practice else None
    O, H, L, C = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    SP = df["spread"].to_numpy(dtype=float) * args.point
    T = ((df.index - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1)).to_numpy().astype(int)   # any resolution
    start_wall = time.time()
    pace = {"t": time.time(), "i": 0, "rate": 0.0, "due": time.time()}
    last_state = 0.0
    last_decision = ""
    stats = {"opened": 0}
    need = {"v": None}

    def write_state(i, decision, reason, done=False):
        lo = max(0, i - 1499)                   # enough that the chart never misses candles between polls at 2000/s
        bars = [{"time": int(T[k]), "open": float(O[k]), "high": float(H[k]), "low": float(L[k]), "close": float(C[k])}
                for k in range(lo, i + 1)]
        p = proba[i]
        STATE.write_text(json.dumps({
            "running": not done, "done": done, "symbol": cfg.symbol, "index": i - i0 + 1, "total": i1 - i0,
            "bar_time_utc": str(df.index[i]), "bars": bars, "speed": read_control().get("speed", 20),
            "p_buy": None if np.isnan(p[2]) else float(p[2]), "p_sell": None if np.isnan(p[0]) else float(p[0]),
            "threshold": cfg.threshold, "need": need["v"] if practice and need["v"] else cfg.threshold,
            "practice": bool(practice),
            "setups": [SETUP_NAMES[k] for k in active_setups(feats.iloc[i].to_dict())] if i < len(feats) else [], "decision": decision, "reason": reason,
            "open": broker.open_count(), "max_open": m.max_open_trades, "balance": round(broker.account_balance(), 2),
            "rate": round(pace["rate"]), "skips": [[k, n] for k, n in skips.most_common(4)], "opened": stats["opened"], "stats": ledger.stats("replay"), "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")}))

    from .quiz import load_policy
    quiz_pol = load_policy()               # recorded on every trade (the app compares agree vs disagree); filters only if asked
    OHLC = np.column_stack([O, H, L, C]) if quiz_pol is not None else None   # the quiz agent looks at the chart
    rules = learn.load_rules()                         # fixed for the run: reading files per candle limits max speed
    ctl, ctl_read = read_control(), time.time()
    i = i0
    try:
        while i < i1:
            if time.time() - ctl_read > 0.2:
                ctl, ctl_read = read_control(), time.time()
            if ctl.get("stop"):
                print("stopped from the app")
                break
            if ctl.get("paused"):
                if time.time() - last_state > 0.5:
                    write_state(i - 1 if i > i0 else i0, "paused", "")
                    last_state = time.time()
                time.sleep(0.2)
                ctl, ctl_read = read_control(), time.time()
                continue
            speed = float(ctl.get("speed", 20))        # 0 = max: no waiting between candles

            cur.update(px=float(C[i]), spread=float(SP[i]), i=i)
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
                    skips["max open trades"] += 1
                elif side:
                    setup = primary_setup(active_setups(feats.iloc[i].to_dict()), side)
                    why = None if args.no_learned else learn.block_reason(rules, side, prob, (df.index[i] - offset).hour, setup, cautions=False)
                    okg, rsn = gate.check(df.index[i].tz_convert(None).to_pydatetime(), broker.account_equity(), SP[i],
                                          spread_med[i], atr_s[i], bot_pnl_today=broker.bot_pnl_today())
                    price = C[i] + SP[i] if side == "buy" else C[i]
                    plan = stake_plan(broker.account_balance(), price * (spec.tick_value / spec.tick_size) * args.margin_rate,
                                      spec, m, price)
                    qa = None
                    if quiz_pol is not None and (args.quiz_filter or not (why or not okg)):
                        try:
                            qa = quiz_pol.answer_row(feats.iloc[i].to_dict(), OHLC[max(0, i - 89):i + 1])
                        except Exception:          # noqa: BLE001 - quiz agent made for other inputs: no opinion
                            qa = None
                    if args.quiz_filter and qa and qa["action"] != side:
                        decision, reason = f"skipped {side}", f"quiz agent says {qa['action']}"
                        skips["quiz agent disagreed"] += 1
                    elif why:
                        decision, reason = f"skipped {side}", why
                        skips["learned rule"] += 1
                    elif not okg:
                        decision, reason = f"skipped {side}", rsn
                        skips[rsn] += 1
                    elif SP[i] > plan["sl_dist"] * m.max_spread_to_stop:
                        decision, reason = f"skipped {side}", "spread too wide for the stop"
                        skips["spread too wide for the stop"] += 1
                    else:
                        sl = price - plan["sl_dist"] if side == "buy" else price + plan["sl_dist"]
                        tp = price + plan["tp_dist"] if side == "buy" else price - plan["tp_dist"]
                        broker.open(side, plan["lots"], price, sl, tp, prob=round(prob, 3), risk_money=plan["sl_money"],
                                    open_bar=int(T[i]) + 60, stake=plan["stake"],
                                    setup=setup, quiz=qa["action"] if qa else None)
                        gate.record_trade()
                        stats["opened"] += 1
                        decision = f"OPENED {side.upper()}"
                        print(f"{df.index[i]:%Y-%m-%d %H:%M} {side.upper()} {plan['lots']} @ {price:.2f} "
                              f"sl {sl:.2f} tp {tp:.2f} p={prob:.2f}", flush=True)
            else:
                decision = "warming up"

            now = time.time()
            if now - last_state > 0.2 or decision.startswith("OPENED") and decision != last_decision and speed and speed < 50:
                if now - pace["t"] >= 1:
                    pace.update(rate=(i - pace["i"]) / (now - pace["t"]), t=now, i=i)
                write_state(i, decision, reason)
                last_state = now
            last_decision = decision
            i += 1
            if speed > 0:                              # pace without sleeping every candle (Windows sleeps are coarse)
                pace["due"] = max(pace["due"], now - 0.5) + 1.0 / speed
                if pace["due"] - now > 0.005:
                    time.sleep(pace["due"] - now)
    finally:
        # trades still open when the history runs out never finished: drop them so they don't skew stats or lessons
        with ledger._conn() as c:
            dropped = c.execute("DELETE FROM trades WHERE mode='replay' AND status='open'").rowcount
        broker.positions = []
        if dropped:
            print(f"{dropped} trade(s) were still open when the history ended; not counted.")
        write_state(min(i, i1 - 1), "finished", "", done=True)
        st = ledger.stats("replay")
        if skips:
            print("signals skipped: " + ", ".join(f"{k} {n:,}" for k, n in skips.most_common()))
        print(f"\nreplay finished: {stats['opened']} trades opened this run | all replay trades: {st['closed']} closed, "
              f"win {st['win_pct']}%, net {st['net_pnl']:+.2f}, score {st['score']:+.1f} pts, PF {st['profit_factor']} "
              f"| took {time.time() - start_wall:.0f}s", flush=True)
        if args.report:
            from .backtest import write_report
            write_report(Path(args.report), args, df.index[i0], df.index[min(i, i1 - 1)], skips)


if __name__ == "__main__":
    main()
