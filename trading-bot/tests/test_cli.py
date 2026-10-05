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


def _small_grid(monkeypatch):
    import trading_bot.research.holdout as holdout

    monkeypatch.setattr(holdout, "DEFAULT_GRID", {"history_candles": [240, 360], "n_splits": [3], "min_trades": [2, 3],
                                                  "score": ["sharpe"]})


def test_holdout_and_rolling_commands_run_end_to_end(tmp_path: Path, sample_ohlcv, capsys, monkeypatch):
    _small_grid(monkeypatch)
    csv = tmp_path / "ohlcv.csv"
    save_csv(sample_ohlcv, csv)
    main(["holdout", "--csv", str(csv), "--confirm-days", "10", "--scores", "sharpe", "--workers", "2",
          "--export-json", str(tmp_path / "h.json")])
    assert json.loads((tmp_path / "h.json").read_text())["strategy"] == "sma_crossover_ls"
    cache = tmp_path / "cache"
    main(["rolling", "--csv", str(csv), "--window-days", "5", "--min-selection-days", "10", "--scores", "sharpe",
          "--workers", "2", "--cache-positions", str(cache), "--export-json", str(tmp_path / "r.json")])
    assert len(list(cache.glob("*.npy"))) == 4  # positions are reused by the next run
    assert "chained" in capsys.readouterr().out


def test_health_alerts_once_when_decisions_stop_and_once_when_they_resume(tmp_path: Path, capsys):
    import argparse

    import pandas as pd

    from trading_bot.cli import cmd_health

    state = tmp_path / "state"
    state.mkdir()
    log = state / "decisions_BTC-USD.jsonl"
    sent = []
    args = argparse.Namespace(symbol="BTC-USD", state_dir=str(state), max_silence_hours=2.0, webhook_url="https://hook")
    t0 = pd.Timestamp("2026-10-01T00:00:00Z").timestamp()

    def check(hours_after_bar_open):
        return cmd_health(args, now=t0 + hours_after_bar_open * 3600, notify=lambda url, msg: sent.append(msg))

    assert check(1) == 1 and len(sent) == 1 and "止まって" in sent[0]  # no log at all yet
    log.write_text(json.dumps({"timestamp": "2026-10-01T00:00:00+00:00", "action": "hold"}) + "\n")
    assert check(2.5) == 0 and len(sent) == 2 and "再開" in sent[1]    # decided; 1.5h since the bar closed
    assert check(3.5) == 1 and len(sent) == 3                           # 2.5h silent: alert
    assert check(5) == 1 and len(sent) == 3                             # still down: no repeat
    with open(log, "a") as f:                                           # no_new_bar wake-ups don't count
        f.write(json.dumps({"timestamp": "2026-10-01T00:00:00+00:00", "action": "no_new_bar"}) + "\n")
    assert check(5.5) == 1 and len(sent) == 3
    capsys.readouterr()
