"""Additional long-only strategies, so self-improvement can choose *how* to
trade, not only which SMA windows to use:

- `DonchianBreakoutStrategy` (trend-following): enter when the close breaks
  above the highest high of the previous `entry_window` bars; exit when it
  falls below the lowest low of the previous `exit_window` bars. Stays in
  long uptrends that an SMA crossover gets shaken out of.
- `RSIReversionStrategy` (mean reversion): enter when RSI drops below `lower`,
  exit when it recovers above `upper`. Aimed at range-bound markets.
- `MultiStrategy`: one parameter space spanning every member strategy, with
  the member's name as the `strategy` parameter — so the optimizer, promotion
  gate, replay and live loop select among strategies with no special casing.

All signals use only bars up to the current one (no lookahead).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import Strategy
from .moving_average import SMACrossoverStrategy


def hold_between(enter: pd.Series, exit_: pd.Series) -> pd.Series:
    """1.0 from an entry bar until an exit bar, else 0.0. Exit wins a tie."""
    state = pd.Series(np.nan, index=enter.index)
    state[enter.to_numpy()] = 1.0
    state[exit_.to_numpy()] = 0.0
    return state.ffill().fillna(0.0)


class DonchianBreakoutStrategy(Strategy):
    name = "donchian_breakout"
    param_grid = {"entry_window": [24, 48, 96, 168], "exit_window": [12, 24, 48]}

    def __init__(self, entry_window: int = 48, exit_window: int = 24):
        if exit_window > entry_window:
            raise ValueError("exit_window must be <= entry_window")
        super().__init__(entry_window=entry_window, exit_window=exit_window)
        self.entry_window = entry_window
        self.exit_window = exit_window

    def generate_positions(self, df: pd.DataFrame) -> pd.Series:
        prior_high = df["high"].rolling(self.entry_window, min_periods=self.entry_window).max().shift(1)
        prior_low = df["low"].rolling(self.exit_window, min_periods=self.exit_window).min().shift(1)
        return hold_between(df["close"] > prior_high, df["close"] < prior_low).rename("position")

    @classmethod
    def param_combinations(cls):
        for combo in super().param_combinations():
            if combo["exit_window"] <= combo["entry_window"]:
                yield combo


def rsi(close: pd.Series, period: int) -> pd.Series:
    """RSI from simple rolling means of gains and losses (Cutler's RSI)."""
    delta = close.diff()
    avg_gain = delta.clip(lower=0).rolling(period, min_periods=period).mean()
    avg_loss = (-delta.clip(upper=0)).rolling(period, min_periods=period).mean()
    return 100 - 100 / (1 + avg_gain / avg_loss)


class RSIReversionStrategy(Strategy):
    name = "rsi_reversion"
    param_grid = {"period": [14], "lower": [25, 30, 35], "upper": [50, 60, 70]}

    def __init__(self, period: int = 14, lower: float = 30, upper: float = 60):
        if not lower < upper:
            raise ValueError("lower must be < upper")
        super().__init__(period=period, lower=lower, upper=upper)
        self.period, self.lower, self.upper = period, lower, upper

    def generate_positions(self, df: pd.DataFrame) -> pd.Series:
        r = rsi(df["close"], self.period)
        return hold_between(r < self.lower, r > self.upper).rename("position")


MEMBERS: tuple[type[Strategy], ...] = (SMACrossoverStrategy, DonchianBreakoutStrategy, RSIReversionStrategy)


class MultiStrategy(Strategy):
    name = "multi"

    def __init__(self, strategy: str = "sma_crossover", **params):
        members = {m.name: m for m in MEMBERS}
        if strategy not in members:
            raise ValueError(f"unknown member strategy {strategy!r}; choose from {sorted(members)}")
        self.inner = members[strategy](**params)
        super().__init__(strategy=strategy, **self.inner.params)

    def generate_positions(self, df: pd.DataFrame) -> pd.Series:
        return self.inner.generate_positions(df)

    @classmethod
    def param_combinations(cls):
        for member in MEMBERS:
            for combo in member.param_combinations():
                yield {"strategy": member.name, **combo}
