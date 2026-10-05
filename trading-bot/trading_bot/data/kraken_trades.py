"""Rebuild historical Kraken candles from its public trade history.

Kraken's OHLC endpoint only serves the latest ~720 bars, but its public
`Trades` endpoint pages back through the full trade history (1000 trades
per call, cursor = the response's `last`). Aggregating those trades into
bars reproduces what the OHLC endpoint would have returned for older
periods, from the same venue. Read-only and keyless like the rest of
`data/`: only the public Trades endpoint is called.
"""
from __future__ import annotations

import time
from typing import Callable, Optional

import pandas as pd
import requests

API_URL = "https://api.kraken.com/0/public/Trades"
KRAKEN_PAIRS = {"BTC/USD": "XBTUSD", "ETH/USD": "ETHUSD", "BTC/EUR": "XBTEUR", "ETH/EUR": "ETHEUR"}
RETRYABLE = ("EAPI:Rate limit exceeded", "EGeneral:Too many requests", "EService:Unavailable", "EService:Busy")


def aggregate_trades(trades: list[tuple[float, float, float]], start_ms: int, end_ms: int, step_ms: int) -> pd.DataFrame:
    """Bucket (time_sec, price, volume) trades, in time order, into bars covering
    [start_ms, end_ms). Bars with no trades carry the previous close forward
    with zero volume and are flagged `filled` (a leading empty bar has no
    previous close and is dropped)."""
    buckets: dict[int, list[float]] = {}
    for ts, price, vol in trades:
        ms = int(ts * 1000)
        if ms < start_ms or ms >= end_ms:
            continue
        key = ms - ms % step_ms
        b = buckets.get(key)
        if b is None:
            buckets[key] = [price, price, price, price, vol]
        else:
            b[1] = max(b[1], price)
            b[2] = min(b[2], price)
            b[3] = price
            b[4] += vol

    rows, prev_close = [], None
    for key in range(start_ms - start_ms % step_ms, end_ms, step_ms):
        b = buckets.get(key)
        if b is not None:
            rows.append((key, *b, False))
            prev_close = b[3]
        elif prev_close is not None:
            rows.append((key, prev_close, prev_close, prev_close, prev_close, 0.0, True))
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume", "filled"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df


class KrakenTradeHistory:
    def __init__(
        self,
        symbol: str,
        session: Optional[requests.Session] = None,
        min_interval_s: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if symbol not in KRAKEN_PAIRS:
            raise ValueError(f"no Kraken pair mapping for {symbol}; add it to KRAKEN_PAIRS")
        self.pair = KRAKEN_PAIRS[symbol]
        self.session = session or requests.Session()  # honours REQUESTS_CA_BUNDLE
        self.min_interval_s = min_interval_s
        self.sleep = sleep
        self.calls = 0

    def _get(self, since_ns: int) -> tuple[list, int]:
        backoff = 5.0
        failures = 0
        while True:
            try:
                resp = self.session.get(API_URL, params={"pair": self.pair, "since": since_ns, "count": 1000}, timeout=30)
                body = resp.json()
            except (requests.RequestException, ValueError):
                # Dropped connections / proxy hiccups / non-JSON error pages are
                # transient on a multi-hour backfill; retry rather than abort.
                failures += 1
                if failures > 8:
                    raise
                self.sleep(backoff)
                backoff = min(backoff * 2, 120.0)
                continue
            self.calls += 1
            errors = body.get("error") or []
            if not errors:
                result = body["result"]
                key = next(k for k in result if k != "last")
                return result[key], int(result["last"])
            if any(e.startswith(RETRYABLE) for e in errors):
                self.sleep(backoff)
                backoff = min(backoff * 2, 120.0)
                continue
            raise RuntimeError(f"Kraken Trades error: {errors}")

    def candles(
        self,
        start_ms: int,
        end_ms: int,
        step_ms: int = 3_600_000,
        on_progress: Optional[Callable[[int], None]] = None,
    ) -> pd.DataFrame:
        """Bars for [start_ms, end_ms), built from every trade in that window."""
        trades: list[tuple[float, float, float]] = []
        cursor = start_ms * 1_000_000
        while True:
            batch, last = self._get(cursor)
            done = not batch or last <= cursor
            for row in batch:
                ts = float(row[2])
                if ts * 1000 >= end_ms:
                    done = True
                    break
                trades.append((ts, float(row[0]), float(row[1])))
            if on_progress and trades:
                on_progress(int(trades[-1][0] * 1000))
            if done:
                break
            cursor = last
            self.sleep(self.min_interval_s)
        return aggregate_trades(trades, start_ms, end_ms, step_ms)
