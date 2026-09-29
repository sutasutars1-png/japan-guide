import json
from pathlib import Path

from trading_bot.cli import main
from trading_bot.data.fetch import save_csv


def test_self_improve_csv_demo_never_optimizes_on_bars_the_trader_has_not_reached(tmp_path: Path, sample_ohlcv, capsys):
    csv = tmp_path / "ohlcv.csv"
    save_csv(sample_ohlcv, csv)
    main([
        "self-improve", "--csv", str(csv), "--state-dir", str(tmp_path / "state"),
        "--steps", "30", "--step-seconds", "0", "--reoptimize-every", "10",
        "--history-candles", "600", "--window", "300", "--n-splits", "3", "--min-trades", "3",
    ])
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    reopts = [i for i, e in enumerate(events) if e["event"] == "reoptimize"]
    assert len(reopts) == 3
    for i in reopts:
        # The optimizer's data ends exactly at the bar decided right after it.
        assert events[i]["data_end"] == events[i + 1]["timestamp"]


def test_self_improve_csv_demo_stops_at_end_of_file(tmp_path: Path, sample_ohlcv, capsys):
    csv = tmp_path / "ohlcv.csv"
    save_csv(sample_ohlcv.iloc[:620], csv)
    main([
        "self-improve", "--csv", str(csv), "--state-dir", str(tmp_path / "state"),
        "--steps", "0", "--step-seconds", "0", "--reoptimize-every", "100",
        "--history-candles", "600", "--window", "300", "--n-splits", "3", "--min-trades", "3",
    ])
    steps = [json.loads(line) for line in capsys.readouterr().out.splitlines() if '"event": "step"' in line]
    assert len(steps) == 21  # bars 600..620 inclusive of the first decidable one
    assert all(s["action"] != "no_new_bar" for s in steps)
