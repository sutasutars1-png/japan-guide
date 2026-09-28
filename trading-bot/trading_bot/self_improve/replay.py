"""Historical replay of the self-improving system — a backtest of the
*process*, not of one parameter set.

Walks the history bar by bar exactly as the live `run_schedule` would: at
each bar's close the currently-active params decide the position (executed
from the next bar, via the same `BacktestEngine`), and every
`reoptimize_every` bars a `run_cycle()` runs on the trailing
`history_candles` bars *ending at that bar* — never on future data. Output
compares the self-improving system against the static starting params and
buy-and-hold over the same bars, with every cycle's decision recorded.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from ..backtest.engine import BacktestEngine
from ..optimize.optimizer import WalkForwardOptimizer
from ..strategy.base import Strategy
from .loop import GateConfig, run_cycle


def _finite(x: float):
    return x if isinstance(x, (int, float)) and math.isfinite(x) else None


@dataclass
class ReplayResult:
    config: dict
    cycles: list[dict] = field(default_factory=list)
    active_by_bar: list[int] = field(default_factory=list)  # index into params_list
    params_list: list[dict] = field(default_factory=list)
    equity: dict[str, list[float]] = field(default_factory=dict)
    metrics: dict[str, dict] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "config": self.config,
            "params_list": self.params_list,
            "active_by_bar": self.active_by_bar,
            "cycles": self.cycles,
            "equity": self.equity,
            "metrics": self.metrics,
        }


def replay(
    df: pd.DataFrame,
    strategy_cls: type[Strategy],
    initial_params: dict,
    optimizer: WalkForwardOptimizer,
    gate: GateConfig,
    history_candles: int = 360,
    reoptimize_every: int = 24,
    timeframe: str = "1h",
) -> ReplayResult:
    if reoptimize_every < 1:
        raise ValueError("reoptimize_every must be >= 1")
    if history_candles > len(df):
        raise ValueError(f"history_candles ({history_candles}) exceeds available bars ({len(df)})")

    engine = optimizer.engine
    n = len(df)
    params_list: list[dict] = [dict(initial_params)]
    active_idx = 0
    active_by_bar: list[int] = []
    cycles: list[dict] = []

    first_cycle_bar = history_candles - 1
    for t in range(n):
        if t >= first_cycle_bar and (t - first_cycle_bar) % reoptimize_every == 0:
            window = df.iloc[t + 1 - history_candles : t + 1].reset_index(drop=True)
            incumbent = params_list[active_idx]
            result, incumbent_score, decision = run_cycle(window, optimizer, strategy_cls, incumbent, gate, timeframe)
            if decision.promoted:
                if result.final_params not in params_list:
                    params_list.append(dict(result.final_params))
                active_idx = params_list.index(result.final_params)
            cycles.append(
                {
                    "bar_index": t,
                    "timestamp": df["timestamp"].iloc[t].isoformat(),
                    "incumbent_params": incumbent,
                    "incumbent_score": _finite(incumbent_score),
                    "candidate_params": result.final_params,
                    "candidate_walk_forward_score": _finite(result.walk_forward_score),
                    "candidate_final_score": _finite(result.final_score),
                    "promoted": decision.promoted,
                    "reason_code": decision.reason_code,
                    "reason": decision.reason,
                    "active_params_after": params_list[active_idx],
                    "leaderboard": [
                        {"params": row["params"], "score": _finite(row["score"])} for row in result.leaderboard
                    ],
                }
            )
        active_by_bar.append(active_idx)

    # Positions are causal (rolling windows end at the current bar), so each
    # param set's full-history position series equals what it would have
    # computed live at that bar; stitch them by which set was active.
    positions_by_params = [strategy_cls(**p).generate_positions(df).fillna(0.0).to_numpy() for p in params_list]
    system_pos = [positions_by_params[active_by_bar[t]][t] for t in range(n)]

    runs = {
        "self_improving": engine.run_positions(df, system_pos, timeframe=timeframe),
        "static": engine.run(df, strategy_cls(**initial_params), timeframe=timeframe),
        "buy_hold": engine.run_positions(df, [1.0] * n, timeframe=timeframe),
    }

    return ReplayResult(
        config={
            "strategy": strategy_cls.name,
            "initial_params": dict(initial_params),
            "history_candles": history_candles,
            "reoptimize_every": reoptimize_every,
            "n_splits": optimizer.n_splits,
            "min_trades": optimizer.min_trades,
            "min_walk_forward_score": gate.min_walk_forward_score,
            "min_improvement_margin": gate.min_improvement_margin,
            "fee_rate": engine.fee_rate,
            "initial_cash": engine.initial_cash,
            "timeframe": timeframe,
        },
        cycles=cycles,
        active_by_bar=active_by_bar,
        params_list=params_list,
        equity={k: [float(v) for v in r.equity_curve.to_numpy()] for k, r in runs.items()},
        metrics={k: {mk: _finite(mv) for mk, mv in r.metrics.items()} for k, r in runs.items()},
    )
