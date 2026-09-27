import pandas as pd
import pytest

from trading_bot.backtest.engine import BacktestEngine
from trading_bot.optimize.optimizer import WalkForwardOptimizer, default_score
from trading_bot.strategy.moving_average import SMACrossoverStrategy


def test_optimize_produces_folds_and_final_params(sample_ohlcv):
    optimizer = WalkForwardOptimizer(engine=BacktestEngine(), n_splits=3)
    result = optimizer.optimize(sample_ohlcv, SMACrossoverStrategy, timeframe="1h")

    assert result.strategy_name == "sma_crossover"
    assert len(result.folds) <= 2  # n_splits - 1
    assert result.leaderboard
    for fold in result.folds:
        assert fold.test_start >= fold.train_end
        assert set(fold.chosen_params) == {"fast_window", "slow_window"}


def test_optimize_rejects_too_little_data():
    optimizer = WalkForwardOptimizer(n_splits=4)
    tiny_df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=5, freq="h", tz="UTC"),
            "open": [1, 1, 1, 1, 1],
            "high": [1, 1, 1, 1, 1],
            "low": [1, 1, 1, 1, 1],
            "close": [1, 1, 1, 1, 1],
            "volume": [1, 1, 1, 1, 1],
        }
    )
    with pytest.raises(ValueError):
        optimizer.optimize(tiny_df, SMACrossoverStrategy)


def test_n_splits_below_two_is_rejected():
    with pytest.raises(ValueError):
        WalkForwardOptimizer(n_splits=1)


def test_default_score_penalizes_low_trade_count():
    assert default_score({"num_trades": 1, "sharpe": 5.0}, min_trades=5) == float("-inf")
    assert default_score({"num_trades": 10, "sharpe": 1.5}, min_trades=5) == 1.5
