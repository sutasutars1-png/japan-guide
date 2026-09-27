import pytest

from trading_bot.strategy.moving_average import SMACrossoverStrategy


def test_rejects_fast_not_less_than_slow():
    with pytest.raises(ValueError):
        SMACrossoverStrategy(fast_window=50, slow_window=10)


def test_generate_positions_is_binary_and_aligned(sample_ohlcv):
    strategy = SMACrossoverStrategy(fast_window=10, slow_window=50)
    positions = strategy.generate_positions(sample_ohlcv)
    assert len(positions) == len(sample_ohlcv)
    assert set(positions.unique().tolist()) <= {0.0, 1.0}


def test_no_signal_before_slow_window_warms_up(sample_ohlcv):
    strategy = SMACrossoverStrategy(fast_window=10, slow_window=50)
    positions = strategy.generate_positions(sample_ohlcv)
    assert (positions.iloc[:49] == 0.0).all()


def test_param_combinations_only_yields_valid_pairs():
    combos = list(SMACrossoverStrategy.param_combinations())
    assert combos
    assert all(c["fast_window"] < c["slow_window"] for c in combos)
