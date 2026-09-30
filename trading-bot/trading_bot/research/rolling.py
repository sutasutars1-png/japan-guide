"""Rolling choose-then-confirm: the `holdout` procedure repeated window after
window, so the self-improvement rules are judged on several unseen periods
instead of one.

For each confirmation window (e.g. 60 days), the rule setting is chosen using
only the bars *before* the window, then traded through it; the windows are
chained into one out-of-sample equity curve. This is how the system would have
done had the rules themselves been re-chosen every `window_days`.

Why one replay per setting is enough: a replay is causal (each cycle sees only
the bars before it), so a setting's decision at bar t is the same whether the
replay stops at t or runs to the end. Every setting is replayed once over the
whole history; each window's choice then only looks at the part before it.

The same machinery compares ways of making the result depend less on a single
rule setting (`VARIANTS`):
- "single": the setting with the best neighbour-averaged selection score
  (exactly what `holdout` picks);
- "vote3": majority vote of the top 3 settings' positions (-1/0/1), so one
  setting's bad streak is outvoted;
- "vote_all": majority vote of every setting — no choice of setting at all;
- "stopX": "single" with a stop: once a position is X% against its entry
  price, go flat until the signal changes side;
- "auto": in each window, whichever of the variants above did best on the
  bars before the window (so the choice of variant is out-of-sample too).
"""
from __future__ import annotations

import hashlib
import itertools
import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from ..backtest.engine import BacktestEngine
from ..optimize.optimizer import WalkForwardOptimizer
from ..self_improve.loop import GateConfig
from ..self_improve.replay import replay
from ..strategy import STRATEGIES
from .holdout import DEFAULT_GRID, SELECT_METRIC, _neighbours

STOP_LEVELS = (0.05, 0.10)
BASE_VARIANTS = ("single", "vote3", "vote_all", *(f"stop{int(s * 100)}" for s in STOP_LEVELS))


def apply_stop(target: np.ndarray, close: np.ndarray, stop: float) -> np.ndarray:
    """Go flat once a position is `stop` against the close at which its signal
    appeared; stay flat until the signal changes. Uses only closes up to each bar."""
    out = np.array(target, dtype=float)
    sig, entry, stopped = 0.0, 0.0, False
    for t in range(len(out)):
        s = out[t]
        if s != sig:
            sig, entry, stopped = s, close[t], False
        if sig and not stopped and sig * (close[t] / entry - 1.0) <= -stop:
            stopped = True
        if stopped:
            out[t] = 0.0
    return out


def majority(positions: list[np.ndarray]) -> np.ndarray:
    return np.sign(np.sum(positions, axis=0))


@dataclass
class _Spec:
    strategy: str
    setting: tuple
    reoptimize_every: int
    engine_kwargs: dict
    min_walk_forward_score: float
    min_improvement_margin: float
    eval_start: int


def _replay_positions(args: tuple[_Spec, pd.DataFrame]) -> list[float]:
    spec, df = args
    history, n_splits, min_trades, score = spec.setting
    cls = STRATEGIES[spec.strategy]
    result = replay(
        df, cls, dict(cls().params),
        WalkForwardOptimizer(BacktestEngine(**spec.engine_kwargs), n_splits=n_splits, min_trades=min_trades, score=score),
        GateConfig(spec.min_walk_forward_score, spec.min_improvement_margin),
        history_candles=history, reoptimize_every=spec.reoptimize_every, eval_start=spec.eval_start,
    )
    return result.system_position


@dataclass
class RollingReport:
    strategy: str
    window_bars: int
    start_timestamp: str
    windows: list[dict] = field(default_factory=list)
    chained: dict[str, dict] = field(default_factory=dict)
    equity: dict[str, list[float]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return self.__dict__


def run_rolling(
    df: pd.DataFrame,
    strategy: str,
    window_days: float = 60,
    min_selection_days: float = 120,
    grid: dict = DEFAULT_GRID,
    reoptimize_every: int = 24,
    fee_rate: float = 0.0002,
    slippage_rate: float = 0.0,
    order_type: str = "limit",
    carry_rate_per_day: float = 0.0004,
    min_walk_forward_score: float = 0.0,
    min_improvement_margin: float = 0.05,
    select_by: str = "return",
    workers: int = 4,
    timeframe: str = "1h",
    cache_dir: Optional[Path] = None,
) -> RollingReport:
    """`cache_dir` keeps each setting's replayed positions, keyed by everything
    that determines them (setting, costs, gate, and the exact bars), so
    re-analysing the same data skips the replays."""
    engine_kwargs = dict(fee_rate=fee_rate, slippage_rate=slippage_rate, order_type=order_type,
                         carry_rate_per_day=carry_rate_per_day)
    engine = BacktestEngine(**engine_kwargs)
    spot = BacktestEngine(**{**engine_kwargs, "carry_rate_per_day": 0.0})
    n = len(df)
    warm = max(grid["history_candles"]) - 1  # first bar every setting has made a decision on
    window = int(window_days * 24)
    first = warm + int(min_selection_days * 24)
    if first + window > n:
        raise ValueError("not enough data for one selection period and one confirmation window")
    bounds = list(range(first, n, window))
    bounds = [b for b in bounds if n - b >= window // 2]  # drop a tail shorter than half a window
    ends = bounds[1:] + [n]

    settings = list(itertools.product(*grid.values()))
    specs = [(_Spec(strategy, s, reoptimize_every, engine_kwargs, min_walk_forward_score, min_improvement_margin, warm), df)
             for s in settings]
    def cache_path(spec: _Spec) -> Optional[Path]:
        if cache_dir is None:
            return None
        key = json.dumps([asdict(spec), n, str(df["timestamp"].iloc[0]), str(df["timestamp"].iloc[-1]),
                          float(df["close"].sum())], default=str)
        return Path(cache_dir) / f"{strategy}_{hashlib.sha1(key.encode()).hexdigest()[:16]}.npy"

    positions = {}
    todo = []
    for spec, frame in specs:
        path = cache_path(spec)
        if path is not None and path.exists():
            positions[spec.setting] = np.load(path)
        else:
            todo.append((spec, frame))
    if todo:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for (spec, _), pos in zip(todo, pool.map(_replay_positions, todo)):
                positions[spec.setting] = np.array(pos)
                path = cache_path(spec)
                if path is not None:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    np.save(path, positions[spec.setting])
    positions = {s: positions[s] for s in settings}

    close = df["close"].to_numpy(dtype=float)
    static = np.nan_to_num(STRATEGIES[strategy]().generate_positions(df).to_numpy(dtype=float))
    metric = SELECT_METRIC[select_by]

    def score(pos: np.ndarray, a: int, b: int) -> dict:
        return engine.run_positions(df.iloc[a:b].reset_index(drop=True), pos[a:b], timeframe=timeframe).metrics

    vote_all = majority(list(positions.values()))

    def variants_for(ranked: list[tuple]) -> dict[str, np.ndarray]:
        best = positions[ranked[0]]
        out = {"single": best, "vote3": majority([positions[s] for s in ranked[:3]]), "vote_all": vote_all}
        for lvl in STOP_LEVELS:
            out[f"stop{int(lvl * 100)}"] = apply_stop(best, close, lvl)
        return out

    stitched = {v: np.zeros(n) for v in (*BASE_VARIANTS, "auto")}
    windows = []
    for a, b in zip(bounds, ends):
        # choose using only bars [warm, a): each setting's own continuous record
        value = {s: score(positions[s], warm, a)[metric] for s in settings}
        robust = {s: np.mean([value[x] for x in [s, *_neighbours(s, grid)]]) for s in settings}
        ranked = sorted(settings, key=lambda s: -robust[s])
        cand = variants_for(ranked)
        sel = {v: score(p, warm, a)[metric] for v, p in cand.items()}
        auto = max(BASE_VARIANTS, key=lambda v: sel[v])
        for v, p in cand.items():
            stitched[v][a:b] = p[a:b]
        stitched["auto"][a:b] = cand[auto][a:b]
        each = sorted(score(positions[s], a, b)["total_return"] for s in settings)
        windows.append({
            "start": df["timestamp"].iloc[a].isoformat(),
            "end": df["timestamp"].iloc[b - 1].isoformat(),
            "chosen": dict(zip(grid.keys(), ranked[0])),
            "top3": [dict(zip(grid.keys(), s)) for s in ranked[:3]],
            "auto_variant": auto,
            "selection": {v: sel[v] for v in BASE_VARIANTS},
            "settings_return": {"min": each[0], "median": float(np.median(each)), "max": each[-1]},
        })

    a0 = bounds[0]
    scored = df.iloc[a0:].reset_index(drop=True)
    runs = {v: engine.run_positions(scored, p[a0:], timeframe=timeframe) for v, p in stitched.items()}
    runs["static"] = engine.run_positions(scored, static[a0:], timeframe=timeframe)
    runs["buy_hold"] = spot.run_positions(scored, np.ones(n - a0), timeframe=timeframe)
    for w, a, b in zip(windows, bounds, ends):
        w["returns"] = {k: float(r.equity_curve.iloc[b - a0 - 1] / (r.equity_curve.iloc[a - a0 - 1] if a > a0 else r.equity_curve.iloc[0]) - 1)
                        for k, r in runs.items()}
    return RollingReport(
        strategy=strategy,
        window_bars=window,
        start_timestamp=df["timestamp"].iloc[a0].isoformat(),
        windows=windows,
        chained={k: r.metrics for k, r in runs.items()},
        equity={k: [float(x) for x in r.equity_curve.to_numpy()] for k, r in runs.items()},
    )
