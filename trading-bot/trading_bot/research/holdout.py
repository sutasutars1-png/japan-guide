"""Choose-then-confirm validation of the self-improvement *rules*.

Replay results swing a lot with the rule settings (training window, folds,
minimum trades), so picking the best-looking setting on the same data it is
reported on overstates it. This module separates the two:

1. Selection period (older data): replay every rule setting in a grid and
   score each by the self-improving system's return (or Sharpe). Pick by *stability* —
   the mean score of a setting and its grid neighbours — not the single best.
2. Confirmation period (the newest `confirm_bars`): replay the chosen setting,
   scoring only those bars. Cycles still learn from everything before each bar,
   exactly as live, but none of these bars influenced the choice.

Every setting is also reported on the confirmation period, so where the
chosen one lands among them is visible rather than hidden.
"""
from __future__ import annotations

import itertools
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field

import pandas as pd

from ..backtest.engine import BacktestEngine
from ..optimize.optimizer import WalkForwardOptimizer
from ..self_improve.loop import GateConfig
from ..self_improve.replay import replay
from ..strategy import STRATEGIES

DEFAULT_GRID = {"history_candles": [720, 1440, 2160], "n_splits": [3, 4], "min_trades": [3, 5], "score": ["sharpe", "return"]}
SETTING_KEYS = ("history_candles", "n_splits", "min_trades", "score")
SELECT_METRIC = {"sharpe": "sharpe", "return": "total_return"}


@dataclass
class RunSpec:
    strategy: str
    initial_params: dict
    history_candles: int
    n_splits: int
    min_trades: int
    score: str
    reoptimize_every: int
    fee_rate: float
    slippage_rate: float
    order_type: str
    carry_rate_per_day: float
    min_walk_forward_score: float
    min_improvement_margin: float
    eval_start: int

    def setting(self) -> tuple:
        return (self.history_candles, self.n_splits, self.min_trades, self.score)


def _run(args: tuple[RunSpec, pd.DataFrame]) -> dict:
    spec, df = args
    engine = BacktestEngine(fee_rate=spec.fee_rate, slippage_rate=spec.slippage_rate, order_type=spec.order_type,
                            carry_rate_per_day=spec.carry_rate_per_day)
    result = replay(
        df,
        STRATEGIES[spec.strategy],
        spec.initial_params,
        WalkForwardOptimizer(engine, n_splits=spec.n_splits, min_trades=spec.min_trades, score=spec.score),
        GateConfig(spec.min_walk_forward_score, spec.min_improvement_margin),
        history_candles=spec.history_candles,
        reoptimize_every=spec.reoptimize_every,
        eval_start=spec.eval_start,
    )
    return {
        "setting": dict(zip(SETTING_KEYS, spec.setting())),
        "cost_per_side": spec.fee_rate + spec.slippage_rate,
        "cycles": len(result.cycles),
        "promotions": sum(c["promoted"] for c in result.cycles),
        "metrics": result.metrics,
    }


def _neighbours(setting: tuple, grid: dict) -> list[tuple]:
    axes = list(grid.values())
    out = []
    for dim, values in enumerate(axes):
        i = values.index(setting[dim])
        for j in (i - 1, i + 1):
            if 0 <= j < len(values):
                n = list(setting)
                n[dim] = values[j]
                out.append(tuple(n))
    return out


@dataclass
class HoldoutReport:
    strategy: str
    split_timestamp: str
    selection: list[dict] = field(default_factory=list)
    chosen: dict = field(default_factory=dict)
    confirmation: list[dict] = field(default_factory=list)
    cost_sensitivity: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__


def run_holdout(
    df: pd.DataFrame,
    strategy: str,
    confirm_bars: int,
    grid: dict = DEFAULT_GRID,
    reoptimize_every: int = 24,
    fee_rate: float = 0.0002,
    slippage_rate: float = 0.0,
    order_type: str = "limit",
    carry_rate_per_day: float = 0.0004,
    min_walk_forward_score: float = 0.0,
    min_improvement_margin: float = 0.05,
    cost_levels: tuple[float, ...] = (0.0, 0.0002, 0.0005, 0.001, 0.0015),
    select_by: str = "return",
    workers: int = 4,
) -> HoldoutReport:
    split = len(df) - confirm_bars
    max_history = max(grid["history_candles"])
    if split - max_history < 24 * 14:
        raise ValueError("not enough data before the confirmation period for the largest training window")
    initial = dict(STRATEGIES[strategy]().params)
    settings = list(itertools.product(*grid.values()))

    def spec(setting, eval_start, fee=fee_rate, slip=slippage_rate):
        h, k, m, sc = setting
        return RunSpec(strategy, initial, h, k, m, sc, reoptimize_every, fee, slip, order_type, carry_rate_per_day,
                       min_walk_forward_score, min_improvement_margin, eval_start)

    selection_df = df.iloc[:split].reset_index(drop=True)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        # 1) selection: every setting scored on the same bars (after the largest warm-up)
        sel = list(pool.map(_run, [(spec(s, max_history - 1), selection_df) for s in settings]))
        value = {s: r["metrics"]["self_improving"][SELECT_METRIC[select_by]] for s, r in zip(settings, sel)}
        robust = {s: sum(value[x] for x in [s, *_neighbours(s, grid)]) / (1 + len(_neighbours(s, grid)))
                  for s in settings}
        for s, r in zip(settings, sel):
            r["robust_score"] = robust[s]
        chosen = max(settings, key=lambda s: robust[s])

        # 2) confirmation: every setting on the newest bars, chosen one flagged
        conf = list(pool.map(_run, [(spec(s, split), df) for s in settings]))
        for s, r in zip(settings, conf):
            r["chosen"] = s == chosen

        # 3) the chosen setting under different total per-side costs
        costs = list(pool.map(_run, [(spec(chosen, split, fee=c, slip=0.0), df) for c in cost_levels]))

    return HoldoutReport(
        strategy=strategy,
        split_timestamp=df["timestamp"].iloc[split].isoformat(),
        selection=sel,
        chosen=dict(zip(grid.keys(), chosen)),
        confirmation=conf,
        cost_sensitivity=costs,
    )
