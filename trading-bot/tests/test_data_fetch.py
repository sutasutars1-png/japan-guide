from pathlib import Path

import pytest

from trading_bot.data.fetch import load_csv, save_csv


def test_save_and_load_csv_round_trip(tmp_path: Path, sample_ohlcv):
    path = tmp_path / "ohlcv.csv"
    save_csv(sample_ohlcv, path)
    loaded = load_csv(path)

    assert list(loaded.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert len(loaded) == len(sample_ohlcv)
    assert loaded["close"].iloc[0] == pytest.approx(sample_ohlcv["close"].iloc[0])


def test_load_csv_rejects_missing_columns(tmp_path: Path):
    path = tmp_path / "bad.csv"
    path.write_text("timestamp,open,close\n1,2,3\n", encoding="utf-8")
    import pytest

    with pytest.raises(ValueError):
        load_csv(path)
