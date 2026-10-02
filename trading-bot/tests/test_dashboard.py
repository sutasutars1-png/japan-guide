import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

from trading_bot.backtest.engine import BacktestEngine
from trading_bot.optimize.optimizer import WalkForwardOptimizer
from trading_bot.self_improve.loop import GateConfig
from trading_bot.self_improve.replay import replay
from trading_bot.strategy import STRATEGIES

ENGINE_JS = Path(__file__).resolve().parents[1] / "trading_bot" / "dashboard" / "engine.js"

RUNNER = """
const SIL = require(process.argv[2]);
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const r = SIL.replay(input.bars, input.cfg);
const fin = v => (Number.isFinite(v) ? v : null);
process.stdout.write(JSON.stringify({
  cycles: r.cycles.map(c => ({bar: c.barIndex, code: c.code, candidate: c.candidate, wf: fin(c.candidateWf), inc: fin(c.incumbentScore)})),
  final: Object.fromEntries(Object.entries(r.runs).map(([k, v]) => [k, v.metrics.final_equity])),
  trades: Object.fromEntries(Object.entries(r.runs).map(([k, v]) => [k, v.metrics.num_trades])),
}));
"""


MARKET = {"fee": 0.001, "slip": 0.0005, "order_type": "market", "carry": 0.0, "score": "sharpe", "eval_start": 0}
LIMIT = {"fee": 0.0002, "slip": 0.0, "order_type": "limit", "carry": 0.0004, "score": "return", "eval_start": 600}


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.parametrize("strategy,costs", [
    ("sma_crossover", MARKET), ("donchian_breakout", MARKET), ("rsi_reversion", MARKET), ("multi", MARKET),
    ("sma_crossover_ls", LIMIT), ("donchian_breakout_ls", LIMIT), ("rsi_reversion_ls", LIMIT), ("multi_ls", LIMIT),
    ("sma_crossover_ls", MARKET),
])
def test_dashboard_engine_matches_python_replay(strategy, costs, sample_ohlcv, tmp_path: Path):
    df = sample_ohlcv.iloc[:1000].reset_index(drop=True)
    cls = STRATEGIES[strategy]
    initial = dict(cls().params)
    # A loose gate so every outcome (promotion, same, margin, floor) actually occurs.
    hist, every, splits, min_trades, floor = 360, 24, 3, 1, -5.0
    engine = BacktestEngine(fee_rate=costs["fee"], slippage_rate=costs["slip"], order_type=costs["order_type"],
                            carry_rate_per_day=costs["carry"])
    py = replay(df, cls, initial, WalkForwardOptimizer(engine, n_splits=splits, min_trades=min_trades, score=costs["score"]),
                GateConfig(floor, 0.05), history_candles=hist, reoptimize_every=every, eval_start=costs["eval_start"])

    runner = tmp_path / "run.js"
    runner.write_text(RUNNER)
    payload = {
        "bars": {"c": df["close"].tolist(), "h": df["high"].tolist(), "l": df["low"].tolist(),
                 "t": [int(t.timestamp() * 1000) for t in df["timestamp"]]},
        "cfg": {"strategy": strategy, "initialParams": initial, "history": hist, "every": every, "nSplits": splits,
                "minTrades": min_trades, "score": costs["score"], "minWf": floor, "margin": 0.05,
                "cost": costs["fee"] + costs["slip"], "cash": 10000, "orderType": costs["order_type"],
                "carryPerDay": costs["carry"], "evalStart": costs["eval_start"]},
    }
    out = subprocess.run(["node", str(runner), str(ENGINE_JS)], input=json.dumps(payload), capture_output=True,
                         text=True, check=True)
    js = json.loads(out.stdout)

    assert sum(c["promoted"] for c in py.cycles) >= 1
    assert len(js["cycles"]) == len(py.cycles)
    for j, p in zip(js["cycles"], py.cycles):
        assert j["bar"] == p["bar_index"]
        assert j["code"] == p["reason_code"]
        assert j["candidate"] == p["candidate_params"]
        for a, b in ((j["wf"], p["candidate_walk_forward_score"]), (j["inc"], p["incumbent_score"])):
            assert (a is None and b is None) or math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
    for k in ("self_improving", "static", "buy_hold"):
        assert math.isclose(js["final"][k], py.metrics[k]["final_equity"], rel_tol=1e-9)
        assert js["trades"][k] == py.metrics[k]["num_trades"]


def _embedded(html: str, script_id: str):
    start = html.index(f'<script id="{script_id}" type="application/json">') + len(f'<script id="{script_id}" type="application/json">')
    return json.loads(html[start: html.index("</script>", start)])


def test_build_dashboard_embeds_store_and_live_state(sample_ohlcv, tmp_path: Path, capsys):
    from trading_bot.cli import main
    from trading_bot.data.store import OHLCVStore

    store = OHLCVStore(tmp_path / "cache", "kraken", "BTC/USD", "1h")
    store.merge(sample_ohlcv.iloc[:700], "trades")
    store.merge(sample_ohlcv.iloc[700:], "exchange_ohlc")
    state = tmp_path / "state"
    out = tmp_path / "dash.html"
    main(["self-improve", "--csv", str(store.path), "--state-dir", str(state), "--steps", "30", "--step-seconds", "0",
          "--reoptimize-every", "10", "--history-candles", "600", "--n-splits", "3", "--min-trades", "3",
          "--strategy", "sma_crossover", "--params", "fast_window=5,slow_window=30", "--dashboard-out", str(out)])
    capsys.readouterr()

    html = out.read_text(encoding="utf-8")
    assert "__CANDLE_JSON__" not in html and "__ENGINE_JS__" not in html
    candles = _embedded(html, "candle-data")
    assert len(candles) == len(sample_ohlcv)
    assert {c[6] for c in candles} == {0, 1}  # official and trade-rebuilt bars are told apart
    live = _embedded(html, "live-data")
    assert len(live["decisions"]) == 30 and len(live["cycles"]) == 3
    assert live["run_config"]["params"] == {"fast_window": 5, "slow_window": 30}
    config = _embedded(html, "config-data")
    assert config["defaults"]["start"] == {"fast_window": 5, "slow_window": 30}
    assert config["defaults"]["history"] == 600


def test_params_accept_json_or_shell_friendly_pairs():
    from trading_bot.cli import _parse_params

    assert _parse_params('{"fast_window": 10}') == {"fast_window": 10}
    assert _parse_params("strategy=rsi_reversion,period=14,lower=25,upper=60.5") == {
        "strategy": "rsi_reversion", "period": 14, "lower": 25, "upper": 60.5}


def test_dashboard_embeds_a_rolling_report_when_present(sample_ohlcv, tmp_path: Path):
    from trading_bot.dashboard.build import build_dashboard
    from trading_bot.data.store import OHLCVStore
    from trading_bot.research.rolling import run_rolling

    store = OHLCVStore(tmp_path / "cache", "kraken", "BTC/USD", "1h")
    store.merge(sample_ohlcv, "exchange_ohlc")
    grid = {"history_candles": [240, 360], "n_splits": [3], "min_trades": [2, 3], "score": ["sharpe"]}
    report = run_rolling(sample_ohlcv, "sma_crossover_ls", window_days=5, min_selection_days=10, grid=grid, workers=2)
    state = tmp_path / "state"
    state.mkdir()
    (state / "rolling.json").write_text(json.dumps(report.to_dict(), default=str))
    html = build_dashboard(store, tmp_path / "d.html", state).read_text(encoding="utf-8")
    roll = _embedded(html, "rolling-data")
    assert len(roll["windows"]) == len(report.windows)
    assert roll["chained"]["vote_all"]["total_return"] == report.chained["vote_all"]["total_return"]
    assert len(roll["equity"]["vote_all"]) == len(report.equity["vote_all"])
    # Without a report the panel is simply absent.
    assert _embedded(build_dashboard(store, tmp_path / "e.html", tmp_path / "none").read_text(encoding="utf-8"),
                     "rolling-data") is None
