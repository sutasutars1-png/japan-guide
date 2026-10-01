import json
from pathlib import Path

import numpy as np

from trading_bot.cli import main
from trading_bot.data.fetch import save_csv
from trading_bot.self_improve.committee import VoteStrategy
from trading_bot.strategy import STRATEGIES

LS = STRATEGIES["sma_crossover_ls"]


def test_vote_is_the_sign_of_the_members_sum(sample_ohlcv):
    members = {"a": LS(fast_window=5, slow_window=30), "b": LS(fast_window=10, slow_window=50),
               "c": LS(fast_window=20, slow_window=100, band=0.01)}
    vote = VoteStrategy(members).generate_positions(sample_ohlcv).to_numpy()
    each = [m.generate_positions(sample_ohlcv).to_numpy() for m in members.values()]
    assert np.array_equal(vote, np.sign(np.sum(each, axis=0)))
    assert set(np.unique(vote)) <= {-1.0, 0.0, 1.0}


def test_committee_self_improve_trades_the_members_vote_and_resumes(tmp_path: Path, sample_ohlcv, capsys, monkeypatch):
    import trading_bot.research.holdout as holdout

    monkeypatch.setattr(holdout, "DEFAULT_GRID", {"history_candles": [240, 360], "n_splits": [3], "min_trades": [2, 3],
                                                  "score": ["sharpe"]})
    csv, state = tmp_path / "ohlcv.csv", tmp_path / "state"
    save_csv(sample_ohlcv, csv)
    args = ["self-improve", "--csv", str(csv), "--state-dir", str(state), "--committee", "--steps", "30",
            "--step-seconds", "0", "--reoptimize-every", "10", "--window", "300"]
    main(args)
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    reopts = [e for e in events if e["event"] == "reoptimize"]
    assert len(reopts) == 3 and all(e["members"] == 4 for e in reopts)

    members = json.loads((state / "active_params_sma_crossover_ls_committee.json").read_text())["members"]
    assert sorted(members) == ["240/3/2/sharpe", "240/3/3/sharpe", "360/3/2/sharpe", "360/3/3/sharpe"]
    history = [json.loads(line) for line in (state / "optimization_history_sma_crossover_ls.jsonl").read_text().splitlines()]
    assert len(history) == 3 * 4 and {h["member"] for h in history} == set(members)

    # The last decision is the vote of the members' active params on the bars the trader saw.
    last = [e for e in events if e["event"] == "step"][-1]
    seen = sample_ohlcv[sample_ohlcv["timestamp"] <= last["timestamp"]].tail(300).reset_index(drop=True)
    vote = VoteStrategy({t: LS(**m["params"]) for t, m in members.items()}).generate_positions(seen)
    assert last["desired_position"] == vote.iloc[-1]
    run_config = json.loads((state / "run_config.json").read_text())
    assert run_config["committee"] and run_config["params"] == {"fast_window": 10, "slow_window": 50, "band": 0.0}
