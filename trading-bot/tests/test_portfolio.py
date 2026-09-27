from pathlib import Path

import pytest

from trading_bot.paper.portfolio import Portfolio


def test_buy_all_in_spends_cash_net_of_fee():
    p = Portfolio(symbol="BTC/USDT", cash=1000.0, fee_rate=0.01)
    p.buy_all_in(price=100.0, timestamp="t0")

    assert p.cash == 0.0
    assert p.position_qty == 990.0 / 100.0  # (1000 - 1% fee) / price
    assert p.entry_price == 100.0
    assert len(p.trade_log) == 1


def test_buy_when_already_holding_is_a_noop():
    p = Portfolio(symbol="BTC/USDT", cash=1000.0)
    p.buy_all_in(price=100.0, timestamp="t0")
    qty_after_first_buy = p.position_qty
    p.buy_all_in(price=50.0, timestamp="t1")

    assert p.position_qty == qty_after_first_buy
    assert len(p.trade_log) == 1


def test_sell_all_realizes_pnl_and_returns_to_cash():
    p = Portfolio(symbol="BTC/USDT", cash=1000.0, fee_rate=0.0)
    p.buy_all_in(price=100.0, timestamp="t0")
    p.sell_all(price=110.0, timestamp="t1")

    assert p.is_flat()
    assert p.cash == pytest.approx(1100.0)
    assert p.realized_pnl == pytest.approx(0.10)


def test_sell_when_flat_is_a_noop():
    p = Portfolio(symbol="BTC/USDT", cash=1000.0)
    p.sell_all(price=100.0, timestamp="t0")
    assert p.cash == 1000.0
    assert p.trade_log == []


def test_equity_reflects_mark_to_market():
    p = Portfolio(symbol="BTC/USDT", cash=1000.0, fee_rate=0.0)
    p.buy_all_in(price=100.0, timestamp="t0")
    assert p.equity(price=150.0) == pytest.approx(1500.0)


def test_save_and_load_round_trip(tmp_path: Path):
    p = Portfolio(symbol="BTC/USDT", cash=500.0, fee_rate=0.002)
    p.buy_all_in(price=20.0, timestamp="t0")
    path = tmp_path / "portfolio.json"
    p.save(path)

    loaded = Portfolio.load_or_create(path, symbol="BTC/USDT")
    assert loaded.to_dict() == p.to_dict()


def test_load_or_create_creates_fresh_when_missing(tmp_path: Path):
    path = tmp_path / "does_not_exist.json"
    p = Portfolio.load_or_create(path, symbol="ETH/USDT", initial_cash=42.0)
    assert p.cash == 42.0
    assert p.is_flat()
