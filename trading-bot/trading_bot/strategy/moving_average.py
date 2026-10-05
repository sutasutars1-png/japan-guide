from __future__ import annotations

import pandas as pd

from .base import Strategy


class SMACrossoverStrategy(Strategy):
    """Long when the fast SMA is above the slow SMA, flat otherwise."""

    name = "sma_crossover"
    param_grid = {
        "fast_window": [5, 10, 20, 30],
        "slow_window": [30, 50, 100, 200],
    }

    def __init__(self, fast_window: int = 10, slow_window: int = 50):
        if fast_window >= slow_window:
            raise ValueError("fast_window must be < slow_window")
        super().__init__(fast_window=fast_window, slow_window=slow_window)
        self.fast_window = fast_window
        self.slow_window = slow_window

    def generate_positions(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        fast = close.rolling(self.fast_window, min_periods=self.fast_window).mean()
        slow = close.rolling(self.slow_window, min_periods=self.slow_window).mean()
        position = (fast > slow).astype(float)
        # No signal until both windows have enough history.
        position[slow.isna()] = 0.0
        return position.rename("position")

    @classmethod
    def param_combinations(cls):
        for combo in super().param_combinations():
            if combo["fast_window"] < combo["slow_window"]:
                yield combo
