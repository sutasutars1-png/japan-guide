from pathlib import Path

import pandas as pd

from trading_bot.paper.trader import PaperTrader
from trading_bot.strategy.moving_average import SMACrossoverStrategy


def _rising_then_falling_df(n_up=60, n_down=60):
    import numpy as np

    up = 100 * np.exp(np.linspace(0, 0.5, n_up))
    down = up[-1] * np.exp(np.linspace(0, -0.5, n_down))
    close = np.concatenate([up, down])
    timestamp = pd.date_range("2024-01-01", periods=len(close), freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": timestamp,
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": 1.0,
        }
    )


def test_step_buys_when_signal_turns_long(tmp_path: Path):
    df = _rising_then_falling_df()

    def provider():
        return df.iloc[:40]  # fast(5) > slow(20) well before the peak

    trader = PaperTrader(
        symbol="BTC/USDT",
        strategy_cls=SMACrossoverStrategy,
        params={"fast_window": 5, "slow_window": 20},
        data_provider=provider,
        state_dir=tmp_path,
        initial_cash=1000.0,
        fee_rate=0.0,
    )
    record = trader.step()

    assert record["action"] == "buy"
    assert not trader.portfolio.is_flat()
    assert trader.portfolio_path.exists()
    assert trader.decisions_log_path.exists()


def test_step_sells_when_signal_turns_flat(tmp_path: Path):
    df = _rising_then_falling_df()
    trader = PaperTrader(
        symbol="BTC/USDT",
        strategy_cls=SMACrossoverStrategy,
        params={"fast_window": 5, "slow_window": 20},
        data_provider=lambda: df.iloc[:40],
        state_dir=tmp_path,
        initial_cash=1000.0,
        fee_rate=0.0,
    )
    trader.step()  # buys
    assert not trader.portfolio.is_flat()

    # Move the data window forward to well into the downtrend.
    trader.data_provider = lambda: df.iloc[:110]
    record = trader.step()

    assert record["action"] == "sell"
    assert trader.portfolio.is_flat()


def test_set_params_swaps_live_strategy(tmp_path: Path):
    trader = PaperTrader(
        symbol="BTC/USDT",
        strategy_cls=SMACrossoverStrategy,
        params={"fast_window": 5, "slow_window": 20},
        data_provider=lambda: _rising_then_falling_df(),
        state_dir=tmp_path,
    )
    trader.set_params({"fast_window": 10, "slow_window": 30})
    assert trader.strategy.params == {"fast_window": 10, "slow_window": 30}


def test_run_loop_yields_requested_iterations_without_extra_sleep(tmp_path: Path):
    df = _rising_then_falling_df()
    trader = PaperTrader(
        symbol="BTC/USDT",
        strategy_cls=SMACrossoverStrategy,
        params={"fast_window": 5, "slow_window": 20},
        data_provider=lambda: df.iloc[:40],
        state_dir=tmp_path,
    )
    records = list(trader.run_loop(iterations=1, sleep_seconds=9999))
    assert len(records) == 1


def test_portfolio_persists_across_trader_instances(tmp_path: Path):
    df = _rising_then_falling_df()
    trader1 = PaperTrader(
        symbol="BTC/USDT",
        strategy_cls=SMACrossoverStrategy,
        params={"fast_window": 5, "slow_window": 20},
        data_provider=lambda: df.iloc[:40],
        state_dir=tmp_path,
        initial_cash=1000.0,
        fee_rate=0.0,
    )
    trader1.step()
    qty_after_buy = trader1.portfolio.position_qty

    trader2 = PaperTrader(
        symbol="BTC/USDT",
        strategy_cls=SMACrossoverStrategy,
        params={"fast_window": 5, "slow_window": 20},
        data_provider=lambda: df.iloc[:40],
        state_dir=tmp_path,
    )
    assert trader2.portfolio.position_qty == qty_after_buy


def test_paper_margin_trading_tracks_the_backtest_engine(tmp_path: Path, sample_ohlcv):
    """Same strategy, limit orders and carry: the paper account and the engine agree
    closely (they differ only in that paper holds a fixed quantity between trades
    while the engine rebalances to 1x each bar)."""
    import pytest

    from trading_bot.backtest.engine import BacktestEngine
    from trading_bot.strategy import STRATEGIES

    cls = STRATEGIES["sma_crossover_ls"]
    params = {"fast_window": 10, "slow_window": 50, "band": 0.0}
    start, end = 300, 700
    state = {"end": start}

    def provider():
        state["end"] += 1
        return sample_ohlcv.iloc[: state["end"]].reset_index(drop=True)

    state["end"] = start - 1
    trader = PaperTrader(symbol="BTC/USD", strategy_cls=cls, params=params, data_provider=provider, state_dir=tmp_path,
                         initial_cash=10_000.0, fee_rate=0.0002, order_type="limit", carry_rate_per_day=0.0004)
    records = [trader.step() for _ in range(end - start)]
    assert any("short" in r["action"] for r in records) and any("buy" in r["action"] for r in records)

    engine = BacktestEngine(initial_cash=10_000.0, fee_rate=0.0002, order_type="limit", carry_rate_per_day=0.0004)
    window = sample_ohlcv.iloc[start - 1 : end - 1].reset_index(drop=True)
    positions = cls(**params).generate_positions(sample_ohlcv).to_numpy()[start - 1 : end - 1]
    expected = engine.run_positions(window, positions).equity_curve.iloc[-1]
    assert records[-1]["equity"] == pytest.approx(expected, rel=0.02)
