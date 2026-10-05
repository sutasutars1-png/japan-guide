"""Backtest engine for one asset, long, flat or short (margin, 1x notional).

Assumptions (documented, not hidden):
- A strategy's target position for bar t is decided from data available
  *through* bar t's close and can only take effect from bar t+1 — no lookahead.
  Positions are -1 (short), 0 (flat) or 1 (long), always at 1x the account's
  equity, so a flip long -> short trades 2 units of notional.
- Execution (`order_type`):
  - "market": the order fills at the decision bar's close.
  - "limit": a limit order rests at the decision bar's close and fills only if
    the next bar trades *through* that price (low below it to buy, high above
    it to sell — merely touching may leave it unfilled in the queue). If not,
    the position is unchanged for that bar and the order is re-placed at the
    next close. Missed fills cluster exactly when price runs away, which is
    the real cost of passive orders; the engine keeps it rather than assuming
    every limit fills.
- Accounting is a margin account in money, like `paper.Portfolio`: at each
  fill the whole equity is committed (quantity = equity / price, net of the
  fee) and that quantity is held until the next fill — a short is not
  re-sized every bar, so its exposure drifts with price as a real one does.
- Costs: `fee_rate + slippage_rate` on the notional of every fill (per side),
  plus a margin carry of `carry_rate_per_day` on the open notional for every
  bar it is held (Japanese crypto margin charges about 0.04%/day on open
  positions, long or short).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
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
ORDER_TYPES = ("market", "limit")


def periods_per_year_for(timeframe: str) -> float:
    return TIMEFRAME_PERIODS_PER_YEAR.get(timeframe, 365 * 24)


@dataclass
class Trade:
    entry_time: pd.Timestamp
    entry_price: float
    side: int = 1  # 1 long, -1 short
    exit_time: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    pnl: Optional[float] = None  # fractional return of this trade, net of fees and carry

    def to_dict(self) -> dict:
        return {
            "side": self.side,
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


def execute(raw: np.ndarray, close: np.ndarray, high: np.ndarray, low: np.ndarray, order_type: str) -> np.ndarray:
    """Position actually held during each bar, given targets decided at each close."""
    n = len(raw)
    held = np.zeros(n)
    if n == 0:
        return held
    if order_type == "market":
        held[1:] = raw[:-1]
        return held
    # Plain lists: this loop runs for every candidate in every fold, and list
    # indexing is several times faster than numpy scalar access.
    r, c, h, lo = raw.tolist(), close.tolist(), high.tolist(), low.tolist()
    out = [0.0] * n
    cur = 0.0
    for t in range(n - 1):
        target = r[t]
        if target > cur:  # buying: needs the next bar to trade below the limit
            if lo[t + 1] < c[t]:
                cur = target
        elif target < cur:  # selling
            if h[t + 1] > c[t]:
                cur = target
        out[t + 1] = cur
    return np.array(out)


def account_equity(held: np.ndarray, close: np.ndarray, cash: float, cost: float, carry_per_bar: float) -> np.ndarray:
    """Equity at each close for a margin account holding `held[t]` during bar t.
    A change of position fills at the previous close (where the order was placed):
    close the old quantity, then commit the whole equity to the new side."""
    h, c = held.tolist(), close.tolist()
    out = [0.0] * len(h)
    qty, entry, prev = 0.0, 0.0, 0.0
    for t in range(len(h)):
        pos = h[t]
        if pos != prev:
            price = c[t - 1]
            if qty:
                cash += qty * (price - entry) - abs(qty) * price * cost
                qty = 0.0
            if pos:
                fee = cash * cost
                cash -= fee
                qty, entry = pos * cash / price, price
            prev = pos
        if qty:
            cash -= abs(qty) * c[t] * carry_per_bar
            out[t] = cash + qty * (c[t] - entry)
        else:
            out[t] = cash
    return np.array(out)


class BacktestEngine:
    def __init__(
        self,
        initial_cash: float = 10_000.0,
        fee_rate: float = 0.001,
        slippage_rate: float = 0.0,
        order_type: str = "market",
        carry_rate_per_day: float = 0.0,
    ):
        if order_type not in ORDER_TYPES:
            raise ValueError(f"order_type must be one of {ORDER_TYPES}")
        self.initial_cash = initial_cash
        self.fee_rate = fee_rate
        self.slippage_rate = slippage_rate
        self.order_type = order_type
        self.carry_rate_per_day = carry_rate_per_day

    @property
    def cost_rate(self) -> float:
        """Total per-side cost as a fraction of the traded notional."""
        return self.fee_rate + self.slippage_rate

    def run(self, df: pd.DataFrame, strategy: Strategy, timeframe: str = "1h") -> BacktestResult:
        if df.empty:
            raise ValueError("Cannot backtest an empty OHLCV DataFrame")
        return self.run_positions(df, strategy.generate_positions(df), timeframe=timeframe)

    def run_positions(self, df: pd.DataFrame, raw_position, timeframe: str = "1h") -> BacktestResult:
        """Backtest target positions decided at each bar's close."""
        if df.empty:
            raise ValueError("Cannot backtest an empty OHLCV DataFrame")

        raw = pd.Series(raw_position, index=df.index, dtype=float).fillna(0.0).to_numpy()
        close = df["close"].to_numpy(dtype=float)
        held = execute(raw, close, df["high"].to_numpy(dtype=float), df["low"].to_numpy(dtype=float), self.order_type)

        periods = periods_per_year_for(timeframe)
        carry_per_bar = self.carry_rate_per_day * 365 / periods
        eq = account_equity(held, close, self.initial_cash, self.cost_rate, carry_per_bar)

        index = df["timestamp"]
        equity = pd.Series(eq, index=index)
        net_return = pd.Series(np.diff(eq, prepend=self.initial_cash) / np.r_[self.initial_cash, eq[:-1]], index=index)
        executed_position = pd.Series(held, index=index)
        trades = self._extract_trades(df, held, self.cost_rate, carry_per_bar)

        return BacktestResult(
            equity_curve=equity,
            returns=net_return,
            position=executed_position,
            trades=trades,
            metrics=metrics_mod.summarize(
                equity=equity, returns=net_return, trades=[t.to_dict() for t in trades], periods_per_year=periods
            ),
        )

    @staticmethod
    def _extract_trades(df: pd.DataFrame, held: np.ndarray, cost_rate: float, carry_per_bar: float) -> list[Trade]:
        """One trade per run of a non-zero held position. A position held from
        bar t was established at bar t-1's close, so that is its entry price."""
        ts, close = df["timestamp"].tolist(), df["close"].to_numpy(dtype=float)
        trades: list[Trade] = []
        open_trade: Optional[Trade] = None
        opened_at = 0
        for t in range(1, len(held)):
            if held[t] == held[t - 1]:
                continue
            if open_trade is not None:
                open_trade.exit_time, open_trade.exit_price = ts[t - 1], float(close[t - 1])
                gross = open_trade.side * (open_trade.exit_price / open_trade.entry_price - 1.0)
                open_trade.pnl = gross - 2 * cost_rate - carry_per_bar * (t - opened_at)
                trades.append(open_trade)
                open_trade = None
            if held[t] != 0:
                open_trade = Trade(entry_time=ts[t - 1], entry_price=float(close[t - 1]), side=int(np.sign(held[t])))
                opened_at = t
        if open_trade is not None:  # still open: marked to the last close, unrealized
            open_trade.exit_time, open_trade.exit_price = ts[-1], float(close[-1])
            trades.append(open_trade)
        return trades
