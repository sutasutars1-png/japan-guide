from pathlib import Path

import pytest

from trading_bot.backtest.engine import BacktestEngine
from trading_bot.optimize.optimizer import OptimizationResult, WalkForwardOptimizer
from trading_bot.paper.trader import PaperTrader
from trading_bot.self_improve.loop import GateConfig, SelfImprovementLoop, decide
from trading_bot.self_improve.replay import replay
from trading_bot.strategy.moving_average import SMACrossoverStrategy

A = {"fast_window": 10, "slow_window": 50}
B = {"fast_window": 5, "slow_window": 30}


def _result(params, wf):
    return OptimizationResult(strategy_name="sma_crossover", final_params=params, final_score=1.0, walk_forward_score=wf)


@pytest.mark.parametrize(
    "result, incumbent_score, code",
    [
        (_result(None, float("-inf")), 0.0, "no_viable"),
        (_result(B, -0.5), float("-inf"), "below_floor"),
        (_result(A, 2.0), 0.0, "same_as_active"),
        (_result(B, 1.02), 1.0, "insufficient_margin"),
        (_result(B, 1.10), 1.0, "promoted"),
        (_result(B, 0.10), float("-inf"), "promoted"),
    ],
)
def test_decide_gates(result, incumbent_score, code):
    decision = decide(result, A, incumbent_score, GateConfig(min_walk_forward_score=0.0, min_improvement_margin=0.05))
    assert decision.reason_code == code
    assert decision.promoted is (code == "promoted")


def _optimizer():
    return WalkForwardOptimizer(engine=BacktestEngine(), n_splits=3, min_trades=3)


def test_replay_never_looks_ahead(sample_ohlcv):
    """Cycles decided before bar k must be identical whether or not bars after k exist."""
    kwargs = dict(
        strategy_cls=SMACrossoverStrategy,
        initial_params=A,
        optimizer=_optimizer(),
        gate=GateConfig(),
        history_candles=300,
        reoptimize_every=100,
    )
    full = replay(sample_ohlcv, **kwargs)
    cut = 800
    truncated = replay(sample_ohlcv.iloc[:cut].reset_index(drop=True), **kwargs)

    early_full = [c for c in full.cycles if c["bar_index"] < cut]
    assert early_full == truncated.cycles
    assert full.active_by_bar[:cut] == truncated.active_by_bar


def test_replay_static_and_buy_hold_baselines(sample_ohlcv):
    engine = BacktestEngine()
    res = replay(
        sample_ohlcv,
        SMACrossoverStrategy,
        A,
        WalkForwardOptimizer(engine=engine, n_splits=3, min_trades=3),
        GateConfig(),
        history_candles=300,
        reoptimize_every=100,
    )
    static = engine.run(sample_ohlcv, SMACrossoverStrategy(**A))
    assert res.metrics["static"]["final_equity"] == pytest.approx(static.metrics["final_equity"])
    assert set(res.equity) == {"self_improving", "static", "buy_hold"}
    assert all(len(v) == len(sample_ohlcv) for v in res.equity.values())
    # First cycle runs once `history_candles` bars exist, then every `reoptimize_every`.
    assert [c["bar_index"] for c in res.cycles][:3] == [299, 399, 499]
    # Before any promotion the system trades the starting params, so it tracks the static run.
    first_promo = next((c["bar_index"] for c in res.cycles if c["promoted"]), len(sample_ohlcv) - 1)
    assert res.equity["self_improving"][first_promo] == pytest.approx(res.equity["static"][first_promo])


def test_fold_scoring_warms_up_indicators(sample_ohlcv):
    """A slow SMA evaluated on a short fold must not sit flat for its whole warm-up."""
    opt = WalkForwardOptimizer(n_splits=3)
    params = {"fast_window": 20, "slow_window": 200}
    warmed = opt._run_fold(sample_ohlcv, SMACrossoverStrategy, params, 400, 600, "1h")
    cold = opt.engine.run(sample_ohlcv.iloc[400:600].reset_index(drop=True), SMACrossoverStrategy(**params))
    assert warmed.position.iloc[1:].sum() > cold.position.sum()


def test_run_schedule_trades_every_bar_and_reoptimizes_on_schedule(tmp_path: Path, sample_ohlcv):
    trader = PaperTrader(
        symbol="BTC/USDT",
        strategy_cls=SMACrossoverStrategy,
        params=A,
        data_provider=lambda: sample_ohlcv,
        state_dir=tmp_path,
    )
    loop = SelfImprovementLoop(
        trader=trader,
        optimizer=_optimizer(),
        strategy_cls=SMACrossoverStrategy,
        history_provider=lambda: sample_ohlcv,
        state_dir=tmp_path,
    )
    events = [e["event"] for e in loop.run_schedule(steps=5, step_seconds=0, reoptimize_every=2)]
    assert events == ["reoptimize", "step", "step", "reoptimize", "step", "step", "reoptimize", "step"]


def test_restart_resumes_promoted_params(tmp_path: Path, sample_ohlcv):
    def make():
        trader = PaperTrader(
            symbol="BTC/USDT",
            strategy_cls=SMACrossoverStrategy,
            params=A,
            data_provider=lambda: sample_ohlcv,
            state_dir=tmp_path,
        )
        loop = SelfImprovementLoop(
            trader=trader,
            optimizer=_optimizer(),
            strategy_cls=SMACrossoverStrategy,
            history_provider=lambda: sample_ohlcv,
            state_dir=tmp_path,
            min_walk_forward_score=-100.0,
        )
        return loop, trader

    loop, _ = make()
    record = loop.maybe_improve()
    assert record["promoted"] is True

    _, restarted_trader = make()
    assert restarted_trader.strategy.params == record["active_params_after"]
