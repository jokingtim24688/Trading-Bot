"""Honest backtest report: how the current model would have done on months it never trained on, after costs.

The app runs the Replay engine on the model's unseen test period at full speed with:
- the threshold rule (not practice mode) and no learned rules (they may have been learned from those same months);
- commission per lot and slippage on every market fill (entry, stop, early exit), on top of the candles' spread;
- its own ledger file (data/backtest.db), so nothing reaches your real stats, lessons or the stage ladder.

Then `write_report` compares the result with the Paper -> Demo gate and writes data/backtest.json + data/backtest.md.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from . import ledger, progression


def _metrics(rows: list[dict], balance: float) -> dict:
    rows = sorted(rows, key=lambda r: r["close_utc"] or "")
    pnl = [r["pnl"] or 0.0 for r in rows]
    wins = [p for p in pnl if p > 0]
    losses = [p for p in pnl if p < 0]
    eq = peak = balance
    dd = 0.0
    months: dict[str, list] = {}
    days = set()
    for r, p in zip(rows, pnl):
        eq += p
        peak = max(peak, eq)
        dd = max(dd, (peak - eq) / peak * 100 if peak > 0 else 0)
        day = (r["close_utc"] or "")[:10]
        days.add(day)
        months.setdefault(day[:7], []).append(p)
    n = len(rows)
    gl = -sum(losses)
    return {"trades": n, "win_rate": round(100 * len(wins) / n, 1) if n else None, "net": round(sum(pnl), 2),
            "profit_factor": round(sum(wins) / gl, 2) if gl else None,
            "expectancy": round(sum(pnl) / n, 2) if n else None,
            "score": round(sum(r["score"] or 0 for r in rows), 1),
            "max_drawdown_pct": round(dd, 2), "days": len(days),
            "trades_per_day": round(n / len(days), 1) if days else None,
            "stop_hits": sum(1 for r in rows if r["exit_reason"] == "sl"),
            "return_pct": round(100 * sum(pnl) / balance, 2) if balance else None,
            "months": [{"month": k, "trades": len(v), "net": round(sum(v), 2)} for k, v in sorted(months.items())]}


def _gate(m: dict) -> list[dict]:
    g = progression.DEFAULT_GATES["paper"]
    checks = [("trades", "Trades", m["trades"], g["min_trades"], m["trades"] >= g["min_trades"]),
              ("days", "Trading days", m["days"], g["min_days"], m["days"] >= g["min_days"]),
              ("score", "Score (points)", m["score"], g["min_score"], m["score"] >= g["min_score"]),
              ("profit_factor", "Profit factor", m["profit_factor"], g["min_profit_factor"],
               (m["profit_factor"] or 0) >= g["min_profit_factor"]),
              ("max_drawdown_pct", "Max drawdown %", m["max_drawdown_pct"], g["max_drawdown_pct"],
               m["max_drawdown_pct"] <= g["max_drawdown_pct"])]
    return [{"id": i, "label": lbl, "value": v, "need": need, "ok": bool(ok)} for i, lbl, v, need, ok in checks]


def write_report(path: Path, args, start, end, skips=None) -> dict:
    rows = [r for r in ledger.recent(1_000_000, "replay") if r["status"] == "closed"]
    m = _metrics(rows, args.balance)
    gate = _gate(m)
    passed = all(c["ok"] for c in gate)
    if not m["trades"]:
        verdict = "No trades on the test period: the model never reached the threshold. Lower it or retrain."
    elif passed:
        verdict = ("Passes the Paper -> Demo gate on months the model never saw, after costs. Paper trading is still "
                   "the real test, but this is a good sign.")
    elif (m["net"] or 0) > 0:
        verdict = "Makes money after costs but misses part of the gate: " + ", ".join(c["label"] for c in gate if not c["ok"]) + "."
    else:
        verdict = "Loses money after costs on months it never saw. Don't move this model beyond Paper; retrain or change the rules."
    report = {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "period": {"from": str(start), "to": str(end)}, "symbol": args.symbol, "threshold": args.threshold,
              "costs": {"commission_per_lot": args.commission, "slippage_points": args.slippage,
                        "spread": "from the candles"},
              "balance": args.balance, "metrics": m, "gate": gate, "passed": passed, "verdict": verdict,
              "skips": [[k, n] for k, n in (skips.most_common(6) if skips else [])]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=1), encoding="utf-8")
    md = [f"# Backtest {args.symbol} M1: {str(start)[:10]} to {str(end)[:10]}", "",
          f"**{verdict}**", "",
          f"Costs: commission {args.commission:g} per lot round trip, slippage {args.slippage:g} points per market fill, "
          "spread from the candles. Threshold rule, no learned rules, the model's unseen test period.", "",
          "| Gate (Paper -> Demo) | Result | Needed | |", "|---|---|---|---|"]
    for c in gate:
        need = f"<= {c['need']}" if c["id"] == "max_drawdown_pct" else f">= {c['need']}"
        md.append(f"| {c['label']} | {c['value']} | {need} | {'✅' if c['ok'] else '❌'} |")
    if m["trades"]:
        md += ["", f"Win rate {m['win_rate']}% · net {m['net']:+,.2f} ({m['return_pct']}%) · expectancy "
                   f"{m['expectancy']:+.2f} per trade · {m['trades_per_day']} trades a day · {m['stop_hits']} stop hits"]
    md += ["", "| Month | Trades | Net |", "|---|---|---|"]
    md += [f"| {x['month']} | {x['trades']} | {x['net']:+,.2f} |" for x in m["months"]]
    path.with_suffix(".md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"\nbacktest report: {verdict}", flush=True)
    return report
