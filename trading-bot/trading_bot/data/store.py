"""Persistent, accumulating OHLCV store (one CSV per exchange/symbol/timeframe).

Exchanges cap how far back their candle endpoint reaches (Kraken's OHLC
returns only the latest ~720 bars), so history has to be *kept*, not
re-downloaded: every fetch is merged into this store instead of replacing
it, and older gaps can be backfilled from other sources (see
`kraken_trades`). Each row records where it came from; on overlapping
timestamps a row only replaces an existing one from an equal-or-lower
priority source, so e.g. trade-reconstructed candles never overwrite the
exchange's own candles.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

try:
    import fcntl
except ImportError:  # Windows: merges are not serialized across processes
    fcntl = None

from .fetch import OHLCV_COLUMNS, cache_path

SOURCE_PRIORITY = {
    "exchange_ohlc": 3,     # the exchange's own candle endpoint
    "exchange_csv": 3,      # the exchange's official bulk OHLCVT download
    "trades": 2,            # candles aggregated from the exchange's public trade history
    "gap_fill": 1,          # an hour with no trades: previous close carried forward, zero volume
}

TIMEFRAME_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


def _to_ms(ts: pd.Series) -> pd.Series:
    epoch = pd.Timestamp("1970-01-01", tz="UTC")
    return (ts - epoch) // pd.Timedelta(milliseconds=1)


class OHLCVStore:
    def __init__(self, cache_dir: Path, exchange_id: str, symbol: str, timeframe: str):
        if timeframe not in TIMEFRAME_MS:
            raise ValueError(f"unsupported timeframe {timeframe!r}")
        self.path = cache_path(exchange_id, symbol, timeframe, Path(cache_dir))
        self.timeframe = timeframe
        self.step_ms = TIMEFRAME_MS[timeframe]

    def load(self) -> pd.DataFrame:
        """All stored rows, oldest first, with a `source` column."""
        if not self.path.exists():
            empty = pd.DataFrame(columns=OHLCV_COLUMNS + ["source"])
            empty["timestamp"] = pd.to_datetime(empty["timestamp"], utc=True)
            return empty
        df = pd.read_csv(self.path)
        if "source" not in df.columns:  # cache files written before the store existed
            df["source"] = "exchange_ohlc"
        unit = "ms" if pd.api.types.is_numeric_dtype(df["timestamp"]) else None
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, unit=unit)
        return df.sort_values("timestamp").reset_index(drop=True)[OHLCV_COLUMNS + ["source"]]

    def ohlcv(self, tail: int | None = None) -> pd.DataFrame:
        df = self.load()[OHLCV_COLUMNS]
        return (df.tail(tail) if tail else df).reset_index(drop=True)

    def merge(self, new: pd.DataFrame, source: str) -> dict:
        """Merge `new` candles tagged `source`; returns counts of added/replaced/kept rows.

        Serialized with an exclusive file lock, so a running bot and a
        backfill can both write the same store without losing rows."""
        if source not in SOURCE_PRIORITY:
            raise ValueError(f"unknown source {source!r}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path.with_suffix(".lock"), "w") as lock:
            if fcntl is not None:
                fcntl.flock(lock, fcntl.LOCK_EX)
            return self._merge_locked(new, source)

    def _merge_locked(self, new: pd.DataFrame, source: str) -> dict:
        new = new[OHLCV_COLUMNS].copy()
        new["timestamp"] = pd.to_datetime(new["timestamp"], utc=True)
        new["source"] = source
        old = self.load()

        prio_new = SOURCE_PRIORITY[source]
        old_idx = old.set_index("timestamp")
        overlap = new["timestamp"].isin(old_idx.index)
        if overlap.any():
            old_prio = old_idx.loc[new.loc[overlap, "timestamp"], "source"].map(SOURCE_PRIORITY).to_numpy()
            replace_mask = overlap.copy()
            replace_mask[overlap] = old_prio <= prio_new
        else:
            replace_mask = overlap
        take = new[~overlap | replace_mask]

        merged = pd.concat([old[~old["timestamp"].isin(take["timestamp"])], take], ignore_index=True)
        merged = merged.sort_values("timestamp").reset_index(drop=True)
        self._write(merged)
        return {
            "added": int((~overlap).sum()),
            "replaced": int(replace_mask.sum()),
            "kept_existing": int((overlap & ~replace_mask).sum()),
            "total": len(merged),
        }

    def _write(self, df: pd.DataFrame) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        out = df.copy()
        out["timestamp"] = _to_ms(out["timestamp"])
        tmp = self.path.with_suffix(".tmp")
        out.to_csv(tmp, index=False)
        tmp.replace(self.path)

    def missing_ranges(self, start_ms: int, end_ms: int) -> list[tuple[int, int]]:
        """Half-open [start, end) ms ranges of absent bars within [start_ms, end_ms), newest first."""
        start_ms -= start_ms % self.step_ms
        have = set(_to_ms(self.load()["timestamp"]).tolist())
        ranges: list[tuple[int, int]] = []
        run_start = None
        t = start_ms
        while t < end_ms:
            if t not in have:
                if run_start is None:
                    run_start = t
            elif run_start is not None:
                ranges.append((run_start, t))
                run_start = None
            t += self.step_ms
        if run_start is not None:
            ranges.append((run_start, t))
        return ranges[::-1]

    def status(self) -> dict:
        df = self.load()
        if df.empty:
            return {"path": str(self.path), "bars": 0}
        ms = _to_ms(df["timestamp"])
        span = int((ms.iloc[-1] - ms.iloc[0]) // self.step_ms) + 1
        return {
            "path": str(self.path),
            "bars": len(df),
            "first": df["timestamp"].iloc[0].isoformat(),
            "last": df["timestamp"].iloc[-1].isoformat(),
            "days": round(span * self.step_ms / 86_400_000, 1),
            "missing_bars_inside": span - len(df),
            "by_source": df["source"].value_counts().to_dict(),
        }
