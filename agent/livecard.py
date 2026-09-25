"""What the Bot tab's live card shows about the agent's thinking, in plain words.

- `confluence(row, lean)`: four pills (trend, momentum, volatility, execution ready), each good / bad / neutral for
  the side the model leans to, with a short text.
- `confidence_pct(seen, best)`: how the reading ranks against the model's own last day of readings (0-100). The raw
  probability is small with 8:1 exits (a few %), so the rank is what reads as "confidence".
- `headline(...)`: one sentence for the hero banner ("Scanning XAUUSD: H1 trend is bullish, ...").
- `reason(...)`: the one-sentence reason on a co-pilot proposal.
"""
import numpy as np


def _trend(row: dict) -> int:
    """+1 bullish, -1 bearish, 0 mixed: the H1 swing structure, else the EMA 200 slope."""
    h1 = row.get("h1_structure") or 0
    if h1 >= 2:
        return 1
    if h1 <= -2:
        return -1
    s = row.get("slope_ema200") or 0
    return 1 if s > 0.05 else -1 if s < -0.05 else 0


def _momentum(row: dict) -> int:
    rsi, r15 = row.get("rsi14") or 0.5, row.get("ret_15") or 0
    if rsi > 0.55 and r15 > 0:
        return 1
    if rsi < 0.45 and r15 < 0:
        return -1
    return 0


def _vol(row: dict) -> str:
    a = row.get("atr_rel")
    if a is None or not np.isfinite(a):
        return "normal"
    return "quiet" if a < 0.7 else "wild" if a > 1.8 else "normal"


WORD = {1: "bullish", -1: "bearish", 0: "mixed"}


def confluence(row: dict, lean: str, ready: bool, ready_text: str) -> list[dict]:
    sgn = 1 if lean == "buy" else -1
    t, m, v = _trend(row), _momentum(row), _vol(row)

    def pill(key, name, val, text):
        state = "neutral" if val == 0 else "good" if val == sgn else "bad"
        return {"key": key, "name": name, "state": state, "text": text}
    out = [pill("trend", "Trend alignment", t, f"H1 trend {WORD[t]}"),
           pill("momentum", "Momentum", m, {1: "rising", -1: "falling", 0: "flat"}[m] + f", RSI {100 * (row.get('rsi14') or 0.5):.0f}")]
    out.append({"key": "volatility", "name": "Volatility", "state": "good" if v == "normal" else "neutral" if v == "quiet" else "bad",
                "text": {"quiet": "quiet market", "normal": "normal range", "wild": "unusually wide"}[v]})
    out.append({"key": "ready", "name": "Execution ready", "state": "good" if ready else "bad", "text": ready_text})
    return out


def confidence_pct(seen, best: float) -> int | None:
    """Rank of `best` among the recent readings, 0-100 (None until there are some)."""
    if not seen:
        return None
    a = np.fromiter(seen, float)
    return int(round(100 * float((a < best).mean() + 0.5 * (a == best).mean())))


def headline(symbol: str, row: dict | None, lean: str | None, decision: str, reason: str, n_open: int,
             open_side: str | None, need: float, proposal: bool) -> str:
    if proposal:
        return f"Co-pilot: proposing a {lean.upper()} on {symbol}, waiting for your approval"
    if decision.startswith("OPENED"):
        return f"Entered a {decision.split()[-1]} on {symbol}, riding it toward take profit"
    if n_open:
        side = f"{open_side.upper()} " if open_side else ""
        return (f"In an active {side}trade on {symbol}, riding it toward take profit"
                + (f" ({n_open} open)" if n_open > 1 else ""))
    if row is None:
        return f"Loading {symbol}: reading the chart"
    t, m = _trend(row), _momentum(row)
    ctx = f"H1 trend is {WORD[t]}, momentum is {({1: 'rising', -1: 'falling', 0: 'flat'})[m]}"
    if decision.startswith("skipped"):
        return f"Strong {lean.upper()} reading on {symbol}, but held back: {reason.split(' (')[0]}"
    if decision == "holding":
        return f"Holding: {reason}"
    want = "a pullback" if t and m and t != m else "a stronger reading"
    return f"Scanning {symbol}: {ctx}. Waiting for {want} above {need:.0%} before entering"


def reason(side: str, setups: list[str], row: dict, prob: float, need: float, conf: int | None) -> str:
    bits = [setups[0]] if setups else []
    t, m = _trend(row), _momentum(row)
    sgn = 1 if side == "buy" else -1
    if t == sgn:
        bits.append(f"H1 trend {WORD[t]}")
    if m == sgn:
        bits.append("momentum " + ("rising" if m > 0 else "falling"))
    lead = ", ".join(bits) if bits else "The model favours this side"
    rank = f", stronger than {conf}% of the last day's readings" if conf is not None else ""
    return f"{lead}: {side} confidence {prob:.1%} vs {need:.1%} needed{rank}."
