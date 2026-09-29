"""The "self-improving" part: on a fixed schedule, re-run the walk-forward
optimizer over recent history and, only if the challenger clears explicit
safety gates against the incumbent, swap the paper trader's live parameters.
Every attempt — promoted or not — is appended to an audit log; nothing is
ever swapped silently.

Gates (all required to promote), evaluated by `decide()`:
- the optimizer found a viable candidate at all (enough trades per fold);
- `min_walk_forward_score`: the candidate's out-of-sample walk-forward score
  clears an absolute floor (default 0.0 — risk-adjusted profitable OOS);
- the candidate differs from the params already live;
- `min_improvement_margin`: the candidate beats the incumbent by at least
  this much, where the incumbent is *re-scored on the same data and folds*
  every cycle — not compared against a stale score from when it was
  promoted. The incumbent's fixed params were picked on older data that can
  overlap these folds, so this comparison leans conservative (favours
  keeping what's live), which is the intended bias against churn.

`decide()` is shared by the live `SelfImprovementLoop` and the historical
`replay` so the backtested self-improvement is the same logic that runs live.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, Optional

import pandas as pd

from ..optimize.optimizer import OptimizationResult, WalkForwardOptimizer
from ..paper.trader import PaperTrader
from ..strategy.base import Strategy

HistoryProvider = Callable[[], pd.DataFrame]

NEG_INF = float("-inf")


@dataclass
class GateConfig:
    min_walk_forward_score: float = 0.0
    min_improvement_margin: float = 0.05


@dataclass
class Decision:
    promoted: bool
    reason_code: str  # no_viable | below_floor | same_as_active | insufficient_margin | promoted
    reason: str


def decide(result: OptimizationResult, incumbent_params: dict, incumbent_score: float, gate: GateConfig) -> Decision:
    wf = result.walk_forward_score
    if result.final_params is None or wf == NEG_INF:
        return Decision(False, "no_viable", "optimizer found no viable parameter set (too few trades in one or more folds)")
    if wf < gate.min_walk_forward_score:
        return Decision(
            False,
            "below_floor",
            f"walk-forward score {wf:.4f} is below the safety floor {gate.min_walk_forward_score:.4f} — not promoted",
        )
    if result.final_params == incumbent_params:
        return Decision(False, "same_as_active", "candidate is identical to the active params — nothing to change")
    if wf < incumbent_score + gate.min_improvement_margin:
        return Decision(
            False,
            "insufficient_margin",
            f"walk-forward score {wf:.4f} does not beat the incumbent's re-scored {incumbent_score:.4f} "
            f"by the required margin {gate.min_improvement_margin:.4f} — not promoted",
        )
    return Decision(
        True,
        "promoted",
        f"walk-forward score {wf:.4f} cleared the safety floor and beat the incumbent's re-scored "
        f"{incumbent_score:.4f} by the required margin — promoted",
    )


def run_cycle(
    df: pd.DataFrame,
    optimizer: WalkForwardOptimizer,
    strategy_cls: type[Strategy],
    incumbent_params: dict,
    gate: GateConfig,
    timeframe: str = "1h",
) -> tuple[OptimizationResult, float, Decision]:
    """One self-improvement cycle on `df`: optimize, re-score incumbent, gate."""
    result = optimizer.optimize(df, strategy_cls, timeframe=timeframe)
    incumbent_score = optimizer.evaluate_params(df, strategy_cls, incumbent_params, timeframe=timeframe)
    return result, incumbent_score, decide(result, incumbent_params, incumbent_score, gate)


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
        self.gate = GateConfig(min_walk_forward_score, min_improvement_margin)

        self.active_params_path = self.state_dir / f"active_params_{strategy_cls.name}.json"
        self.history_path = self.state_dir / f"optimization_history_{strategy_cls.name}.jsonl"

        # Resume with whatever was last promoted, so a restart doesn't silently
        # fall back to the CLI's starting params.
        if self.active_params_path.exists():
            self.trader.set_params(self._load_active().params)

    def _load_active(self) -> ActiveParams:
        if self.active_params_path.exists():
            data = json.loads(self.active_params_path.read_text(encoding="utf-8"))
            return ActiveParams.from_dict(data)
        return ActiveParams(params=dict(self.trader.strategy.params), score=NEG_INF)

    def _save_active(self, active: ActiveParams) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.active_params_path.write_text(json.dumps(active.to_dict(), indent=2), encoding="utf-8")

    def _append_history(self, record: dict) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with open(self.history_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def maybe_improve(self) -> dict:
        df = self.history_provider()
        active = self._load_active()
        result, incumbent_score, decision = run_cycle(
            df, self.optimizer, self.strategy_cls, active.params, self.gate, timeframe=self.timeframe
        )

        if decision.promoted:
            self.trader.set_params(result.final_params)
            active = ActiveParams(params=result.final_params, score=result.walk_forward_score)
        else:
            active = ActiveParams(params=active.params, score=incumbent_score)
        self._save_active(active)

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data_end": df["timestamp"].iloc[-1].isoformat(),
            "promoted": decision.promoted,
            "reason_code": decision.reason_code,
            "reason": decision.reason,
            "candidate_final_params": result.final_params,
            "candidate_final_score": result.final_score,
            "candidate_walk_forward_score": result.walk_forward_score,
            "incumbent_score": incumbent_score,
            "active_params_after": active.params,
            "active_score_after": active.score,
        }
        self._append_history(record)
        return record

    def run_schedule(
        self,
        steps: Optional[int] = None,
        step_seconds: float = 3600.0,
        reoptimize_every: int = 24,
        settle_seconds: float = 20.0,
        retry_seconds: float = 60.0,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> Iterator[dict]:
        """The live self-improving system: decide once per closed bar and
        re-optimize every `reoptimize_every` decided bars (starting with one
        before the first decision). Yields one event per action.

        Wakes `settle_seconds` after each bar boundary (a multiple of
        `step_seconds`) rather than sleeping a fixed interval, so decisions
        stay aligned to bar closes. If the exchange hasn't published the new
        bar yet, retries every `retry_seconds` until it has; only decided
        bars count toward `steps` and the re-optimization schedule."""
        if reoptimize_every < 1:
            raise ValueError("reoptimize_every must be >= 1")
        bars = 0
        last_reoptimized_at = None
        while steps is None or bars < steps:
            if bars % reoptimize_every == 0 and last_reoptimized_at != bars:
                last_reoptimized_at = bars
                yield {"event": "reoptimize", **self.maybe_improve()}
            record = self.trader.step()
            yield {"event": "step", **record}
            decided = record.get("action") != "no_new_bar"
            if decided:
                bars += 1
            if steps is not None and bars >= steps:
                break
            if step_seconds <= 0:
                continue
            now = clock()
            next_wake = (now // step_seconds + 1) * step_seconds + settle_seconds
            wait = next_wake - now if decided else min(retry_seconds, next_wake - now)
            sleep(max(0.0, wait))
