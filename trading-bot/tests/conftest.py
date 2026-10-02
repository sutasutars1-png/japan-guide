import numpy as np
import pandas as pd
import pytest


def make_ohlcv(n: int = 1200, seed: int = 7, drift: float = 0.0006, vol: float = 0.01) -> pd.DataFrame:
    """Deterministic synthetic hourly OHLCV: a random walk with mild upward
    drift, so SMA-crossover has real signal to find (used across tests so a
    strategy/optimizer/backtest all see consistent, reproducible data).
    """
    rng = np.random.default_rng(seed)
    returns = rng.normal(loc=drift, scale=vol, size=n)
    close = 20_000 * np.exp(np.cumsum(returns))
    high = close * (1 + np.abs(rng.normal(0, 0.002, size=n)))
    low = close * (1 - np.abs(rng.normal(0, 0.002, size=n)))
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    volume = rng.uniform(10, 100, size=n)
    timestamp = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")

    return pd.DataFrame(
        {
            "timestamp": timestamp,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


@pytest.fixture
def sample_ohlcv() -> pd.DataFrame:
    return make_ohlcv()
