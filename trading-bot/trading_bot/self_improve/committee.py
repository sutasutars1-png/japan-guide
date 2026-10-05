"""Committee of self-improvement rule settings, trading their majority vote.

`rolling` validation showed that picking one rule setting (training window,
folds, minimum trades, objective) is fragile: the setting that looked best on
past data often did badly next. A committee avoids the choice. Every rule
setting in the grid runs its own self-improvement — its own re-optimization,
its own promotion gate, its own active parameters — and the trader takes the
sign of the sum of their positions (-1, 0 or 1). Nobody picks a setting, and
no single setting's bad streak decides the position.

This is the live counterpart of the "vote_all" variant in
`research/rolling.py`; both use the same members and the same gate.
"""
from __future__ import annotations

import itertools
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

from ..backtest.engine import BacktestEngine
from ..optimize.optimizer import WalkForwardOptimizer
from ..paper.trader import PaperTrader
from ..strategy.base import Strategy
from .loop import NEG_INF, ActiveParams, GateConfig, SelfImprovementLoop, run_cycle

Setting = tuple  # (history_candles, n_splits, min_trades, score)


def member_tag(setting: Setting) -> str:
    return "/".join(str(x) for x in setting)


def all_settings(grid: dict) -> list[Setting]:
    return list(itertools.product(*grid.values()))


class VoteStrategy(Strategy):
    """Majority vote of member strategies: sign of the sum of their positions."""

    name = "vote"

    def __init__(self, members: dict[str, Strategy]):
        super().__init__(members={tag: dict(s.params) for tag, s in members.items()})
        self.members = members

    def generate_positions(self, df: pd.DataFrame) -> pd.Series:
        total = sum(s.generate_positions(df).fillna(0.0).to_numpy(dtype=float) for s in self.members.values())
        return pd.Series(np.sign(total), index=df.index, name="position")


class CommitteeLoop(SelfImprovementLoop):
    """Same schedule as `SelfImprovementLoop` (decide every bar, re-optimize
    every `reoptimize_every` bars); a cycle re-optimizes every member on its
    own trailing window, then the trader votes with the members' active params."""

    def __init__(
        self,
        trader: PaperTrader,
        strategy_cls: type[Strategy],
        settings: list[Setting],
        engine: BacktestEngine,
        history_provider: Callable[[], pd.DataFrame],
        state_dir: Path,
        timeframe: str = "1h",
        min_walk_forward_score: float = 0.0,
        min_improvement_margin: float = 0.05,
        initial_params: Optional[dict] = None,
    ):
        self.trader = trader
        self.strategy_cls = strategy_cls
        self.settings = list(settings)
        self.history_provider = history_provider
        self.state_dir = Path(state_dir)
        self.timeframe = timeframe
        self.gate = GateConfig(min_walk_forward_score, min_improvement_margin)
        self.optimizers = {
            member_tag(s): WalkForwardOptimizer(engine, n_splits=s[1], min_trades=s[2], score=s[3]) for s in self.settings
        }
        self.active_params_path = self.state_dir / f"active_params_{strategy_cls.name}_committee.json"
        self.history_path = self.state_dir / f"optimization_history_{strategy_cls.name}.jsonl"
        start = dict(strategy_cls(**(initial_params or {})).params)
        saved = self._load_members()
        self.active = {member_tag(s): saved.get(member_tag(s), ActiveParams(dict(start), NEG_INF)) for s in self.settings}
        self._apply()

    @property
    def max_history(self) -> int:
        return max(s[0] for s in self.settings)

    def _load_members(self) -> dict[str, ActiveParams]:
        if not self.active_params_path.exists():
            return {}
        data = json.loads(self.active_params_path.read_text(encoding="utf-8"))
        return {tag: ActiveParams.from_dict(v) for tag, v in data["members"].items()}

    def _save_members(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        data = {"members": {tag: a.to_dict() for tag, a in self.active.items()}}
        self.active_params_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _apply(self) -> None:
        self.trader.strategy = VoteStrategy({tag: self.strategy_cls(**a.params) for tag, a in self.active.items()})

    def maybe_improve(self) -> dict:
        df = self.history_provider()
        now = datetime.now(timezone.utc).isoformat()
        promoted = []
        for setting in self.settings:
            tag = member_tag(setting)
            window = df.iloc[-setting[0]:].reset_index(drop=True)
            result, incumbent_score, decision = run_cycle(
                window, self.optimizers[tag], self.strategy_cls, self.active[tag].params, self.gate, self.timeframe
            )
            if decision.promoted:
                self.active[tag] = ActiveParams(params=result.final_params, score=result.walk_forward_score)
                promoted.append(tag)
            else:
                self.active[tag] = ActiveParams(params=self.active[tag].params, score=incumbent_score)
            self._append_history({
                "timestamp": now,
                "data_end": window["timestamp"].iloc[-1].isoformat(),
                "member": tag,
                "promoted": decision.promoted,
                "reason_code": decision.reason_code,
                "reason": decision.reason,
                "candidate_final_params": result.final_params,
                "candidate_final_score": result.final_score,
                "candidate_walk_forward_score": result.walk_forward_score,
                "incumbent_score": incumbent_score,
                "active_params_after": self.active[tag].params,
            })
        self._save_members()
        self._apply()
        return {
            "timestamp": now,
            "data_end": df["timestamp"].iloc[-1].isoformat(),
            "members": len(self.settings),
            "promoted": bool(promoted),
            "promoted_members": promoted,
            "reason_code": "promoted" if promoted else "no_change",
        }
