"""Strategy interface.

A Strategy maps an OHLCV DataFrame + a parameter set to a *position* series:
1.0 = fully long (spot-held), 0.0 = flat/cash. Long-only, matching spot crypto
trading (no margin/shorting) so paper and (eventual) live execution can never
owe more than the cash on hand.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from itertools import product
from typing import Any, Iterable

import pandas as pd


class Strategy(ABC):
    name: str = "strategy"

    #: param_name -> candidate values, used by the optimizer's grid search.
    param_grid: dict[str, list[Any]] = {}

    def __init__(self, **params: Any):
        self.params = params

    @abstractmethod
    def generate_positions(self, df: pd.DataFrame) -> pd.Series:
        """Return a Series aligned to df.index with values in {0.0, 1.0}."""
        raise NotImplementedError

    @classmethod
    def param_combinations(cls) -> Iterable[dict[str, Any]]:
        if not cls.param_grid:
            yield {}
            return
        keys = list(cls.param_grid.keys())
        for values in product(*(cls.param_grid[k] for k in keys)):
            yield dict(zip(keys, values))

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"{self.name}({self.params})"
