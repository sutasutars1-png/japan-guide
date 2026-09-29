from pathlib import Path

import pandas as pd
import pytest
import requests

from trading_bot.data.fetch import load_csv
from trading_bot.data.kraken_trades import KrakenTradeHistory, aggregate_trades
from trading_bot.data.store import OHLCVStore

H = 3_600_000
T0 = 1_788_000_000_000 - 1_788_000_000_000 % H  # an hour boundary


def _bars(start_hour: int, n: int, price: float = 100.0) -> pd.DataFrame:
    ts = pd.to_datetime([T0 + (start_hour + i) * H for i in range(n)], unit="ms", utc=True)
    return pd.DataFrame({"timestamp": ts, "open": price, "high": price, "low": price, "close": price, "volume": 1.0})


def _store(tmp_path: Path) -> OHLCVStore:
    return OHLCVStore(tmp_path, "kraken", "BTC/USD", "1h")


def test_merge_accumulates_instead_of_replacing(tmp_path: Path):
    store = _store(tmp_path)
    store.merge(_bars(0, 5), "exchange_ohlc")
    stats = store.merge(_bars(3, 5, price=101.0), "exchange_ohlc")  # later window, overlapping 2 bars

    df = store.load()
    assert len(df) == 8
    assert stats == {"added": 3, "replaced": 2, "kept_existing": 0, "total": 8}
    assert df["close"].iloc[0] == 100.0 and df["close"].iloc[-1] == 101.0


def test_lower_priority_source_never_overwrites_exchange_candles(tmp_path: Path):
    store = _store(tmp_path)
    store.merge(_bars(0, 3, price=100.0), "exchange_ohlc")
    stats = store.merge(_bars(-2, 5, price=99.0), "trades")

    df = store.load().set_index("timestamp")
    assert stats["added"] == 2 and stats["kept_existing"] == 3
    assert (df.loc[df["source"] == "exchange_ohlc", "close"] == 100.0).all()
    # ...but exchange candles do replace reconstructed ones.
    store.merge(_bars(-2, 1, price=98.0), "exchange_ohlc")
    assert store.load()["close"].iloc[0] == 98.0


def test_store_file_stays_readable_by_load_csv(tmp_path: Path):
    store = _store(tmp_path)
    store.merge(_bars(0, 3), "exchange_ohlc")
    assert len(load_csv(store.path)) == 3


def test_missing_ranges_newest_first(tmp_path: Path):
    store = _store(tmp_path)
    store.merge(_bars(2, 2), "exchange_ohlc")   # hours 2,3
    store.merge(_bars(6, 1), "exchange_ohlc")   # hour 6
    assert store.missing_ranges(T0, T0 + 8 * H) == [
        (T0 + 7 * H, T0 + 8 * H),
        (T0 + 4 * H, T0 + 6 * H),
        (T0, T0 + 2 * H),
    ]


def test_closed_bars_drops_the_bar_still_forming():
    from trading_bot.data.fetch import closed_bars

    df = pd.DataFrame({"timestamp": [T0, T0 + H, T0 + 2 * H], "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0})
    assert closed_bars(df, "1h", now_ms=T0 + 2 * H + 10)["timestamp"].tolist() == [T0, T0 + H]
    assert closed_bars(df, "1h", now_ms=T0 + 3 * H)["timestamp"].tolist() == [T0, T0 + H, T0 + 2 * H]


def test_aggregate_trades_builds_ohlcv_and_fills_empty_hours():
    s = T0 / 1000
    trades = [(s + 10, 100.0, 1.0), (s + 20, 105.0, 2.0), (s + 30, 95.0, 1.0), (s + 40, 101.0, 1.0),
              (s + 2 * 3600 + 5, 110.0, 3.0)]
    df = aggregate_trades(trades, T0, T0 + 3 * H, H)
    assert df[["open", "high", "low", "close", "volume"]].iloc[0].tolist() == [100.0, 105.0, 95.0, 101.0, 5.0]
    assert df["filled"].tolist() == [False, True, False]
    assert df[["open", "close", "volume"]].iloc[1].tolist() == [101.0, 101.0, 0.0]


class FakeSession:
    """Serves Kraken-shaped Trades pages from an in-memory trade list."""

    def __init__(self, trades, page=3, rate_limit_first=False):
        self.trades, self.page, self.rate_limit_first, self.calls = trades, page, rate_limit_first, 0

    def get(self, url, params, timeout):
        self.calls += 1
        if self.rate_limit_first and self.calls == 1:
            return _Resp({"error": ["EGeneral:Too many requests"]})
        if self.rate_limit_first and self.calls == 2:
            raise requests.ConnectionError("proxy closed the connection")
        since_s = params["since"] / 1e9
        rows = [t for t in self.trades if t[0] > since_s][: self.page]
        last = int(rows[-1][0] * 1e9) if rows else params["since"]
        return _Resp({"error": [], "result": {"XXBTZUSD": [[str(p), str(v), ts, "b", "m", "", 1] for ts, p, v in rows], "last": str(last)}})


class _Resp:
    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body


def test_trade_history_pages_until_window_end_and_retries_transient_errors():
    s = T0 / 1000
    trades = [(s + i * 900 + 1, 100.0 + i, 1.0) for i in range(12)]  # 4 trades/hour for 3 hours
    session = FakeSession(trades, page=5, rate_limit_first=True)
    hist = KrakenTradeHistory("BTC/USD", session=session, min_interval_s=0, sleep=lambda _: None)
    df = hist.candles(T0, T0 + 2 * H)

    assert len(df) == 2
    assert df["open"].tolist() == [100.0, 104.0]
    assert df["close"].tolist() == [103.0, 107.0]
    assert session.calls >= 4  # a rate-limit reply and a dropped connection are retried, then paging
