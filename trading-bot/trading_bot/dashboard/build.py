"""Build the self-contained dashboard HTML (SMA Cross Lab) from the candle
store and, when present, the running bot's state files.

The page embeds everything it needs (candles, the live bot's decisions and
re-optimization log, and the browser port of the replay engine), so the
output is a single file that opens offline or can be published as-is.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from ..data.store import OHLCVStore

HERE = Path(__file__).resolve().parent
SOURCE_CODES = {"exchange_ohlc": 0, "exchange_csv": 0, "trades": 1, "gap_fill": 2}
_EPOCH = pd.Timestamp("1970-01-01", tz="UTC")


def _ms(ts) -> int:
    return int((pd.Timestamp(ts) - _EPOCH) // pd.Timedelta(milliseconds=1))


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _finite(x):
    return x if isinstance(x, (int, float)) and x not in (float("inf"), float("-inf")) and x == x else None


def load_live_state(state_dir: Path, symbol: str, strategy: Optional[str] = None) -> Optional[dict]:
    """The running bot's paper-trading record, or None if it has never run."""
    state_dir = Path(state_dir)
    safe = symbol.replace("/", "-")
    decisions = [d for d in _jsonl(state_dir / f"decisions_{safe}.jsonl") if d.get("action") != "no_new_bar"]
    if not decisions:
        return None
    run_config = _read_json(state_dir / "run_config.json")
    if strategy is None:
        strategy = (run_config or {}).get("strategy")
    if strategy is None:
        histories = sorted(state_dir.glob("optimization_history_*.jsonl"), key=lambda p: p.stat().st_mtime)
        strategy = histories[-1].stem.removeprefix("optimization_history_") if histories else "sma_crossover"
    cycles = _jsonl(state_dir / f"optimization_history_{strategy}.jsonl")
    active = _read_json(state_dir / f"active_params_{strategy}.json")
    portfolio = _read_json(state_dir / f"portfolio_{safe}.json") or {}
    return {
        "strategy": strategy,
        "decisions": [[_ms(d["timestamp"]), d["price"], d["equity"], d["desired_position"], d["action"]] for d in decisions],
        "cycles": [
            {
                "t": _ms(c.get("data_end") or c["timestamp"]),
                "promoted": c["promoted"],
                "code": c.get("reason_code"),
                "candidate": c.get("candidate_final_params"),
                "wf": _finite(c.get("candidate_walk_forward_score")),
                "inc": _finite(c.get("incumbent_score")),
            }
            for c in cycles
        ],
        "active": (active or {}).get("params"),
        "portfolio": {"cash": portfolio.get("cash"), "qty": portfolio.get("qty", portfolio.get("position_qty")),
                      "realized_pnl": portfolio.get("realized_pnl")},
        "run_config": run_config,
    }


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


ROLLING_KEYS = ("vote_all", "single", "static", "buy_hold")


def load_rolling(path: Optional[Path]) -> Optional[dict]:
    """The latest `rolling --export-json` report, trimmed to what the page shows."""
    if path is None or not Path(path).exists():
        return None
    r = json.loads(Path(path).read_text(encoding="utf-8"))
    keys = [k for k in ROLLING_KEYS if k in r["chained"]]
    tag = lambda c: f"{c['history_candles']}/{c['n_splits']}/{c['min_trades']}/{c['score']}"
    return {
        "strategy": r["strategy"],
        "start": _ms(r["start_timestamp"]),
        "window_bars": r["window_bars"],
        "windows": [{"start": _ms(w["start"]), "end": _ms(w["end"]), "chosen": tag(w["chosen"]),
                     "returns": {k: w["returns"][k] for k in keys}} for w in r["windows"]],
        "chained": {k: {m: r["chained"][k][m] for m in ("total_return", "sharpe", "max_drawdown", "num_trades")}
                    for k in keys},
        "equity": {k: [round(v, 1) for v in r["equity"][k]] for k in keys},
    }


def page_defaults(run_config: Optional[dict]) -> dict:
    """Start the page on the live bot's own rules, so its replay is comparable."""
    if not run_config:
        return {}
    keys = {
        "strategy": "strategy", "history_candles": "history", "reoptimize_every": "every", "n_splits": "nSplits",
        "min_trades": "minTrades", "min_walk_forward_score": "minWf", "min_improvement_margin": "margin",
        "score": "score", "order_type": "orderType",
    }
    out = {page: run_config[k] for k, page in keys.items() if k in run_config}
    if "fee_rate" in run_config:
        out["fee"] = run_config["fee_rate"] * 100
    if "slippage_rate" in run_config:
        out["slip"] = run_config["slippage_rate"] * 100
    if "carry_rate_per_day" in run_config:
        out["carry"] = run_config["carry_rate_per_day"] * 100
    if run_config.get("params"):
        out["start"] = run_config["params"]
    return out


def _embed(obj) -> str:
    # "</" inside a <script> block would end it early.
    return json.dumps(obj, separators=(",", ":"), default=str).replace("</", "<\\/")


def build_dashboard(
    store: OHLCVStore,
    out_path: Path,
    state_dir: Optional[Path] = None,
    exchange: str = "kraken",
    symbol: str = "BTC/USD",
    strategy: Optional[str] = None,
    rolling_path: Optional[Path] = None,
) -> Path:
    df = store.load()
    if df.empty:
        raise ValueError(f"the store {store.path} is empty; run `bootstrap` or `fetch-data` first")
    candles = [
        [_ms(r.timestamp), round(r.open, 2), round(r.high, 2), round(r.low, 2), round(r.close, 2), round(r.volume, 4),
         SOURCE_CODES[r.source]]
        for r in df.itertuples()
    ]
    live = load_live_state(state_dir, symbol, strategy) if state_dir else None
    config = {
        "defaults": page_defaults((live or {}).get("run_config")),
        "built_at": datetime.now(timezone.utc).isoformat(),
        "exchange": exchange,
        "symbol": symbol,
    }
    html = (HERE / "template.html").read_text(encoding="utf-8")
    html = (
        html.replace("__CANDLE_JSON__", _embed(candles))
        .replace("__LIVE_JSON__", _embed(live))
        .replace("__CONFIG_JSON__", _embed(config))
        .replace("__ROLLING_JSON__", _embed(load_rolling(rolling_path or (Path(state_dir) / "rolling.json" if state_dir else None))))
        .replace("__ENGINE_JS__", (HERE / "engine.js").read_text(encoding="utf-8"))
    )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(html, encoding="utf-8")
    tmp.replace(out_path)
    return out_path
