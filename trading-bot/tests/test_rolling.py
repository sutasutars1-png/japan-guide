import numpy as np

from trading_bot.research.rolling import BASE_VARIANTS, apply_stop, majority, run_rolling

GRID = {"history_candles": [240, 360], "n_splits": [3], "min_trades": [2, 3], "score": ["sharpe"]}


def test_stop_goes_flat_until_the_signal_changes():
    close = np.array([100.0, 98.0, 94.0, 97.0, 99.0, 99.0, 99.0])
    target = np.array([1.0, 1.0, 1.0, 1.0, -1.0, -1.0, 1.0])
    # Long from 100; 94 is 6% against it -> flat (even though it recovers); a new
    # signal (short at 99) re-arms the stop, then a long signal again.
    assert apply_stop(target, close, 0.05).tolist() == [1.0, 1.0, 0.0, 0.0, -1.0, -1.0, 1.0]
    short = apply_stop(np.array([-1.0, -1.0, -1.0]), np.array([100.0, 104.0, 106.0]), 0.05)
    assert short.tolist() == [-1.0, -1.0, 0.0]


def test_majority_vote_keeps_positions_discrete():
    votes = majority([np.array([1.0, 1.0, -1.0, 0.0]), np.array([1.0, -1.0, -1.0, 0.0]), np.array([0.0, -1.0, 1.0, 1.0])])
    assert votes.tolist() == [1.0, -1.0, -1.0, 1.0]


def test_rolling_rechooses_before_each_window_and_chains_them(sample_ohlcv, tmp_path):
    report = run_rolling(sample_ohlcv, "sma_crossover_ls", window_days=5, min_selection_days=10, grid=GRID, workers=2,
                         cache_dir=tmp_path)
    n, warm, window = len(sample_ohlcv), 359, 120
    first = warm + 240
    assert report.start_timestamp == sample_ohlcv["timestamp"].iloc[first].isoformat()
    assert len(report.windows) == len([b for b in range(first, n, window) if n - b >= window // 2])
    assert set(report.chained) == {*BASE_VARIANTS, "auto", "static", "buy_hold"}
    for w in report.windows:
        assert w["auto_variant"] in BASE_VARIANTS
        assert w["settings_return"]["min"] <= w["settings_return"]["median"] <= w["settings_return"]["max"]
    # Chaining the windows reproduces the whole out-of-sample curve.
    for k in ("single", "buy_hold"):
        product = np.prod([1 + w["returns"][k] for w in report.windows]) - 1
        assert np.isclose(product, report.chained[k]["total_return"])

    # A second run reads the cached positions and reproduces the report.
    assert len(list(tmp_path.glob("*.npy"))) == 4
    again = run_rolling(sample_ohlcv, "sma_crossover_ls", window_days=5, min_selection_days=10, grid=GRID, workers=2,
                        cache_dir=tmp_path)
    assert again.chained == report.chained
