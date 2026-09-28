"""OHLCV market data: fetch from a public exchange API and/or load from CSV cache.

Only public market-data endpoints are used (no API key, no order placement).
`ccxt` is imported lazily so the rest of the package works without it installed
(e.g. in tests that only exercise cached/offline data).
"""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]

DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[2] / "data_cache"


def cache_path(exchange_id: str, symbol: str, timeframe: str, cache_dir: Path = DEFAULT_CACHE_DIR) -> Path:
    safe_symbol = symbol.replace("/", "-")
    return cache_dir / f"{exchange_id}_{safe_symbol}_{timeframe}.csv"


def load_csv(path: Path) -> pd.DataFrame:
    """Load a previously cached (or hand-provided) OHLCV CSV.

    Expected columns: timestamp (ms epoch or ISO string), open, high, low, close, volume.
    """
    df = pd.read_csv(path)
    missing = [c for c in OHLCV_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{path} is missing OHLCV columns: {missing}")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, unit="ms" if pd.api.types.is_numeric_dtype(df["timestamp"]) else None)
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df[OHLCV_COLUMNS]


def save_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    epoch = pd.Timestamp("1970-01-01", tz="UTC")
    # Resolution-independent: pandas' datetime64 unit (ns/us/etc.) varies by
    # version, so int64-casting the column directly is NOT a safe way to get
    # ms-since-epoch — divide by an explicit Timedelta instead.
    out["timestamp"] = (out["timestamp"] - epoch) // pd.Timedelta(milliseconds=1)
    out.to_csv(path, index=False)


class OHLCVFetcher:
    """Fetches public OHLCV candles from a crypto exchange via ccxt.

    Keyless and read-only: only `fetch_ohlcv` (public market data) is ever
    called on the exchange client. This class never places, cancels, or
    queries orders — it has no code path that could touch a real account.
    """

    def __init__(self, exchange_id: str = "binance", cache_dir: Path = DEFAULT_CACHE_DIR):
        self.exchange_id = exchange_id
        self.cache_dir = Path(cache_dir)
        self._exchange = None

    def _get_exchange(self):
        if self._exchange is None:
            import os

            import ccxt  # lazy import — optional dependency

            exchange_cls = getattr(ccxt, self.exchange_id)
            self._exchange = exchange_cls({"enableRateLimit": True})
            # ccxt's requests.Session is built with trust_env=False, so it
            # ignores REQUESTS_CA_BUNDLE/SSL_CERT_FILE — fine on a normal
            # network, but breaks under a TLS-intercepting egress proxy
            # (e.g. this sandbox's), which presents its own CA. Point it at
            # the same CA bundle other tools already trust, if one is set.
            #
            # ccxt.Exchange.fetch() passes `verify=self.verify and
            # self.validateServerSsl` to requests — since self.verify is the
            # boolean True by default, that `and` discards a CA-bundle path
            # assigned to `.session.verify` or `.verify` and evaluates to
            # plain `True`. Assigning the path to `validateServerSsl`
            # instead is what actually survives that expression.
            ca_bundle = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
            if ca_bundle:
                self._exchange.session.verify = ca_bundle
                self._exchange.validateServerSsl = ca_bundle
        return self._exchange

    def store(self, symbol: str, timeframe: str):
        from .store import OHLCVStore

        return OHLCVStore(self.cache_dir, self.exchange_id, symbol, timeframe)

    def fetch(
        self,
        symbol: str,
        timeframe: str = "1h",
        since_ms: int | None = None,
        limit_per_call: int = 1000,
        max_candles: int = 5000,
        use_cache: bool = True,
        refresh: bool = False,
    ) -> pd.DataFrame:
        """Return the newest `max_candles` bars, accumulating history on disk.

        With `use_cache`, newly downloaded candles are merged into the
        persistent store (never replacing older stored history) and the
        result comes from the store, so history grows beyond what the
        exchange serves in one request. Without `refresh`, an existing store
        is returned as-is with no network call.
        """
        store = self.store(symbol, timeframe)
        if use_cache and not refresh and store.path.exists():
            return store.ohlcv(tail=max_candles)

        df = self._download(symbol, timeframe, since_ms, limit_per_call, max_candles)
        if not use_cache:
            return df
        store.merge(df, source="exchange_ohlc")
        return store.ohlcv(tail=max_candles)

    def _download(self, symbol: str, timeframe: str, since_ms, limit_per_call: int, max_candles: int) -> pd.DataFrame:
        exchange = self._get_exchange()
        all_rows: list[list] = []
        cursor = since_ms
        while len(all_rows) < max_candles:
            batch = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=cursor, limit=limit_per_call)
            if not batch:
                break
            all_rows.extend(batch)
            last_ts = batch[-1][0]
            if cursor is not None and last_ts <= cursor:
                break
            cursor = last_ts + 1
            if len(batch) < limit_per_call:
                break
            time.sleep(exchange.rateLimit / 1000.0)

        if not all_rows:
            raise RuntimeError(f"No OHLCV data returned for {symbol} on {self.exchange_id}")

        df = pd.DataFrame(all_rows, columns=OHLCV_COLUMNS)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df = df.drop_duplicates(subset="timestamp").sort_values("timestamp").reset_index(drop=True)
        return df.tail(max_candles).reset_index(drop=True)
