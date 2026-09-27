"""The "self-improving" part: periodically re-run the walk-forward optimizer
over recent history and, only if it clears explicit safety gates, swap the
paper trader's live parameters. Every attempt — promoted or not — is appended
to an audit log; nothing is ever swapped silently.

Gates against overfitting/churn (both required to promote):
- `min_walk_forward_score`: the candidate's out-of-sample walk-forward score
  must clear an absolute floor (default 0.0 — i.e. it must have been
  profitable on a risk-adjusted basis out-of-sample, not just in-sample).
- `min_improvement_margin`: the candidate must beat the currently active
  params' own last-known walk-forward score by at least this much, so a
  noisy re-optimization can't flip params back and forth for a negligible
  gain.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

from ..optimize.optimizer import OptimizationResult, WalkForwardOptimizer
from ..paper.trader import PaperTrader
from ..strategy.base import Strategy

HistoryProvider = Callable[[], pd.DataFrame]


@dataclass
class ActiveParams:
    params: dict
    score: float

    def to_dict(self) -> dict:
        return {"params": self.params, "score": self.score}

    @classmethod
    def from_dict(cls, data: dict) -> "ActiveParams":
        return cls(params=data["params"], score=data["score"])


class SelfImprovementLoop:
    def __init__(
        self,
        trader: PaperTrader,
        optimizer: WalkForwardOptimizer,
        strategy_cls: type[Strategy],
        history_provider: HistoryProvider,
        state_dir: Path,
        timeframe: str = "1h",
        min_walk_forward_score: float = 0.0,
        min_improvement_margin: float = 0.05,
    ):
        self.trader = trader
        self.optimizer = optimizer
        self.strategy_cls = strategy_cls
        self.history_provider = history_provider
        self.state_dir = Path(state_dir)
        self.timeframe = timeframe
        self.min_walk_forward_score = min_walk_forward_score
        self.min_improvement_margin = min_improvement_margin

        self.active_params_path = self.state_dir / f"active_params_{strategy_cls.name}.json"
        self.history_path = self.state_dir / f"optimization_history_{strategy_cls.name}.jsonl"

    def _load_active(self) -> ActiveParams:
        if self.active_params_path.exists():
            data = json.loads(self.active_params_path.read_text(encoding="utf-8"))
            return ActiveParams.from_dict(data)
        return ActiveParams(params=dict(self.trader.strategy.params), score=float("-inf"))

    def _save_active(self, active: ActiveParams) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.active_params_path.write_text(json.dumps(active.to_dict(), indent=2), encoding="utf-8")

    def _append_history(self, record: dict) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with open(self.history_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def maybe_improve(self) -> dict:
        df = self.history_provider()
        result: OptimizationResult = self.optimizer.optimize(df, self.strategy_cls, timeframe=self.timeframe)
        active = self._load_active()

        promoted = False
        if result.final_params is None or result.walk_forward_score == float("-inf"):
            reason = "optimizer found no viable parameter set (too few trades in one or more folds)"
        elif result.walk_forward_score < self.min_walk_forward_score:
            reason = (
                f"walk-forward score {result.walk_forward_score:.4f} is below the safety floor "
                f"{self.min_walk_forward_score:.4f} — not promoted"
            )
        elif result.walk_forward_score < active.score + self.min_improvement_margin:
            reason = (
                f"walk-forward score {result.walk_forward_score:.4f} does not beat the active "
                f"params' {active.score:.4f} by the required margin {self.min_improvement_margin:.4f} — not promoted"
            )
        else:
            reason = (
                f"walk-forward score {result.walk_forward_score:.4f} cleared the safety floor and "
                f"beat active {active.score:.4f} by the required margin — promoted"
            )
            promoted = True
            self.trader.set_params(result.final_params)
            active = ActiveParams(params=result.final_params, score=result.walk_forward_score)
            self._save_active(active)

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "promoted": promoted,
            "reason": reason,
            "candidate_final_params": result.final_params,
            "candidate_final_score": result.final_score,
            "candidate_walk_forward_score": result.walk_forward_score,
            "active_params_after": active.params,
            "active_score_after": active.score,
        }
        self._append_history(record)
        return record

    def run_loop(self, iterations: Optional[int] = None, interval_seconds: float = 86_400.0):
        """Yield one `maybe_improve()` record per cycle; sleeps between cycles."""
        import time

        count = 0
        while iterations is None or count < iterations:
            yield self.maybe_improve()
            count += 1
            if iterations is None or count < iterations:
                time.sleep(interval_seconds)
