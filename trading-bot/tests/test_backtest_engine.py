import pandas as pd
import pytest

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


import numpy as np  # noqa: E402

from trading_bot.backtest.engine import execute  # noqa: E402


def _bars(closes, highs=None, lows=None):
    n = len(closes)
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC"),
        "open": closes, "high": highs or [c * 1.01 for c in closes], "low": lows or [c * 0.99 for c in closes],
        "close": closes, "volume": [1.0] * n,
    })


def test_short_profits_when_price_falls_and_pays_both_sides_on_a_flip():
    df = _bars([100.0, 90.0, 81.0, 90.0])
    engine = BacktestEngine(initial_cash=100.0, fee_rate=0.001)
    res = engine.run_positions(df, [-1, -1, 1, 1])  # short from bar 0's close, flip long at bar 2's close
    assert res.position.tolist() == [0.0, -1.0, -1.0, 1.0]
    # Each bar: position x return - turnover x cost (a flip turns over 2 units).
    expected = 100 * (1 + 0.1 - 0.001) * (1 + 0.1) * (1 + (90 / 81 - 1) - 2 * 0.001)
    assert res.equity_curve.iloc[-1] == pytest.approx(expected)
    short = res.trades[0]
    assert short.side == -1 and short.entry_price == 100.0 and short.exit_price == 81.0
    assert short.pnl == pytest.approx(0.19 - 2 * 0.001)
    assert res.trades[1].side == 1 and res.trades[1].pnl is None  # still open


def test_carry_is_charged_every_bar_a_position_is_held():
    df = _bars([100.0] * 25)
    held_all_day = BacktestEngine(initial_cash=100.0, fee_rate=0.0, carry_rate_per_day=0.0004).run_positions(df, [1] * 25)
    assert held_all_day.equity_curve.iloc[-1] == pytest.approx(100 * (1 - 0.0004 / 24) ** 24)


def test_limit_order_fills_only_when_the_next_bar_trades_through():
    close = np.array([100.0, 101.0, 102.0, 99.0])
    high = np.array([100.5, 101.5, 102.5, 101.0])
    low = np.array([99.5, 100.5, 101.5, 98.0])
    # Buy decided at bar 0 (limit 100): bar 1's low 100.5 never trades below it -> no fill.
    # Re-placed at 101 after bar 1: bar 2's low 101.5 -> still no fill. At 102: bar 3's low 98 -> filled.
    assert execute(np.array([1.0, 1.0, 1.0, 1.0]), close, high, low, "limit").tolist() == [0, 0, 0, 1]
    assert execute(np.array([1.0, 1.0, 1.0, 1.0]), close, high, low, "market").tolist() == [0, 1, 1, 1]
    # Selling needs the next high above the limit.
    assert execute(np.array([-1.0, -1.0, -1.0, -1.0]), close, high, low, "limit").tolist() == [0, -1, -1, -1]


def test_unknown_order_type_rejected():
    with pytest.raises(ValueError):
        BacktestEngine(order_type="stop")
