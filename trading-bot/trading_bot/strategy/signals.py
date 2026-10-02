"""Long/short signals aimed at the two weaknesses the 2-year `rolling` run found
in the SMA cross: many small whipsaw losses, and margin carry from being in
the market almost all the time. Each rule fits in one sentence and has two
parameters, so what the bot does stays explainable:

- `momentum_ls`: "long if the price is up more than `band` over the last
  `lookback_days`, short if down more than `band`, otherwise flat."
  A longer look-back flips far less often than an hourly SMA cross.
- `trend_strength_ls`: "only hold when the price is at least `k` standard
  deviations away from its `window_days` average, in that direction; get
  out when it crosses back over the average." Flat in quiet, tangled markets.
- `shock_reversion_ls`: "after a 24-hour move larger than `k` times its usual
  size, take the opposite side for `hold_hours`." Short holding periods, so
  almost no carry.

Bars stay 1h; the day-based windows are look-backs in hours (days * 24).
Every value at bar t uses only bars up to t (no lookahead).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import Strategy
from .more import hold_between

HOURS = 24


class MomentumLongShort(Strategy):
    name = "momentum_ls"
    param_grid = {"lookback_days": [1, 3, 7, 14], "band": [0.0, 0.02, 0.05]}

    def __init__(self, lookback_days: int = 7, band: float = 0.02):
        super().__init__(lookback_days=lookback_days, band=band)
        self.lookback_days, self.band = lookback_days, band

    def generate_positions(self, df: pd.DataFrame) -> pd.Series:
        ret = df["close"] / df["close"].shift(self.lookback_days * HOURS) - 1.0
        pos = (ret > self.band).astype(float) - (ret < -self.band).astype(float)
        return pos.rename("position")


class TrendStrengthLongShort(Strategy):
    name = "trend_strength_ls"
    param_grid = {"window_days": [3, 7, 14], "k": [1.0, 1.5, 2.0]}

    def __init__(self, window_days: int = 7, k: float = 1.5):
        super().__init__(window_days=window_days, k=k)
        self.window_days, self.k = window_days, k

    def generate_positions(self, df: pd.DataFrame) -> pd.Series:
        n = self.window_days * HOURS
        close = df["close"]
        z = (close - close.rolling(n, min_periods=n).mean()) / close.rolling(n, min_periods=n).std()
        long_ = hold_between(z > self.k, z < 0)
        short = hold_between(z < -self.k, z > 0)
        return (long_ - short).rename("position")


class ShockReversionLongShort(Strategy):
    name = "shock_reversion_ls"
    param_grid = {"k": [2.0, 2.5, 3.0], "hold_hours": [6, 12, 24]}
    usual_days = 30  # what counts as the "usual" size of a 24-hour move

    def __init__(self, k: float = 2.5, hold_hours: int = 12):
        super().__init__(k=k, hold_hours=hold_hours)
        self.k, self.hold_hours = k, hold_hours

    def generate_positions(self, df: pd.DataFrame) -> pd.Series:
        n = self.usual_days * HOURS
        r24 = df["close"] / df["close"].shift(HOURS) - 1.0
        usual = r24.rolling(n, min_periods=n).std()
        trigger = (r24 < -self.k * usual).astype(float) - (r24 > self.k * usual).astype(float)
        # hold the latest trigger's side for hold_hours bars (a new trigger restarts the clock)
        held = trigger.replace(0.0, np.nan).ffill(limit=self.hold_hours - 1).fillna(0.0)
        return held.rename("position")
