"""Virtual portfolio for paper trading. Simulated cash and holdings only —
this class never talks to an exchange and can never place a real order.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Portfolio:
    symbol: str
    cash: float = 10_000.0
    position_qty: float = 0.0
    fee_rate: float = 0.001
    realized_pnl: float = 0.0
    entry_price: Optional[float] = None
    trade_log: list[dict] = field(default_factory=list)

    def equity(self, price: float) -> float:
        return self.cash + self.position_qty * price

    def is_flat(self) -> bool:
        return self.position_qty == 0.0

    def buy_all_in(self, price: float, timestamp: str) -> None:
        if not self.is_flat():
            return
        spend = self.cash
        fee = spend * self.fee_rate
        qty = (spend - fee) / price
        self.cash = 0.0
        self.position_qty = qty
        self.entry_price = price
        self.trade_log.append(
            {"timestamp": timestamp, "side": "buy", "price": price, "qty": qty, "fee": fee}
        )

    def sell_all(self, price: float, timestamp: str) -> None:
        if self.is_flat():
            return
        proceeds = self.position_qty * price
        fee = proceeds * self.fee_rate
        pnl = None
        if self.entry_price is not None:
            pnl = (price / self.entry_price - 1.0) - 2 * self.fee_rate
            self.realized_pnl += pnl
        self.cash += proceeds - fee
        self.trade_log.append(
            {
                "timestamp": timestamp,
                "side": "sell",
                "price": price,
                "qty": self.position_qty,
                "fee": fee,
                "pnl": pnl,
            }
        )
        self.position_qty = 0.0
        self.entry_price = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Portfolio":
        return cls(**data)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load_or_create(cls, path: Path, symbol: str, initial_cash: float = 10_000.0, fee_rate: float = 0.001) -> "Portfolio":
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls.from_dict(data)
        return cls(symbol=symbol, cash=initial_cash, fee_rate=fee_rate)
