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
