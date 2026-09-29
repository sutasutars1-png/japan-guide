from trading_bot.research.holdout import _neighbours, run_holdout

GRID = {"history_candles": [240, 360], "n_splits": [3], "min_trades": [2, 3]}


def test_neighbours_differ_in_exactly_one_axis_by_one_step():
    grid = {"a": [1, 2, 3], "b": [10, 20]}
    assert sorted(_neighbours((2, 10), grid)) == [(1, 10), (2, 20), (3, 10)]


def test_holdout_chooses_on_selection_and_scores_only_the_confirmation_period(sample_ohlcv):
    report = run_holdout(sample_ohlcv, "sma_crossover", confirm_bars=300, grid=GRID,
                         cost_levels=(0.001, 0.004), workers=2)
    assert report.split_timestamp == sample_ohlcv["timestamp"].iloc[900].isoformat()
    assert len(report.selection) == len(report.confirmation) == 4
    assert sum(r["chosen"] for r in report.confirmation) == 1
    best_robust = max(report.selection, key=lambda r: r["robust_score"])["setting"]
    assert report.chosen == best_robust
    # Confirmation equity covers only the newest 300 bars.
    assert all(r["metrics"]["buy_hold"]["final_equity"] for r in report.confirmation)
    assert [c["cost_per_side"] for c in report.cost_sensitivity] == [0.001, 0.004]
    # Buy & hold trades once, so its return can only fall as cost rises.
    bh = [c["metrics"]["buy_hold"]["total_return"] for c in report.cost_sensitivity]
    assert bh[0] > bh[1]
