"""Practice mode (Paper and Replay only): trade the model's best-looking setups instead of a fixed threshold.

With 8:1 exits the model's raw confidence is small (a few %), so a fixed threshold can mean it never trades and never
learns. Practice mode enters when the favourite side's confidence is in the top TOP_PCT of the model's own readings
over the last day of candles. Demo and Real always use the strict threshold.
"""
from collections import deque

import numpy as np

WINDOW = 1440       # one day of M1 candles
TOP_PCT = 10.0      # enter on the top 10% of readings
MIN_SEEN = 60       # need an hour of readings first


class Practice:
    def __init__(self, top_pct: float = TOP_PCT):
        self.top_pct = top_pct
        self.seen = deque(maxlen=WINDOW)

    def decide(self, p_long: float, p_short: float):
        """Return (side, prob, cutoff) or (None, None, cutoff)."""
        best = max(p_long, p_short)
        self.seen.append(best)
        if len(self.seen) < MIN_SEEN:
            return None, None, None
        cutoff = float(np.percentile(self.seen, 100 - self.top_pct))
        if best >= cutoff and best > 0:
            return ("buy", p_long, cutoff) if p_long >= p_short else ("sell", p_short, cutoff)
        return None, None, cutoff
