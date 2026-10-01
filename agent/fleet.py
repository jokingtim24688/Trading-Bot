"""Fleet launcher: start one ML bot per symbol and watch them all in the terminal.

Each symbol gets its own `agent.run` process, so one crashing or stalling can't take
the others down. The dashboard reads the shared ledger, so what you see is the real
recorded P/L, not the bots' own claims.

    python -m agent.fleet --scan            # what's tradeable right now, and why
    python -m agent.fleet                   # paper-trade every trained symbol
    python -m agent.fleet --symbols XAUUSD,EURUSD
    python -m agent.fleet --live            # send real orders (demo account unless --allow-real)

Which symbols it will trade: only ones with a trained model in models/. A model only
exists after agent.train has validated it, so the fleet can't silently start trading
something that was never tested. --scan shows what's missing.
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"
LOGS = ROOT / "logs" / "fleet"

# Objective tradeability limits. These are about whether an instrument CAN be traded
# sensibly, not a prediction that it will be profitable - nothing here knows that.
MAX_SPREAD_ATR = 0.25      # spread must be under 25% of a typical M1 range
MIN_BARS = 2000            # enough history for features to be meaningful


def _mt5():
    sys.path.insert(0, str(ROOT))
    from app import mt5_service
    return mt5_service


def trained_symbols() -> list[str]:
    if not MODELS.exists():
        return []
    return sorted(p.name[: -len("_M1.json")] for p in MODELS.glob("*_M1.json"))


def scan(symbols: list[str] | None = None) -> list[dict]:
    """Check each symbol against objective tradeability limits."""
    svc = _mt5()
    out = []
    for sym in symbols or trained_symbols():
        row = {"symbol": sym, "ok": False, "why": ""}
        try:
            spec = svc.symbol_spec(sym)
            bars = svc.m1_bars(sym, 300)
            closes = [b["close"] for b in bars.get("bars", [])]
            highs = [b["high"] for b in bars.get("bars", [])]
            lows = [b["low"] for b in bars.get("bars", [])]
            if len(closes) < 50:
                row["why"] = "not enough M1 history yet (run Fetch first)"
                out.append(row)
                continue
            atr = sum(h - l for h, l in zip(highs[-50:], lows[-50:])) / 50
            point = spec.get("point") or 0.01
            spread_pts = (spec.get("ask", 0) - spec.get("bid", 0)) / point
            atr_pts = atr / point
            row.update(spread=round(spread_pts, 1), atr=round(atr_pts, 1),
                       ratio=round(spread_pts / atr_pts, 3) if atr_pts else None,
                       model=(MODELS / f"{sym}_M1.json").exists())
            if not row["model"]:
                row["why"] = "no trained model - run agent.train for it"
            elif atr_pts and spread_pts / atr_pts > MAX_SPREAD_ATR:
                row["why"] = (f"spread {spread_pts:.0f}pts is {spread_pts/atr_pts:.0%} of its "
                              f"{atr_pts:.0f}pt range - costs eat the edge")
            else:
                row["ok"] = True
                row["why"] = "tradeable"
        except Exception as e:  # noqa: BLE001 - MT5 off, symbol missing, etc.
            row["why"] = f"{type(e).__name__}: {str(e)[:60]}"
        out.append(row)
    return out


def launch(sym: str, args) -> subprocess.Popen:
    LOGS.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "agent.run", "--symbol", sym,
           "--threshold", str(args.threshold), "--max-open", str(args.max_open)]
    if args.live:
        cmd.append("--live")
    if args.allow_real:
        cmd.append("--allow-real")
    if args.hours:
        cmd += ["--hours", args.hours]
    log = open(LOGS / f"{sym}.log", "a", encoding="utf-8", buffering=1)
    log.write(f"\n=== fleet start {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    return subprocess.Popen(cmd, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT,
                            env={**os.environ, "PYTHONUNBUFFERED": "1"})


def dashboard(fleet):
    """One screen: every bot, its state, and the ledger's real numbers."""
    sys.path.insert(0, str(ROOT))
    from agent import ledger
    try:
        svc = _mt5()
        acct = svc.account()
        bal, eq = acct.get("balance", 0), acct.get("equity", 0)
    except Exception:  # noqa: BLE001
        bal = eq = 0

    procs, mode = fleet.procs, fleet.mode
    print("\033[2J\033[H", end="")
    up = int(time.time() - fleet.started)
    colour = {"running": "\033[92m", "draining": "\033[93m", "paused": "\033[93m",
              "stopped": "\033[91m"}.get(fleet.state, "")
    state = f"{colour}{fleet.state.upper()}\033[0m  {mode}"
    print(f"  FLEET  |  {state}  |  up {up//3600:02d}:{up%3600//60:02d}:{up%60:02d}"
          f"  |  balance ${bal:,.2f}  equity ${eq:,.2f}")
    print("  " + "-" * 94)
    print(f"  {'symbol':<10} {'bot':<9} {'open':>5} {'trades':>7} {'wins':>6} "
          f"{'win%':>6} {'realised P/L':>14} {'last trade':>18}")
    print("  " + "-" * 94)

    tot_pnl = tot_n = 0
    for sym, p in sorted(procs.items()):
        alive = p.poll() is None
        state = "\033[92mrunning\033[0m" if alive else f"\033[91mdied({p.returncode})\033[0m"
        try:
            st = ledger.stats(symbol=sym) or {}
            rows = ledger.recent(1, symbol=sym) or []
            n = st.get("trades", 0) or 0
            wins = st.get("wins", 0) or 0
            pnl = st.get("net", 0.0) or 0.0
            opn = len(ledger.open_trades(symbol=sym) or [])
            last = (rows[0].get("close_utc") or rows[0].get("open_utc") or "")[:16] if rows else "-"
        except Exception:  # noqa: BLE001
            n = wins = opn = 0
            pnl = 0.0
            last = "-"
        tot_pnl += pnl
        tot_n += n
        wr = f"{100*wins/n:.0f}%" if n else "-"
        col = "\033[92m" if pnl > 0 else "\033[91m" if pnl < 0 else ""
        end = "\033[0m" if col else ""
        print(f"  {sym:<10} {state:<18} {opn:>5} {n:>7} {wins:>6} {wr:>6} "
              f"{col}{pnl:>13,.2f}{end} {last:>18}")

    print("  " + "-" * 94)
    col = "\033[92m" if tot_pnl > 0 else "\033[91m" if tot_pnl < 0 else ""
    print(f"  {'TOTAL':<10} {len(procs)} bots{'':<9} {'':>5} {tot_n:>7} {'':>6} {'':>6} "
          f"{col}{tot_pnl:>13,.2f}\033[0m")
    print(f"\n  logs: logs/fleet/<symbol>.log      Ctrl+C stops every bot")
    print(f"  Telegram:  /stop  /start  /pause  /status  /bots  /total  /prof  /loss")


class Fleet:
    """Holds the running bots and answers the Telegram commands.

    Stopping is a DRAIN, not a cut-off: the bot processes end straight away so no new
    trade can open, but any trade already open is left to reach its own stop or target.
    The fleet stays in `draining` until the last one closes, then reports itself stopped.
    Open trades keep their SL/TP at the broker, so they are safe with no bot running -
    but nothing would record their result, so the fleet keeps syncing the ledger while
    it drains.
    """

    def __init__(self, args, symbols, mode):
        self.args, self.mode = args, mode
        self.procs: dict[str, subprocess.Popen] = {}
        self.symbols = list(symbols)
        self.started = time.time()
        self.state = "stopped"          # running | draining | paused | stopped
        self.drain_goal = None          # "stopped" or "paused" once the drain finishes
        self._lock = threading.Lock()

    # ----- helpers -----
    def alive(self) -> int:
        return sum(1 for p in self.procs.values() if p.poll() is None)

    def open_trades(self) -> list:
        """The fleet's open trades, from the ledger (synced first so it is current)."""
        sys.path.insert(0, str(ROOT))
        try:
            from app import mt5_service
            mt5_service.sync_bot_ledger(force=True)
        except Exception:               # noqa: BLE001 - MT5 off; ledger may lag
            pass
        try:
            from agent import ledger
            return [t for t in (ledger.open_trades() or [])
                    if t.get("symbol") in self.symbols]
        except Exception:               # noqa: BLE001
            return []

    def _kill_bots(self):
        for p in self.procs.values():
            if p.poll() is None:
                p.terminate()
        for p in self.procs.values():
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
        self.procs.clear()

    # ----- lifecycle -----
    def start_all(self) -> int:
        with self._lock:
            self.drain_goal = None
            for sym in self.symbols:
                if sym not in self.procs or self.procs[sym].poll() is not None:
                    self.procs[sym] = launch(sym, self.args)
            self.state = "running"
            return len(self.procs)

    def begin_drain(self, goal: str) -> int:
        """Stop new entries now; wait for open trades to finish. Returns how many are open."""
        with self._lock:
            self._kill_bots()
            opn = len(self.open_trades())
            self.drain_goal = goal
            self.state = "draining" if opn else goal
            return opn

    def tick(self):
        """Called by the dashboard loop: finish the drain once the last trade closes."""
        if self.state != "draining":
            return
        if not self.open_trades():
            self.state = self.drain_goal or "stopped"
            self.drain_goal = None
            print(f"\n  \033[92mDrain complete - all trades closed. Fleet {self.state}.\033[0m")
            self._notify(f"✅ All trades closed. Fleet is now {self.state}.")

    def _notify(self, text: str):
        try:
            sys.path.insert(0, str(ROOT))
            from app import telegram
            telegram.send_now(text)
        except Exception:               # noqa: BLE001
            pass

    # ----- telegram command handlers -----
    def _open_lines(self) -> str:
        opn = self.open_trades()
        if not opn:
            return "no trades open"
        out = [f"{len(opn)} trade(s) still open:"]
        for t in opn[:10]:
            out.append(f"  {t.get('symbol')} {str(t.get('side','')).upper()} "
                       f"{t.get('lots')} @ {t.get('entry')}")
        if len(opn) > 10:
            out.append(f"  ...and {len(opn)-10} more")
        return "\n".join(out)

    def cmd_status(self, _args: str = "") -> str:
        up = int(time.time() - self.started)
        icon = {"running": "🟢", "draining": "🟡", "paused": "⏸", "stopped": "🔴"}[self.state]
        lines = [f"{icon} Fleet {self.state.upper()} ({self.mode})",
                 f"{self.alive()}/{len(self.symbols)} bots up, {up//3600}h {up%3600//60}m",
                 f"symbols: {', '.join(self.symbols)}", "", self._open_lines()]
        if self.state == "draining":
            lines.append(f"\nwaiting for these to close, then -> {self.drain_goal}")
        return "\n".join(lines)

    def cmd_stop(self, _args: str = "") -> str:
        n = self.alive()
        opn = self.begin_drain("stopped")
        if not opn:
            return f"🛑 Stopped {n} bot(s). Nothing was open - fleet is fully stopped."
        return (f"🛑 Stopping {n} bot(s). No new trades will open.\n\n"
                f"{self._open_lines()}\n\n"
                f"They keep their stop and target, so the fleet will finish stopping "
                f"once the last one closes. I'll message you then.\n"
                f"/status to check, /start to cancel and resume.")

    def cmd_pause(self, _args: str = "") -> str:
        n = self.alive()
        opn = self.begin_drain("paused")
        if not opn:
            return f"⏸ Paused {n} bot(s). Nothing open. /start to resume."
        return (f"⏸ Pausing {n} bot(s) - no new trades.\n\n{self._open_lines()}\n\n"
                f"Open trades run to their stop or target. /start to resume now.")

    def cmd_start(self, _args: str = "") -> str:
        was = self.state
        n = self.start_all()
        extra = " (cancelled the drain)" if was == "draining" else ""
        return f"▶️ Started {n} bot(s) in {self.mode} mode{extra}:\n" + ", ".join(self.symbols)

    def cmd_bots(self, _args: str = "") -> str:
        lines = [f"📋 Bots ({self.state})"]
        for sym in self.symbols:
            p = self.procs.get(sym)
            lines.append(f"{sym}: {'running' if p and p.poll() is None else 'not running'}")
        return "\n".join(lines)


def register_telegram(fleet: "Fleet") -> str:
    """Wire the fleet's controls into the Telegram bot. Returns a status line."""
    sys.path.insert(0, str(ROOT))
    try:
        from app import telegram
    except Exception as e:  # noqa: BLE001
        return f"Telegram unavailable ({type(e).__name__})"

    telegram.register_command("/stop", "stop every bot (open trades keep their SL/TP)", fleet.cmd_stop)
    telegram.register_command("/start", "start the bots again", fleet.cmd_start)
    telegram.register_command("/pause", "stop opening new trades, let open ones finish", fleet.cmd_pause)
    telegram.register_command("/status", "are the bots running?", fleet.cmd_status)
    telegram.register_command("/bots", "each bot and whether it is up", fleet.cmd_bots)
    # /total, /prof and /loss are already answered by app/telegram.py from the ledger.

    st = telegram.status()
    if not st.get("token_set") or not st.get("chat_set"):
        return ("Telegram NOT linked - set it up in the app: Settings > Phone alerts "
                "(BotFather token, then 'Find my chat')")
    telegram.start_commands()
    return "Telegram linked - /stop /start /pause /status /bots /total /prof /loss"


def main():
    ap = argparse.ArgumentParser(description="Launch and watch one ML bot per symbol.")
    ap.add_argument("--symbols", help="comma list; default = every symbol with a trained model")
    ap.add_argument("--scan", action="store_true", help="show what's tradeable and exit")
    ap.add_argument("--live", action="store_true", help="send real orders (demo unless --allow-real)")
    ap.add_argument("--allow-real", action="store_true", help="permit a real-money account")
    ap.add_argument("--threshold", type=float, default=0.55)
    ap.add_argument("--max-open", type=int, default=3, help="max open trades per bot")
    ap.add_argument("--hours", default=None, help="server-time hours for entries, e.g. 7-20")
    ap.add_argument("--refresh", type=float, default=5.0, help="dashboard refresh, seconds")
    ap.add_argument("--force", action="store_true", help="start symbols that failed the scan too")
    args = ap.parse_args()

    wanted = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else None

    rows = scan(wanted)
    if args.scan or not rows:
        print(f"\n  {'symbol':<10} {'model':<7} {'spread':>7} {'range':>7} {'spread/range':>13}  why")
        print("  " + "-" * 86)
        for r in rows:
            mark = "\033[92mOK \033[0m" if r["ok"] else "\033[91mno \033[0m"
            ratio = f"{r['ratio']:.0%}" if r.get("ratio") else "-"
            print(f"  {r['symbol']:<10} {'yes' if r.get('model') else 'no':<7} "
                  f"{r.get('spread', '-'):>7} {r.get('atr', '-'):>7} "
                  f"{ratio:>13}  {mark} {r['why']}")
        if not rows:
            print("  nothing to scan - no trained models in models/. Train one first:")
            print("     python -m agent.train --symbol XAUUSD")
        print()
        if args.scan:
            return

    go = [r["symbol"] for r in rows if r["ok"] or args.force]
    if not go:
        print("  No symbol passed the scan. Use --force to start anyway, or fix the reasons above.")
        return

    mode = "live" if args.live else "paper"
    if args.live and not args.allow_real:
        print("  LIVE mode: orders go to MT5. A real-money account will be refused "
              "unless you also pass --allow-real.")
    print(f"\n  Starting {len(go)} bot(s) in {mode} mode: {', '.join(go)}")

    fleet = Fleet(args, go, mode)
    fleet.start_all()
    tg = register_telegram(fleet)
    print(f"  {tg}")
    time.sleep(2)

    def stop(*_):
        print("\n\n  Stopping every bot...")
        fleet._kill_bots()
        opn = fleet.open_trades()
        if opn:
            print(f"  {len(opn)} trade(s) left open - they keep their stop and target "
                  f"at the broker.\n  Close them in MT5 or with the app's Hold-to-flatten.\n")
        else:
            print("  All stopped, nothing open.\n")
        sys.exit(0)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    # The terminal is just a screen now - control the fleet from Telegram.
    while True:
        dashboard(fleet)
        fleet.tick()
        if fleet.state == "running":
            for sym, p in list(fleet.procs.items()):
                if p.poll() is not None:
                    print(f"  \033[91m{sym} stopped - restarting\033[0m "
                          f"(see logs/fleet/{sym}.log)")
                    fleet.procs[sym] = launch(sym, args)
        time.sleep(args.refresh)


if __name__ == "__main__":
    main()
