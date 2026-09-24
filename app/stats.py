"""You vs the bot: the same numbers for your manual trades and the bot's (`GET /api/stats/compare`, weekly review).

"you" = closed deals of positions opened with magic 0 (the Manual tab, MT5 itself, the phone app), from MT5's history.
"bot" = closed trades in the bot's ledger for one mode. Times are MT5 server time (the chart's clock): `by_hour` and
`by_weekday` use the close time, `curve` is the running total after each close.
"""
from datetime import datetime, timezone

from agent import ledger, progression

from . import manual

EPOCH0 = datetime(2000, 1, 1, tzinfo=timezone.utc)


def _ts(iso: str | None) -> int | None:
    try:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()) if iso else None
    except ValueError:
        return None


def summarize(trades: list[dict]) -> dict:
    """trades: [{time (close), open_time, profit}] -> the stats block the UI shows."""
    trades = sorted(trades, key=lambda t: t["time"])
    pnl = [t["profit"] for t in trades]
    wins = [p for p in pnl if p > 0]
    losses = [p for p in pnl if p < 0]
    gw, gl = sum(wins), -sum(losses)
    holds = [(t["time"] - t["open_time"]) / 60 for t in trades if t.get("open_time")]
    by_hour = [{"hour": h, "trades": 0, "net": 0.0} for h in range(24)]
    by_day = [{"day": d, "trades": 0, "net": 0.0} for d in range(7)]
    curve, cum = [], 0.0
    for t in trades:
        when = datetime.fromtimestamp(t["time"], timezone.utc)
        for row in (by_hour[when.hour], by_day[when.weekday()]):
            row["trades"] += 1
            row["net"] = round(row["net"] + t["profit"], 2)
        cum += t["profit"]
        curve.append({"time": t["time"], "cum": round(cum, 2)})
    n = len(trades)
    return {"trades": n, "wins": len(wins), "losses": len(losses),
            "win_rate": round(100 * len(wins) / n, 1) if n else None,
            "net": round(sum(pnl), 2),
            "avg_win": round(gw / len(wins), 2) if wins else None,
            "avg_loss": round(-gl / len(losses), 2) if losses else None,
            "profit_factor": round(gw / gl, 2) if gl else None,            # None: no losing trades yet
            "expectancy": round(sum(pnl) / n, 2) if n else None,
            "best_trade": round(max(pnl), 2) if pnl else None,
            "worst_trade": round(min(pnl), 2) if pnl else None,
            "avg_hold_min": round(sum(holds) / len(holds), 1) if holds else None,
            "by_hour": by_hour, "by_weekday": by_day, "curve": curve}


def lite(s: dict) -> dict:
    return {k: s[k] for k in ("trades", "win_rate", "net", "profit_factor")}


def you_trades(start: datetime, end: datetime) -> list[dict]:
    """Your closed manual trades between start and end (MT5 history; empty when MT5 is offline)."""
    try:
        rows = manual.history_range(start, end)
    except Exception:                                  # noqa: BLE001 - MT5 offline: no manual trades to show
        return []
    return [{"time": r["time"], "open_time": r["open_time"], "profit": r["profit"], "symbol": r["symbol"]}
            for r in rows if r["owner"] == "you"]


def bot_modes(mode: str | None) -> tuple[str, ...]:
    """paper | live (demo + real) | all | demo | real | replay; None = the stage the bot is on now."""
    if not mode:
        mode = progression.stage_info(progression.load()["stage"])["mode"]
    return {"live": ("demo", "real"), "all": ("paper", "demo", "real")}.get(mode, (mode,))


def bot_trades(start_ts: int, end_ts: int, mode: str | None = None) -> list[dict]:
    out = []
    for m in bot_modes(mode):
        for r in ledger.recent(1_000_000, m):
            if r["status"] != "closed":
                continue
            close = r["close_bar"] or _ts(r["close_utc"])
            if close is None or not start_ts <= close < end_ts:
                continue
            out.append({"time": close, "open_time": r["open_bar"] or _ts(r["open_utc"]), "profit": r["pnl"] or 0.0,
                        "symbol": r["symbol"]})
    return out


def compare(days: float = 30, mode: str | None = None, start: datetime | None = None,
            end: datetime | None = None) -> dict:
    end = end or datetime.now(timezone.utc)
    start = start or (EPOCH0 if not days else datetime.fromtimestamp(end.timestamp() - days * 86400, timezone.utc))
    you = you_trades(start, end)
    you = [t for t in you if start.timestamp() <= t["time"] < end.timestamp()]
    bot = bot_trades(int(start.timestamp()), int(end.timestamp()), mode)
    return {"from": int(start.timestamp()), "to": int(end.timestamp()), "bot_modes": list(bot_modes(mode)),
            "you": summarize(you), "bot": summarize(bot)}
