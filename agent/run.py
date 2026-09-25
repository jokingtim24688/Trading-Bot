"""Live M1 loop.

    python -m agent.run --symbol XAUUSD --threshold 0.55            # paper (default, no orders)
    python -m agent.run --symbol XAUUSD --threshold 0.55 --live     # real orders, DEMO account only
    python -m agent.run ... --live --allow-real                     # real-money account (be sure)

Create a file named STOP in the working directory to flatten and exit.
"""
import argparse
import json
from collections import Counter, deque
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
import numpy as np  # noqa: E402  (after hardware.apply sets the thread counts)
from .pro import SETUP_NAMES, active_setups, primary_setup  # noqa: E402
from .risk import RiskGate, stake_plan  # noqa: E402
from . import livecard, news  # noqa: E402


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
    ap.add_argument("--news-before", type=float, default=0, help="no new trades this many minutes before big news (0 = off)")
    ap.add_argument("--news-after", type=float, default=0, help="...and this many minutes after it")
    ap.add_argument("--news-currencies", default="USD", help="comma list of currencies whose news pauses the bot")
    ap.add_argument("--news-impact", default="High", help="comma list of impact levels that pause it (High,Medium,Low)")
    ap.add_argument("--quiz-filter", action="store_true", help="only enter when the quiz agent picks the same side")
    ap.add_argument("--practice", action="store_true", help="paper only: also show where the model's top 10%% of readings start")
    ap.add_argument("--hours", default=None, help="server-time hours new entries are allowed, e.g. 9-22 (default all day)")
    ap.add_argument("--settings", default=None, help="the app's settings.json: its threshold is re-read every candle")
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
    if args.hours:
        h0, h1 = (int(x) for x in args.hours.split("-"))
        cfg.risk.session_start_hour, cfg.risk.session_end_hour = h0, h1
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
    spec_digits = max(0, int(round(-np.log10(spec.point)))) if spec.point else 5
    probs = {"buy": None, "sell": None, "need": None, "setups": []}
    from .quiz import load_policy
    quiz_pol = load_policy()               # its answer is recorded on every trade, so the app can measure if it helps
    if args.quiz_filter:
        print("quiz agent second opinion: " + ("on" if quiz_pol else "off (no trained quiz agent yet)"))
    practice = Practice() if args.practice and mode == "paper" else None
    ranker = practice or Practice()            # the model's last day of readings: confidence rank + practice top 10%
    try:                                       # score the last day of closed candles now: no warm-up at all
        from .practice import WINDOW
        hist = data.m1_bars(cfg.history_bars + WINDOW)
        f = build_features(hist, spec.point).iloc[:-1].tail(WINDOW).dropna()
        if len(f):
            pr = model.predict_proba(f)
            n = ranker.seed(np.maximum(pr[:, 0], pr[:, 2]))
            print(f"scored the last {n} closed candles: ready to trade on this candle", flush=True)
    except Exception as e:                     # noqa: BLE001 - the rank fills in live instead
        print(f"couldn't score recent candles ({e}); the confidence rank fills in live", flush=True)

    data_dir = status_path.parent
    proposal_path, decision_path = data_dir / "copilot.json", data_dir / "copilot_decision.json"
    live = {"bot_mode": "auto", "copilot_seconds": 30, "copilot_auto_execute": False}
    card = {"row": None, "lean": None, "conf": None, "proposal": None, "ready": (False, "no setup yet")}

    def read_live_settings():
        """The app's settings, re-read every candle: confidence slider, Full Auto / Co-pilot and its timer."""
        if not args.settings:
            return
        try:
            st = json.loads(Path(args.settings).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        thr = st.get("threshold")
        if isinstance(thr, (int, float)) and 0 < thr < 1 and thr != cfg.threshold:
            print(f"confidence threshold changed in the app: {cfg.threshold:.2f} -> {thr:.2f}", flush=True)
            cfg.threshold = float(thr)
        m_ = st.get("bot_mode", "auto")
        if m_ in ("auto", "copilot") and m_ != live["bot_mode"]:
            print(f"bot mode: {'Co-pilot (asks you before each trade)' if m_ == 'copilot' else 'Full Auto'}", flush=True)
            live["bot_mode"] = m_
        live["copilot_seconds"] = max(5, min(600, int(st.get("copilot_seconds", 30) or 30)))
        live["copilot_auto_execute"] = bool(st.get("copilot_auto_execute", False))

    recent = deque(maxlen=60)                  # the last hour's decisions, so the card can say what's blocking it

    def say(bar_time, decision, reason=""):
        """One line per closed candle in the live log + data/agent_status.json for the Market tab."""
        recent.append("opened" if decision.startswith("OPENED") else
                      (reason.split(":")[0].split(" (")[0] or decision) if decision.startswith("skipped") else decision)
        hhmm = str(bar_time)[11:16]
        pb, ps = probs["buy"], probs["sell"]
        need = cfg.threshold                   # the slider's value: the only bar entries have to clear
        conf = f"buy {pb:.1%} / sell {ps:.1%} (needs {need:.1%})" if pb is not None else "model warming up"
        print(f"{hhmm} {conf} -> {decision}{': ' + reason if reason else ''}", flush=True)
        try:
            status_path.parent.mkdir(exist_ok=True)
            row, lean = card["row"], card["lean"]
            if decision.startswith("skipped"):
                card["ready"] = (False, reason.split(" (")[0][:70])
            opn = broker.open_list()
            pr_ = card["proposal"]
            pr_ = pr_ and {k: v for k, v in pr_.items() if k not in ("_ctx", "sl")}   # SL stays in the order only
            try:
                pills = livecard.confluence(row, lean, *card["ready"]) if row and lean else []
                head = livecard.headline(cfg.symbol, row, lean, decision, reason, len(opn),
                                         opn[-1]["side"] if opn else None, need, bool(pr_))
            except Exception:                  # noqa: BLE001 - the card is a nicety; never stop trading over it
                pills, head = [], f"{decision}: {reason}" if reason else decision
            extra = {"bot_mode": live["bot_mode"], "confidence_pct": card["conf"],
                     "lean": lean, "proposal": pr_, "confluence": pills, "headline": head}
            status_path.write_text(json.dumps({**extra,
                "time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "bar": hhmm, "mode": mode,
                "symbol": cfg.symbol, "p_buy": pb, "p_sell": ps, "threshold": cfg.threshold, "need": need,
                "practice": practice is not None, "top10": probs["need"], "setups": [SETUP_NAMES[k] for k in probs["setups"]],
                "decision": decision,
                "reason": reason, "last_hour": dict(Counter(recent).most_common()),
                "hours": [cfg.risk.session_start_hour, cfg.risk.session_end_hour], "open": broker.open_count(), "max_open": max_open}))
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
    def plan_for(side):
        """Price, lots, SL and TP for an entry at the current price, or (None, why) when it can't be placed."""
        t = data.tick()
        price = t.ask if side == "buy" else t.bid
        plan = stake_plan(broker.account_balance(), data.margin_per_lot(side, price), spec, m, price)
        if plan is None:
            return None, "no margin data from MT5"
        min_stop = spec.stops_level_points * spec.point
        if plan["sl_dist"] <= min_stop:
            return None, f"stop {plan['sl_dist']:.5g} is inside the broker's minimum distance {min_stop:.5g}"
        spread_now = abs(t.ask - t.bid)
        if spread_now > plan["sl_dist"] * m.max_spread_to_stop:
            return None, f"spread {spread_now:.2f} is too wide for the stop"
        sgn = 1 if side == "buy" else -1
        return {**plan, "price": price, "sl": price - sgn * plan["sl_dist"], "tp": price + sgn * plan["tp_dist"]}, ""

    def enter(bar_time, bar_epoch, side, prob, qa, setup, how=""):
        pl, why = plan_for(side)
        if pl is None:
            journal.log(event="skip", bar_time=bar_time, symbol=cfg.symbol, side=side, prob=round(prob, 3), note=why)
            say(bar_time, f"skipped {side}", why)
            return False
        price, lots, sl, tp = pl["price"], pl["lots"], pl["sl"], pl["tp"]
        filled, note = broker.open(side, lots, price, sl, tp, prob=round(float(prob), 3),
                                   risk_money=pl["sl_money"], open_bar=bar_epoch + 60, stake=pl["stake"],
                                   setup=setup, quiz=qa["action"] if qa else None)
        note += (f" | stake {pl['stake']} ({'min lot' if pl['forced_min'] else str(m.stake_pct_of_balance) + '% of balance'})"
                 f" SL -{pl['sl_money']} TP +{pl['tp_money']} ({pl['tp_pct']}%) open {broker.open_count()}/{max_open}{how}")
        journal.log(event="order" if filled else "reject", bar_time=bar_time, symbol=cfg.symbol, side=side,
                    lots=lots, price=price, sl=sl, tp=tp, prob=round(prob, 3), equity=broker.account_equity(), note=note)
        print(f"{bar_time} {side} {lots} @ {price} sl {sl:.5g} tp {tp:.5g} p={prob:.2f} -> {note}")
        say(bar_time, f"OPENED {side.upper()}" if filled else f"order rejected ({side})", "" if filled else note)
        if filled:
            gate.record_trade()
        return filled

    def write_proposal():
        try:
            proposal_path.write_text(json.dumps(card["proposal"]), encoding="utf-8")
        except OSError:
            pass

    def propose(bar_time, bar_epoch, side, prob, qa, setup):
        """Co-pilot: show the trade on the Bot tab and wait for Approve / Skip (or the timer) before sending it."""
        pl, why = plan_for(side)
        if pl is None:
            say(bar_time, f"skipped {side}", why)
            return
        now = time.time()
        rsn = livecard.reason(side, [SETUP_NAMES[k] for k in probs["setups"]], card["row"], float(prob),
                              cfg.threshold, card["conf"])
        card["proposal"] = {"id": f"{int(now * 1000)}", "status": "pending", "symbol": cfg.symbol, "side": side,
                            "entry": round(pl["price"], spec_digits), "tp": round(pl["tp"], spec_digits),
                            "sl": round(pl["sl"], spec_digits), "lots": pl["lots"], "prob": round(float(prob), 4),
                            "confidence_pct": card["conf"], "reason": rsn, "created": now,
                            "expires": now + live["copilot_seconds"], "seconds": live["copilot_seconds"],
                            "auto_execute": live["copilot_auto_execute"], "mode": mode,
                            "_ctx": {"bar_epoch": bar_epoch, "qa": qa, "setup": setup}}
        write_proposal()
        journal.log(event="proposal", bar_time=bar_time, symbol=cfg.symbol, side=side, prob=round(prob, 3), note=rsn)
        print(f"{str(bar_time)[11:16]} CO-PILOT proposes {side.upper()} {cfg.symbol} @ {pl['price']:.5g} "
              f"TP {pl['tp']:.5g}: {rsn}", flush=True)
        say(bar_time, "proposing " + side, "waiting for your approval")

    def finish_proposal(status, bar_time, filled=None):
        p = card["proposal"]
        p.update(status=status, decided=time.time())
        if filled is not None:
            p["filled"] = filled
        card["proposal"] = None
        try:
            proposal_path.write_text(json.dumps({k: v for k, v in p.items() if k != "_ctx"}), encoding="utf-8")
        except OSError:
            pass
        print(f"co-pilot: proposal {p['id']} {status}", flush=True)
        if status in ("executed", "failed"):
            return                             # enter() already reported the order on the card
        say(bar_time, {"skipped": "skipped by you", "expired": "proposal expired"}.get(status, status),
            "" if filled is not False else "the order didn't go through")

    def check_proposal(bar_time):
        p = card["proposal"]
        act = None
        try:
            d = json.loads(decision_path.read_text(encoding="utf-8"))
            decision_path.unlink(missing_ok=True)
            if d.get("id") == p["id"]:
                act = d.get("action")
        except (OSError, ValueError):
            pass
        if act is None and time.time() >= p["expires"]:
            act = "approve" if p["auto_execute"] else "expire"
            how = " (co-pilot timer ran out: auto-executed)"
        else:
            how = " (approved by you in co-pilot)"
        if act == "approve":
            c = p["_ctx"]
            filled = enter(bar_time, c["bar_epoch"], p["side"], p["prob"], c["qa"], c["setup"], how)
            finish_proposal("executed" if filled else "failed", bar_time, filled)
        elif act == "skip":
            finish_proposal("skipped", bar_time)
        elif act == "expire":
            finish_proposal("expired", bar_time)

    journal.log(event="start", symbol=cfg.symbol, note=f"mode={mode} thr={cfg.threshold}")
    read_live_settings()
    proposal_path.unlink(missing_ok=True)           # a proposal from an earlier run is stale
    decision_path.unlink(missing_ok=True)
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
                if card["proposal"]:
                    check_proposal(bar_time)                # co-pilot: your answer, or the timer running out
                time.sleep(1.0)
                continue
            last_bar = bar_time
            read_live_settings()                           # slider / mode changed while running: from this candle
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
            rowd = row.iloc[0].to_dict()
            probs["setups"] = active_setups(rowd)
            probs.update(buy=float(p_long), sell=float(p_short))
            card.update(row=rowd, lean="buy" if p_long >= p_short else "sell",
                        conf=livecard.confidence_pct(ranker.seen, max(p_long, p_short)),
                        ready=(False, "below the confidence needed"))
            cut = ranker.decide(p_long, p_short)[2]          # adds this reading to the last day's readings
            if practice is not None:                       # info only: where its best ~10% of readings start
                probs["need"] = cut

            # early exit: close a trade before its stop when the model has clearly turned against it
            if m.early_exit:
                for t in broker.open_list():
                    own, opp = (p_long, p_short) if t["side"] == "buy" else (p_short, p_long)
                    if opp >= cfg.threshold and opp >= m.early_exit_ratio * own:
                        x = broker.close_one(t, "early")
                        if x:
                            report_exits([x], bar_time)

            if card["proposal"]:
                card["ready"] = (True, "waiting for your approval")
                say(bar_time, "waiting for you", "co-pilot proposal waiting for your answer")
                continue
            if broker.open_count() >= max_open:
                card["ready"] = (False, f"all {max_open} trade slots in use")
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
            if side is None:
                say(bar_time, "waiting for a strong setup", "no side reached the needed confidence on this candle")
                continue

            qa = None
            if quiz_pol is not None:
                try:
                    qa = quiz_pol.answer_row(row.iloc[0].to_dict(), bars[["open", "high", "low", "close"]].to_numpy()[-90:])
                except Exception:                  # noqa: BLE001 - a quiz agent made for other inputs: no opinion
                    qa = None
            if args.quiz_filter and qa is not None and qa["action"] != side:
                say(bar_time, f"skipped {side}", f"quiz agent says {qa['action']}")
                continue

            if not args.no_learned:
                why = learn.block_reason(learn.load_rules(), "buy" if side == "buy" else "sell", float(prob),
                                         datetime.now(timezone.utc).hour, setup=primary_setup(probs["setups"], side),
                                         recent_probs=ranker.seen)
                if why:
                    journal.log(event="skip", bar_time=bar_time, symbol=cfg.symbol, side=side, prob=round(prob, 3), note=why)
                    say(bar_time, f"skipped {side}", why)
                    continue

            if args.news_before > 0 or args.news_after > 0:
                why = news.pause_reason(None, args.news_before, args.news_after, tuple(args.news_currencies.split(",")),
                                        tuple(args.news_impact.split(",")))
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

            setup = primary_setup(probs["setups"], side)
            card["ready"] = (True, "all checks passed")
            if live["bot_mode"] == "copilot":
                propose(bar_time, bar_epoch, side, prob, qa, setup)
                continue
            enter(bar_time, bar_epoch, side, prob, qa, setup)
    except KeyboardInterrupt:
        print("interrupted (positions left as they are; server SL/TP stay active in live mode)")
    finally:
        journal.log(event="stop", symbol=cfg.symbol, equity=broker.account_equity())
        data.shutdown()


if __name__ == "__main__":
    main()
