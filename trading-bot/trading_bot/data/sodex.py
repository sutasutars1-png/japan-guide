"""Read-only client for SoDEX's public market data (perpetuals).

SoDEX is an on-chain order-book exchange on ValueChain. Its gateway serves
market data without any key; this module only ever sends unauthenticated GET
requests to the public `markets` endpoints. It holds no private key, signs
nothing and has no code path that could place, cancel or query an order or
an account — the same rule as the rest of this project (paper trading only,
ROADMAP principle 1).

It exposes the small part of the ccxt interface `OHLCVFetcher` uses
(`fetch_ohlcv`, `rateLimit`), so the store, the paper trader, the
self-improvement loop and the dashboard work with `--exchange sodex`
unchanged. Endpoints and response shapes follow the official SDK
(github.com/sodex-tech/sodex-python-sdk-public):

    GET {base}/api/v1/perps/markets/{symbol}/klines?interval=1h&startTime=..&limit=..
    GET {base}/api/v1/perps/markets/tickers?symbol=..
    GET {base}/api/v1/perps/markets/symbols?symbol=..

Every response is wrapped as {"code": 0, "message": .., "data": ..}.
The perpetual for BTC is `BTC-USD` on mainnet.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

import requests

BASE_URLS = {
    "mainnet": "https://mainnet-gw.sodex.dev",
    "testnet": "https://testnet-gw.sodex.dev",
}
PERPS = "/api/v1/perps"
MAX_KLINES = 1500  # per request, per the gateway
# ccxt-style timeframes -> SoDEX intervals (daily and longer are upper-case)
INTERVALS = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h", "4h": "4h", "1d": "1D"}


class SodexAPIError(RuntimeError):
    def __init__(self, code: int, message: str):
        super().__init__(f"SoDEX API error {code}: {message}")
        self.code = code


class SodexPublic:
    """Unauthenticated SoDEX market-data client with a ccxt-like `fetch_ohlcv`."""

    rateLimit = 250  # ms between paginated calls; the public limits are generous
    needs_since_for_depth = True  # without startTime the gateway returns only the newest page

    def __init__(self, network: str = "mainnet", session: Optional[requests.Session] = None, timeout: float = 10.0):
        if network not in BASE_URLS:
            raise ValueError(f"network must be one of {sorted(BASE_URLS)}")
        self.network = network
        self.base_url = BASE_URLS[network]
        self.session = session or requests.Session()
        self.timeout = timeout

    def _get(self, path: str, params: Optional[dict] = None) -> Any:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        resp = self.session.get(self.base_url + path, params=params, timeout=self.timeout,
                                headers={"Accept": "application/json"})
        try:
            body = resp.json()
        except ValueError:
            body = None
        if isinstance(body, dict) and body.get("code") not in (None, 0):
            raise SodexAPIError(int(body["code"]), str(body.get("message") or body.get("msg") or body))
        if not 200 <= resp.status_code < 300:
            raise RuntimeError(f"SoDEX HTTP {resp.status_code} for {path}: {getattr(resp, 'text', '')[:200]}")
        return body.get("data") if isinstance(body, dict) else body

    # ---- ccxt-compatible ----
    def fetch_ohlcv(self, symbol: str, timeframe: str = "1h", since: Optional[int] = None,
                    limit: Optional[int] = None) -> list[list[float]]:
        """[[open_time_ms, open, high, low, close, base_volume], ...], oldest first."""
        if timeframe not in INTERVALS:
            raise ValueError(f"timeframe {timeframe!r} not supported; use one of {sorted(INTERVALS)}")
        params = {"interval": INTERVALS[timeframe], "startTime": since,
                  "limit": min(limit or MAX_KLINES, MAX_KLINES)}
        rows = self._get(f"{PERPS}/markets/{symbol}/klines", params) or []
        out = [[int(r["t"]), float(r["o"]), float(r["h"]), float(r["l"]), float(r["c"]), float(r.get("v") or 0.0)]
               for r in rows]
        return sorted(out, key=lambda r: r[0])

    # ---- extra read-only views used by `exchange-check` and the decision log ----
    def ticker(self, symbol: str) -> dict:
        rows = self._get(f"{PERPS}/markets/tickers", {"symbol": symbol}) or []
        row = next((r for r in rows if r.get("symbol") == symbol), None)
        if row is None:
            raise SodexAPIError(-1, f"no ticker for {symbol}")
        return {
            "symbol": symbol,
            "last": _num(row.get("lastPx")),
            "bid": _num(row.get("bidPx")),
            "ask": _num(row.get("askPx")),
            "mark": _num(row.get("markPrice")),
            "index": _num(row.get("indexPrice")),
            "funding_rate": _num(row.get("fundingRate")),
            "open_interest": _num(row.get("openInterest")),
            "quote_volume_24h": _num(row.get("quoteVolume")),
        }

    def market(self, symbol: str) -> dict:
        rows = self._get(f"{PERPS}/markets/symbols", {"symbol": symbol}) or []
        row = next((r for r in rows if r.get("name") == symbol), None)
        if row is None:
            raise SodexAPIError(-1, f"no market {symbol}")
        return {
            "symbol": symbol,
            "status": row.get("status"),
            "maker_fee": _num(row.get("makerFee")),
            "taker_fee": _num(row.get("takerFee")),
            "tick_size": _num(row.get("tickSize")),
            "step_size": _num(row.get("stepSize")),
            "min_notional": _num(row.get("minNotional")),
            "max_leverage": row.get("maxLeverage"),
        }


def _num(v) -> Optional[float]:
    if v in (None, ""):
        return None
    return float(Decimal(str(v)))
