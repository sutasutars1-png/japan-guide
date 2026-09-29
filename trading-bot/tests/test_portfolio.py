from pathlib import Path

import pytest

from trading_bot.paper.portfolio import Portfolio


def test_buy_all_in_spends_cash_net_of_fee():
    p = Portfolio(symbol="BTC/USDT", cash=1000.0, fee_rate=0.01)
    p.buy_all_in(price=100.0, timestamp="t0")

    assert p.cash == 990.0  # margin account: collateral stays, net of the fee
    assert p.position_qty == 990.0 / 100.0  # (1000 - 1% fee) / price
    assert p.equity(100.0) == 990.0
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


def test_short_then_cover_profits_from_a_fall_and_logs_both_legs():
    p = Portfolio(symbol="BTC/USD", cash=1000.0, fee_rate=0.0)
    assert p._fill(-1, 100.0, "t0", slippage=0.0) == ["short"]
    assert p.side() == -1 and p.equity(90.0) == pytest.approx(1100.0)
    assert p._fill(1, 90.0, "t1", slippage=0.0) == ["cover", "buy"]  # a flip closes then opens
    assert p.cash == pytest.approx(1100.0) and p.side() == 1
    assert p.realized_pnl == pytest.approx(0.10)


def test_limit_rests_until_a_bar_trades_through_it():
    p = Portfolio(symbol="BTC/USD", cash=1000.0, fee_rate=0.0002, order_type="limit")
    assert p.submit(1, 100.0, "t0") == ["limit_placed"] and p.is_flat()
    assert p.on_bar(high=101.0, low=100.0, close=100.5, timestamp="t1", carry_per_bar=0.0) == []  # touched, not through
    assert p.is_flat() and p.pending["limit"] == 100.0
    assert p.on_bar(high=100.8, low=99.9, close=100.2, timestamp="t2", carry_per_bar=0.0) == ["buy"]
    assert p.entry_price == 100.0 and p.pending is None
    assert p.submit(1, 100.2, "t2") == []  # already long: nothing to do


def test_carry_accrues_on_the_open_notional_each_bar():
    p = Portfolio(symbol="BTC/USD", cash=1000.0, fee_rate=0.0)
    p._fill(-1, 100.0, "t0", slippage=0.0)
    for _ in range(24):
        p.on_bar(high=100.0, low=100.0, close=100.0, timestamp="t", carry_per_bar=0.0004 / 24)
    assert p.carry_paid == pytest.approx(1000.0 * 0.0004)
    assert p.equity(100.0) == pytest.approx(1000.0 - 0.4)


def test_loads_files_written_by_the_spot_only_version():
    p = Portfolio.from_dict({"symbol": "BTC/USD", "cash": 0.0, "position_qty": 2.5, "fee_rate": 0.001,
                             "realized_pnl": 0.0, "entry_price": 100.0, "trade_log": []})
    assert p.qty == 2.5 and p.side() == 1
