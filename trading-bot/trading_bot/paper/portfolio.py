"""Virtual margin account for paper trading: long, flat or short, 1x notional.
Simulated cash and positions only — this class never talks to an exchange and
can never place a real order.

It mirrors `BacktestEngine`'s execution model so paper results and replays
are comparable:
- a market order fills at the decision close (slippage against you);
- a limit order rests at the decision close and fills only if a *later* bar
  trades through it (see `on_bar`); a new decision replaces it;
- margin carry accrues every bar on the open notional.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Portfolio:
    symbol: str
    cash: float = 10_000.0  # settled collateral; equity = cash + unrealized P&L
    qty: float = 0.0  # signed base-asset amount: > 0 long, < 0 short
    entry_price: Optional[float] = None
    fee_rate: float = 0.001
    slippage_rate: float = 0.0
    carry_rate_per_day: float = 0.0
    order_type: str = "market"
    pending: Optional[dict] = None  # resting limit: {"target", "limit", "placed_at"}
    realized_pnl: float = 0.0  # sum of closed trades' fractional returns
    carry_paid: float = 0.0
    trade_log: list[dict] = field(default_factory=list)

    # ---- state ----
    @property
    def position_qty(self) -> float:
        return self.qty

    def side(self) -> int:
        return 0 if self.qty == 0 else (1 if self.qty > 0 else -1)

    def is_flat(self) -> bool:
        return self.qty == 0.0

    def equity(self, price: float) -> float:
        if self.qty == 0 or self.entry_price is None:
            return self.cash
        return self.cash + self.qty * (price - self.entry_price)

    # ---- execution ----
    def _fill(self, target: int, price: float, timestamp: str, slippage: float) -> list[str]:
        """Move from the current side to `target` at `price` (close, then open)."""
        actions = []
        side = self.side()
        if side != 0 and target != side:
            fill = price * (1 - slippage * side)  # selling a long gets less; buying back a short pays more
            fee = abs(self.qty) * fill * self.fee_rate
            pnl = side * (fill / self.entry_price - 1.0) - 2 * self.fee_rate
            self.cash += self.qty * (fill - self.entry_price) - fee
            self.realized_pnl += pnl
            action = "sell" if side > 0 else "cover"
            self.trade_log.append({"timestamp": timestamp, "side": action, "price": fill, "qty": self.qty, "fee": fee, "pnl": pnl})
            self.qty, self.entry_price = 0.0, None
            actions.append(action)
        if target != 0 and self.qty == 0:
            fill = price * (1 + slippage * target)
            notional = self.cash
            fee = notional * self.fee_rate
            self.cash -= fee
            self.qty = target * (notional - fee) / fill
            self.entry_price = fill
            action = "buy" if target > 0 else "short"
            self.trade_log.append({"timestamp": timestamp, "side": action, "price": fill, "qty": self.qty, "fee": fee})
            actions.append(action)
        return actions

    def on_bar(self, high: float, low: float, close: float, timestamp: str, carry_per_bar: float) -> list[str]:
        """Process one newly closed bar: a resting limit fills if this bar traded
        through it, then carry is charged on whatever was held during the bar."""
        actions: list[str] = []
        if self.pending:
            target, limit = self.pending["target"], self.pending["limit"]
            direction = target - self.side()
            if (direction > 0 and low < limit) or (direction < 0 and high > limit):
                actions = self._fill(target, limit, timestamp, slippage=0.0)
                self.pending = None
        if self.qty:
            carry = abs(self.qty) * close * carry_per_bar
            self.cash -= carry
            self.carry_paid += carry
        return actions

    def submit(self, target: int, price: float, timestamp: str) -> list[str]:
        """Act on a decision made at this close: fill now (market) or rest a limit."""
        if target == self.side():
            self.pending = None
            return []
        if self.order_type == "market":
            self.pending = None
            return self._fill(target, price, timestamp, slippage=self.slippage_rate)
        self.pending = {"target": target, "limit": price, "placed_at": timestamp}
        return ["limit_placed"]

    # ---- spot-style helpers ----
    def buy_all_in(self, price: float, timestamp: str) -> None:
        if self.is_flat():
            self._fill(1, price, timestamp, slippage=self.slippage_rate)

    def sell_all(self, price: float, timestamp: str) -> None:
        if not self.is_flat():
            self._fill(0, price, timestamp, slippage=self.slippage_rate)

    # ---- persistence ----
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Portfolio":
        data = dict(data)
        if "position_qty" in data:  # files written by the spot-only version
            data["qty"] = data.pop("position_qty")
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load_or_create(
        cls,
        path: Path,
        symbol: str,
        initial_cash: float = 10_000.0,
        fee_rate: float = 0.001,
        slippage_rate: float = 0.0,
        carry_rate_per_day: float = 0.0,
        order_type: str = "market",
    ) -> "Portfolio":
        if path.exists():
            return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
        return cls(symbol=symbol, cash=initial_cash, fee_rate=fee_rate, slippage_rate=slippage_rate,
                   carry_rate_per_day=carry_rate_per_day, order_type=order_type)
