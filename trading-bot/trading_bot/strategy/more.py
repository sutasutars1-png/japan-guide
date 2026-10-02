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
    members: tuple = ()  # set below, after the long/short members are defined

    def __init__(self, strategy: str = "", **params):
        members = {m.name: m for m in self.members}
        strategy = strategy or self.members[0].name
        if strategy not in members:
            raise ValueError(f"unknown member strategy {strategy!r}; choose from {sorted(members)}")
        self.inner = members[strategy](**params)
        super().__init__(strategy=strategy, **self.inner.params)

    def generate_positions(self, df: pd.DataFrame) -> pd.Series:
        return self.inner.generate_positions(df)

    @classmethod
    def param_combinations(cls):
        for member in cls.members:
            for combo in member.param_combinations():
                yield {"strategy": member.name, **combo}


# ---------------------------------------------------------------------------
# Long/short variants (margin). Same signals, mirrored for the short side, so
# a downtrend can be traded instead of only sat out. Positions: -1, 0, 1.
# ---------------------------------------------------------------------------


class SMACrossoverLongShort(Strategy):
    """Long when fast SMA is above slow by more than `band`, short when below by
    more than `band`, flat in between. The band keeps the system out of the
    market (no fees, no margin carry) while the two averages are tangled."""

    name = "sma_crossover_ls"
    param_grid = {"fast_window": [5, 10, 20, 30], "slow_window": [30, 50, 100, 200], "band": [0.0, 0.005, 0.01]}

    def __init__(self, fast_window: int = 10, slow_window: int = 50, band: float = 0.0):
        if fast_window >= slow_window:
            raise ValueError("fast_window must be < slow_window")
        super().__init__(fast_window=fast_window, slow_window=slow_window, band=band)
        self.fast_window, self.slow_window, self.band = fast_window, slow_window, band

    def generate_positions(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        fast = close.rolling(self.fast_window, min_periods=self.fast_window).mean()
        slow = close.rolling(self.slow_window, min_periods=self.slow_window).mean()
        pos = (fast > slow * (1 + self.band)).astype(float) - (fast < slow * (1 - self.band)).astype(float)
        pos[slow.isna()] = 0.0
        return pos.rename("position")

    @classmethod
    def param_combinations(cls):
        for combo in super().param_combinations():
            if combo["fast_window"] < combo["slow_window"]:
                yield combo


class DonchianBreakoutLongShort(DonchianBreakoutStrategy):
    """Long on an upside breakout, short on a downside breakdown; each side
    exits on the opposite `exit_window` extreme."""

    name = "donchian_breakout_ls"

    def generate_positions(self, df: pd.DataFrame) -> pd.Series:
        high_e = df["high"].rolling(self.entry_window, min_periods=self.entry_window).max().shift(1)
        low_e = df["low"].rolling(self.entry_window, min_periods=self.entry_window).min().shift(1)
        high_x = df["high"].rolling(self.exit_window, min_periods=self.exit_window).max().shift(1)
        low_x = df["low"].rolling(self.exit_window, min_periods=self.exit_window).min().shift(1)
        close = df["close"]
        long_ = hold_between(close > high_e, close < low_x)
        short = hold_between(close < low_e, close > high_x)
        return (long_ - short).rename("position")


class RSIReversionLongShort(RSIReversionStrategy):
    """Long below `lower` until above `upper`; short above 100-`lower` until
    below 100-`upper`. If both sides are live at once the position is flat."""

    name = "rsi_reversion_ls"

    def generate_positions(self, df: pd.DataFrame) -> pd.Series:
        r = rsi(df["close"], self.period)
        long_ = hold_between(r < self.lower, r > self.upper)
        short = hold_between(r > 100 - self.lower, r < 100 - self.upper)
        return (long_ - short).rename("position")


LS_MEMBERS: tuple[type[Strategy], ...] = (SMACrossoverLongShort, DonchianBreakoutLongShort, RSIReversionLongShort)


class MultiLongShort(MultiStrategy):
    name = "multi_ls"
    members = LS_MEMBERS


MultiStrategy.members = MEMBERS
