import pandas as pd
import pytest

from trading_bot.backtest import metrics


def test_total_return_doubling():
    equity = pd.Series([100.0, 150.0, 200.0])
    assert metrics.total_return(equity) == 1.0


def test_total_return_empty_or_single_is_zero():
    assert metrics.total_return(pd.Series([100.0])) == 0.0
    assert metrics.total_return(pd.Series([], dtype=float)) == 0.0


def test_max_drawdown_detects_peak_to_trough():
    equity = pd.Series([100.0, 120.0, 90.0, 110.0])
    dd = metrics.max_drawdown(equity)
    assert dd == pytest.approx(90.0 / 120.0 - 1.0)


def test_max_drawdown_monotonic_increase_is_zero():
    equity = pd.Series([100.0, 110.0, 120.0])
    assert metrics.max_drawdown(equity) == 0.0


def test_sharpe_ratio_zero_variance_is_zero():
    returns = pd.Series([0.01, 0.01, 0.01])
    assert metrics.sharpe_ratio(returns, periods_per_year=365) == 0.0


def test_sharpe_ratio_positive_for_positive_returns():
    returns = pd.Series([0.01, 0.02, -0.005, 0.015, 0.01])
    assert metrics.sharpe_ratio(returns, periods_per_year=365) > 0


def test_win_rate_ignores_open_unrealized_trades():
    trades = [{"pnl": 0.1}, {"pnl": -0.05}, {"pnl": None}]
    assert metrics.win_rate(trades) == 0.5


def test_win_rate_no_closed_trades_is_zero():
    assert metrics.win_rate([{"pnl": None}]) == 0.0
