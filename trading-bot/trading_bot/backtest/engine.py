"""Vectorized long-only backtest engine.

Simplifying assumptions (documented, not hidden):
- A strategy's position for bar t is decided from data available *through*
  bar t's close, but only takes effect from bar t+1 onward (`shift(1)`) —
  no lookahead.
- Fees are charged as a return drag proportional to the fraction of the
  portfolio that changes position (`fee_rate` per unit turnover); there is
  no separate slippage model. This is deliberately simple, not a claim of
  realistic execution.
- Long-only, single asset, no leverage: position is either 0 (cash) or 1
  (fully invested), matching spot trading.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from ..strategy.base import Strategy
from . import metrics as metrics_mod

TIMEFRAME_PERIODS_PER_YEAR = {
    "1m": 365 * 24 * 60,
    "5m": 365 * 24 * 12,
    "15m": 365 * 24 * 4,
    "1h": 365 * 24,
    "4h": 365 * 6,
    "1d": 365,
}


def periods_per_year_for(timeframe: str) -> float:
    return TIMEFRAME_PERIODS_PER_YEAR.get(timeframe, 365 * 24)


@dataclass
class Trade:
    entry_time: pd.Timestamp
    entry_price: float
    exit_time: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    pnl: Optional[float] = None  # fractional return of this trade, net of fees

    def to_dict(self) -> dict:
        return {
            "entry_time": self.entry_time.isoformat() if self.entry_time is not None else None,
            "entry_price": self.entry_price,
            "exit_time": self.exit_time.isoformat() if self.exit_time is not None else None,
            "exit_price": self.exit_price,
            "pnl": self.pnl,
        }


@dataclass
class BacktestResult:
    equity_curve: pd.Series
    returns: pd.Series
    position: pd.Series
    trades: list[Trade] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    def trades_as_dicts(self) -> list[dict]:
        return [t.to_dict() for t in self.trades]


class BacktestEngine:
    def __init__(self, initial_cash: float = 10_000.0, fee_rate: float = 0.001):
        self.initial_cash = initial_cash
        self.fee_rate = fee_rate

    def run(self, df: pd.DataFrame, strategy: Strategy, timeframe: str = "1h") -> BacktestResult:
        if df.empty:
            raise ValueError("Cannot backtest an empty OHLCV DataFrame")

        raw_position = strategy.generate_positions(df).fillna(0.0)
        executed_position = raw_position.shift(1).fillna(0.0)

        bar_return = df["close"].pct_change().fillna(0.0)
        turnover = executed_position.diff().abs()
        turnover.iloc[0] = executed_position.iloc[0]
        fee_drag = turnover * self.fee_rate

        net_return = executed_position * bar_return - fee_drag
        equity = self.initial_cash * (1.0 + net_return).cumprod()
        equity.index = df["timestamp"]
        net_return.index = df["timestamp"]
        executed_position.index = df["timestamp"]

        trades = self._extract_trades(df, executed_position, self.fee_rate)

        result_metrics = metrics_mod.summarize(
            equity=equity,
            returns=net_return,
            trades=[t.to_dict() for t in trades],
            periods_per_year=periods_per_year_for(timeframe),
        )

        return BacktestResult(
            equity_curve=equity,
            returns=net_return,
            position=executed_position,
            trades=trades,
            metrics=result_metrics,
        )

    @staticmethod
    def _extract_trades(df: pd.DataFrame, executed_position: pd.Series, fee_rate: float) -> list[Trade]:
        trades: list[Trade] = []
        open_trade: Optional[Trade] = None
        prev_pos = 0.0
        for ts, close, pos in zip(df["timestamp"], df["close"], executed_position):
            if prev_pos == 0.0 and pos == 1.0:
                open_trade = Trade(entry_time=ts, entry_price=float(close))
            elif prev_pos == 1.0 and pos == 0.0 and open_trade is not None:
                open_trade.exit_time = ts
                open_trade.exit_price = float(close)
                gross = open_trade.exit_price / open_trade.entry_price - 1.0
                open_trade.pnl = gross - 2 * fee_rate  # entry + exit fee
                trades.append(open_trade)
                open_trade = None
            prev_pos = pos

        if open_trade is not None:
            # Still open at the end of the data — mark-to-last-close, unrealized.
            last_ts = df["timestamp"].iloc[-1]
            last_close = float(df["close"].iloc[-1])
            open_trade.exit_time = last_ts
            open_trade.exit_price = last_close
            open_trade.pnl = None  # unrealized: excluded from win-rate/closed-trade stats
            trades.append(open_trade)

        return trades
