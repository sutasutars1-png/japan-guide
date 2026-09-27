import pandas as pd

from trading_bot.backtest.engine import BacktestEngine
from trading_bot.strategy.moving_average import SMACrossoverStrategy


def test_equity_curve_aligned_with_input(sample_ohlcv):
    engine = BacktestEngine(initial_cash=10_000.0, fee_rate=0.001)
    strategy = SMACrossoverStrategy(fast_window=10, slow_window=50)
    result = engine.run(sample_ohlcv, strategy, timeframe="1h")

    assert len(result.equity_curve) == len(sample_ohlcv)
    assert result.equity_curve.iloc[0] > 0
    assert "sharpe" in result.metrics
    assert "max_drawdown" in result.metrics


def test_flat_strategy_never_trades_and_preserves_cash(sample_ohlcv):
    class AlwaysFlat(SMACrossoverStrategy):
        def generate_positions(self, df):
            return pd.Series(0.0, index=df.index)

    engine = BacktestEngine(initial_cash=10_000.0, fee_rate=0.001)
    result = engine.run(sample_ohlcv, AlwaysFlat(fast_window=10, slow_window=50), timeframe="1h")

    assert result.metrics["num_trades"] == 0
    assert result.equity_curve.iloc[-1] == 10_000.0


def test_no_lookahead_signal_takes_effect_next_bar(sample_ohlcv):
    """A position flip decided at bar t must not affect bar t's own return —
    only bar t+1 onward. Verified by construction against `executed_position`.
    """
    engine = BacktestEngine(initial_cash=10_000.0, fee_rate=0.0)
    strategy = SMACrossoverStrategy(fast_window=10, slow_window=50)
    result = engine.run(sample_ohlcv, strategy, timeframe="1h")

    raw_position = strategy.generate_positions(sample_ohlcv)
    expected_executed = raw_position.shift(1).fillna(0.0)
    assert (result.position.reset_index(drop=True) == expected_executed.reset_index(drop=True)).all()


def test_trades_have_consistent_entry_exit_ordering(sample_ohlcv):
    engine = BacktestEngine(initial_cash=10_000.0, fee_rate=0.001)
    strategy = SMACrossoverStrategy(fast_window=10, slow_window=50)
    result = engine.run(sample_ohlcv, strategy, timeframe="1h")

    for trade in result.trades:
        if trade.exit_time is not None:
            assert trade.exit_time >= trade.entry_time


def test_empty_dataframe_raises():
    import pytest

    engine = BacktestEngine()
    strategy = SMACrossoverStrategy(fast_window=10, slow_window=50)
    with pytest.raises(ValueError):
        engine.run(pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"]), strategy)
