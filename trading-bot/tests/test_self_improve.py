from pathlib import Path

from trading_bot.backtest.engine import BacktestEngine
from trading_bot.optimize.optimizer import WalkForwardOptimizer
from trading_bot.paper.trader import PaperTrader
from trading_bot.self_improve.loop import SelfImprovementLoop
from trading_bot.strategy.moving_average import SMACrossoverStrategy


def _make_loop(tmp_path: Path, history_df):
    trader = PaperTrader(
        symbol="BTC/USDT",
        strategy_cls=SMACrossoverStrategy,
        params={"fast_window": 10, "slow_window": 50},
        data_provider=lambda: history_df,
        state_dir=tmp_path,
    )
    optimizer = WalkForwardOptimizer(engine=BacktestEngine(), n_splits=3)
    return SelfImprovementLoop(
        trader=trader,
        optimizer=optimizer,
        strategy_cls=SMACrossoverStrategy,
        history_provider=lambda: history_df,
        state_dir=tmp_path,
        min_walk_forward_score=-100.0,  # low floor: focus this test on the margin gate, not the floor
        min_improvement_margin=0.05,
    ), trader


def test_first_run_promotes_from_unknown_baseline(tmp_path: Path, sample_ohlcv):
    loop, trader = _make_loop(tmp_path, sample_ohlcv)
    record = loop.maybe_improve()

    assert record["promoted"] is True
    assert loop.active_params_path.exists()
    assert trader.strategy.params == record["candidate_final_params"]


def test_repeat_run_on_identical_data_does_not_reprompote(tmp_path: Path, sample_ohlcv):
    loop, _ = _make_loop(tmp_path, sample_ohlcv)
    first = loop.maybe_improve()
    assert first["promoted"] is True

    second = loop.maybe_improve()
    assert second["promoted"] is False
    assert second["active_params_after"] == first["active_params_after"]


def test_history_log_records_every_attempt(tmp_path: Path, sample_ohlcv):
    loop, _ = _make_loop(tmp_path, sample_ohlcv)
    loop.maybe_improve()
    loop.maybe_improve()

    lines = loop.history_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


def test_safety_floor_blocks_promotion_when_set_too_high(tmp_path: Path, sample_ohlcv):
    trader = PaperTrader(
        symbol="BTC/USDT",
        strategy_cls=SMACrossoverStrategy,
        params={"fast_window": 10, "slow_window": 50},
        data_provider=lambda: sample_ohlcv,
        state_dir=tmp_path,
    )
    optimizer = WalkForwardOptimizer(engine=BacktestEngine(), n_splits=3)
    loop = SelfImprovementLoop(
        trader=trader,
        optimizer=optimizer,
        strategy_cls=SMACrossoverStrategy,
        history_provider=lambda: sample_ohlcv,
        state_dir=tmp_path,
        min_walk_forward_score=1e6,  # impossible to clear
    )
    record = loop.maybe_improve()
    assert record["promoted"] is False
    assert "safety floor" in record["reason"]
