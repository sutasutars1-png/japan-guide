"""Walk-forward grid search for strategy parameters.

"Self-improvement" in this project means: periodically re-run this optimizer
over recent history and, if it finds params that genuinely generalize
out-of-sample, adopt them for paper trading (see `trading_bot.self_improve`).
Never grid-search parameters and deploy the single best in-sample result —
that overfits to noise. Instead:

1. Split the available history into `n_splits` contiguous folds.
2. For fold i (i = 1..n_splits-1), train on everything *before* it (expanding
   window) by grid-searching every candidate param combo and picking the
   best by in-sample score; then evaluate that chosen combo on fold i itself
   (out-of-sample) and record the score.
3. The mean of those out-of-sample scores (`walk_forward_score`) is an
   honest estimate of "if you'd re-optimized like this historically, how
   would it have gone" — the number that should gate whether to trust and
   deploy the optimizer's recommendation at all.
4. Separately, `final_params` is the best combo found by grid-searching the
   *entire* available history — the concrete parameter set to deploy next,
   assuming `walk_forward_score` clears a sanity bar.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import pandas as pd

from ..backtest.engine import BacktestEngine
from ..strategy.base import Strategy

ScoreFn = Callable[[dict], float]


def default_score(metrics: dict, min_trades: int = 5) -> float:
    """Sharpe ratio, penalized to -inf if too few trades to be meaningful."""
    if metrics.get("num_trades", 0) < min_trades:
        return float("-inf")
    return metrics["sharpe"]


@dataclass
class FoldResult:
    fold_index: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    chosen_params: dict[str, Any]
    train_score: float
    test_score: float
    test_metrics: dict

    def to_dict(self) -> dict:
        return {
            "fold_index": self.fold_index,
            "train_start": self.train_start.isoformat(),
            "train_end": self.train_end.isoformat(),
            "test_start": self.test_start.isoformat(),
            "test_end": self.test_end.isoformat(),
            "chosen_params": self.chosen_params,
            "train_score": self.train_score,
            "test_score": self.test_score,
            "test_metrics": self.test_metrics,
        }


@dataclass
class OptimizationResult:
    strategy_name: str
    final_params: Optional[dict[str, Any]]
    final_score: float
    walk_forward_score: float
    folds: list[FoldResult] = field(default_factory=list)
    leaderboard: list[dict] = field(default_factory=list)  # sorted, best first

    def to_dict(self) -> dict:
        return {
            "strategy_name": self.strategy_name,
            "final_params": self.final_params,
            "final_score": self.final_score,
            "walk_forward_score": self.walk_forward_score,
            "folds": [f.to_dict() for f in self.folds],
            "leaderboard": self.leaderboard,
        }


class WalkForwardOptimizer:
    def __init__(
        self,
        engine: Optional[BacktestEngine] = None,
        n_splits: int = 4,
        score_fn: ScoreFn = default_score,
    ):
        if n_splits < 2:
            raise ValueError("n_splits must be >= 2 (need at least one train/test pair)")
        self.engine = engine or BacktestEngine()
        self.n_splits = n_splits
        self.score_fn = score_fn

    def _grid_search(self, df: pd.DataFrame, strategy_cls: type[Strategy], timeframe: str):
        """Return (best_params, best_score, leaderboard) over `df`."""
        leaderboard = []
        for params in strategy_cls.param_combinations():
            strategy = strategy_cls(**params)
            result = self.engine.run(df, strategy, timeframe=timeframe)
            score = self.score_fn(result.metrics)
            leaderboard.append({"params": params, "score": score, "metrics": result.metrics})

        leaderboard.sort(key=lambda row: row["score"], reverse=True)
        if not leaderboard or leaderboard[0]["score"] == float("-inf"):
            return None, float("-inf"), leaderboard
        return leaderboard[0]["params"], leaderboard[0]["score"], leaderboard

    def optimize(self, df: pd.DataFrame, strategy_cls: type[Strategy], timeframe: str = "1h") -> OptimizationResult:
        if len(df) < self.n_splits * 10:
            raise ValueError(
                f"Not enough data ({len(df)} bars) for {self.n_splits} walk-forward folds; "
                "fetch more history or reduce n_splits."
            )

        fold_bounds = self._fold_bounds(len(df), self.n_splits)
        folds: list[FoldResult] = []

        for i in range(1, self.n_splits):
            train_end_idx = fold_bounds[i]
            test_start_idx, test_end_idx = fold_bounds[i], fold_bounds[i + 1]
            train_df = df.iloc[:train_end_idx].reset_index(drop=True)
            test_df = df.iloc[test_start_idx:test_end_idx].reset_index(drop=True)
            if len(test_df) < 5 or len(train_df) < 10:
                continue

            chosen_params, train_score, _ = self._grid_search(train_df, strategy_cls, timeframe)
            if chosen_params is None:
                continue

            test_result = self.engine.run(test_df, strategy_cls(**chosen_params), timeframe=timeframe)
            test_score = self.score_fn(test_result.metrics)

            folds.append(
                FoldResult(
                    fold_index=i,
                    train_start=train_df["timestamp"].iloc[0],
                    train_end=train_df["timestamp"].iloc[-1],
                    test_start=test_df["timestamp"].iloc[0],
                    test_end=test_df["timestamp"].iloc[-1],
                    chosen_params=chosen_params,
                    train_score=train_score,
                    test_score=test_score,
                    test_metrics=test_result.metrics,
                )
            )

        finite_test_scores = [f.test_score for f in folds if f.test_score != float("-inf")]
        walk_forward_score = sum(finite_test_scores) / len(finite_test_scores) if finite_test_scores else float("-inf")

        final_params, final_score, leaderboard = self._grid_search(df, strategy_cls, timeframe)

        return OptimizationResult(
            strategy_name=strategy_cls.name,
            final_params=final_params,
            final_score=final_score,
            walk_forward_score=walk_forward_score,
            folds=folds,
            leaderboard=leaderboard[:20],
        )

    @staticmethod
    def _fold_bounds(n_rows: int, n_splits: int) -> list[int]:
        step = n_rows // n_splits
        bounds = [i * step for i in range(n_splits)]
        bounds.append(n_rows)
        return bounds
