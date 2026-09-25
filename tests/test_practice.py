"""Practice mode (paper): trades the model's top ~10% readings; seeded from recent candles so a start needn't wait an hour."""
import numpy as np

from agent.practice import MIN_SEEN, WINDOW, Practice


def test_fresh_start_waits_without_seed():
    p = Practice()
    assert all(p.decide(0.5, 0.0)[0] is None for _ in range(MIN_SEEN - 1))


def test_seeded_start_trades_strong_readings_at_once():
    p = Practice()
    assert p.seed(np.random.default_rng(1).uniform(0, 0.1, WINDOW + 50)) == WINDOW
    assert p.decide(0.2, 0.01)[0] == "buy" and p.decide(0.01, 0.3)[0] == "sell"
    assert p.decide(0.01, 0.02)[0] is None


def test_learned_bar_is_capped_at_the_models_own_scale():
    """A min_confidence of 0.20 learned elsewhere must not block a model that reads 0.05-0.10."""
    import time as _time

    from agent import learn
    rules = {"min_confidence": 0.20, "cautions": [{"side": "buy", "setup": None, "until": _time.time() + 3600,
                                                    "min_prob": 0.30, "until_utc": "2026-09-26T10:00", "why": "x"}]}
    recent = list(np.linspace(0.05, 0.10, 500))
    assert learn.block_reason(rules, "sell", 0.09, 12) is not None                      # no recent readings: as learned
    assert learn.block_reason(rules, "sell", 0.09, 12, recent_probs=recent) is None     # capped at the median 0.075
    assert learn.block_reason(rules, "sell", 0.06, 12, recent_probs=recent) is not None  # still skips weak ones
    assert learn.block_reason(rules, "buy", 0.095, 12, recent_probs=recent) is None     # caution capped at the 80th pct
