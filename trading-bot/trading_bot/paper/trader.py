"""Paper trading loop.

Simulates order execution against a virtual `Portfolio`; it never calls any
exchange endpoint that could place, modify, or cancel a real order. Live
market data comes from a caller-supplied `data_provider` callable — decoupled
from any specific fetcher so this loop is trivially testable without network
access, and so a future live-trading executor is a separate, explicit class
rather than a flag on this one.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable, Iterator, Optional

import pandas as pd

from ..strategy.base import Strategy
from .portfolio import Portfolio

DataProvider = Callable[[], pd.DataFrame]


class PaperTrader:
    def __init__(
        self,
        symbol: str,
        strategy_cls: type[Strategy],
        params: dict,
        data_provider: DataProvider,
        state_dir: Path,
        timeframe: str = "1h",
        initial_cash: float = 10_000.0,
        fee_rate: float = 0.001,
    ):
        self.symbol = symbol
        self.strategy_cls = strategy_cls
        self.timeframe = timeframe
        self.data_provider = data_provider
        self.state_dir = Path(state_dir)

        safe_symbol = symbol.replace("/", "-")
        self.portfolio_path = self.state_dir / f"portfolio_{safe_symbol}.json"
        self.decisions_log_path = self.state_dir / f"decisions_{safe_symbol}.jsonl"

        self.portfolio = Portfolio.load_or_create(self.portfolio_path, symbol, initial_cash, fee_rate)
        self.strategy = strategy_cls(**params)

    def set_params(self, params: dict) -> None:
        """Swap the active strategy's parameters (used by the self-improve loop)."""
        self.strategy = self.strategy_cls(**params)

    def step(self) -> dict:
        """Fetch the latest data, decide, and simulate at most one trade."""
        df = self.data_provider()
        if df.empty:
            raise ValueError("data_provider returned an empty OHLCV DataFrame")

        positions = self.strategy.generate_positions(df)
        desired_position = float(positions.iloc[-1])
        latest_price = float(df["close"].iloc[-1])
        latest_ts = df["timestamp"].iloc[-1]
        ts_str = latest_ts.isoformat() if hasattr(latest_ts, "isoformat") else str(latest_ts)

        action = "hold"
        if desired_position == 1.0 and self.portfolio.is_flat():
            self.portfolio.buy_all_in(latest_price, ts_str)
            action = "buy"
        elif desired_position == 0.0 and not self.portfolio.is_flat():
            self.portfolio.sell_all(latest_price, ts_str)
            action = "sell"

        self.portfolio.save(self.portfolio_path)

        record = {
            "timestamp": ts_str,
            "price": latest_price,
            "desired_position": desired_position,
            "action": action,
            "equity": self.portfolio.equity(latest_price),
            "params": self.strategy.params,
        }
        self._append_decision(record)
        return record

    def _append_decision(self, record: dict) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with open(self.decisions_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def run_loop(self, iterations: Optional[int] = None, sleep_seconds: float = 60.0) -> Iterator[dict]:
        """Yield one decision record per step; sleeps between steps (not after the last)."""
        count = 0
        while iterations is None or count < iterations:
            yield self.step()
            count += 1
            if iterations is None or count < iterations:
                time.sleep(sleep_seconds)
