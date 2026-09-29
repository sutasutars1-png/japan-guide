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


from trading_bot.optimize.optimizer import OptimizationResult  # noqa: E402
from trading_bot.self_improve.loop import GateConfig, decide  # noqa: E402
from trading_bot.strategy import STRATEGIES  # noqa: E402
from trading_bot.strategy.more import (  # noqa: E402
    DonchianBreakoutStrategy,
    MultiStrategy,
    RSIReversionStrategy,
)

NEW = [
    DonchianBreakoutStrategy(entry_window=48, exit_window=24),
    RSIReversionStrategy(period=14, lower=30, upper=60),
    MultiStrategy(strategy="donchian_breakout", entry_window=24, exit_window=12),
]


@pytest.mark.parametrize("strategy", NEW, ids=lambda s: s.name)
def test_new_strategies_are_binary_trade_and_never_look_ahead(strategy, sample_ohlcv):
    full = strategy.generate_positions(sample_ohlcv)
    assert set(full.unique().tolist()) <= {0.0, 1.0}
    assert full.diff().abs().sum() >= 4  # it actually trades on the sample
    for cut in (300, 700, 1000):
        partial = strategy.generate_positions(sample_ohlcv.iloc[:cut])
        assert (partial.to_numpy() == full.iloc[:cut].to_numpy()).all()


def test_invalid_params_rejected():
    with pytest.raises(ValueError):
        DonchianBreakoutStrategy(entry_window=24, exit_window=48)
    with pytest.raises(ValueError):
        RSIReversionStrategy(lower=60, upper=50)
    with pytest.raises(ValueError):
        MultiStrategy(strategy="nope")


def test_multi_spans_every_member_and_round_trips_its_params(sample_ohlcv):
    combos = list(MultiStrategy.param_combinations())
    assert len(combos) == 15 + 11 + 9
    assert {c["strategy"] for c in combos} == {"sma_crossover", "donchian_breakout", "rsi_reversion"}
    for combo in combos:
        rebuilt = MultiStrategy(**combo)
        assert rebuilt.params == combo  # what the optimizer promotes is what the trader rebuilds
    member = STRATEGIES["rsi_reversion"](period=14, lower=25, upper=70)
    multi = MultiStrategy(strategy="rsi_reversion", period=14, lower=25, upper=70)
    assert (member.generate_positions(sample_ohlcv) == multi.generate_positions(sample_ohlcv)).all()


def test_gate_margin_grows_with_candidate_count():
    gate = GateConfig(min_walk_forward_score=0.0, min_improvement_margin=0.1)
    assert gate.margin_for(15) == pytest.approx(0.1)
    assert gate.margin_for(60) == pytest.approx(0.2)
    few = OptimizationResult("multi", {"strategy": "rsi_reversion"}, 1.0, 1.15, n_candidates=15)
    many = OptimizationResult("multi", {"strategy": "rsi_reversion"}, 1.0, 1.15, n_candidates=60)
    incumbent = {"strategy": "sma_crossover"}
    assert decide(few, incumbent, 1.0, gate).promoted is True
    assert decide(many, incumbent, 1.0, gate).reason_code == "insufficient_margin"
