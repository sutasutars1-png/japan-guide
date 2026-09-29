"""Command-line entry point.

    python -m trading_bot.cli <subcommand> [options]

Subcommands: dashboard, bootstrap, fetch-data, backfill, import-csv, data-status, backtest, optimize, paper-trade, self-improve, replay.
Nothing in this CLI places a real exchange order — see README.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from .backtest.engine import BacktestEngine
from .data.fetch import OHLCVFetcher, load_csv
from .optimize.optimizer import WalkForwardOptimizer
from .paper.trader import PaperTrader
from .self_improve.loop import GateConfig, SelfImprovementLoop
from .self_improve.replay import replay
from .strategy import STRATEGIES

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE_DIR = REPO_ROOT / "data_cache"
DEFAULT_STATE_DIR = REPO_ROOT / "state"
# Chosen by `holdout` on the older data (README "7"): margin long/short SMA cross.
DEFAULT_STRATEGY = "sma_crossover_ls"
SEED_DIR = REPO_ROOT / "seed_data"


def _engine(args) -> BacktestEngine:
    return BacktestEngine(
        initial_cash=args.initial_cash, fee_rate=args.fee_rate, slippage_rate=args.slippage_rate,
        order_type=args.order_type, carry_rate_per_day=args.carry_rate_per_day,
    )


def _strategy_cls(name: str):
    try:
        return STRATEGIES[name]
    except KeyError:
        raise SystemExit(f"Unknown strategy '{name}'. Choices: {sorted(STRATEGIES)}")


def _parse_params(raw: str | None) -> dict:
    """JSON (`'{"fast_window": 10}'`) or shell-friendly `fast_window=10,slow_window=50`.

    The key=value form needs no quoting, so the same command works in bash,
    Windows cmd and PowerShell."""
    if not raw:
        return {}
    raw = raw.strip()
    if raw.startswith("{"):
        return json.loads(raw)
    params = {}
    for pair in raw.split(","):
        key, _, value = pair.partition("=")
        for cast in (int, float):
            try:
                params[key.strip()] = cast(value)
                break
            except ValueError:
                continue
        else:
            params[key.strip()] = value.strip()
    return params


def _load_history(args) -> pd.DataFrame:
    if args.csv:
        return load_csv(Path(args.csv))
    fetcher = OHLCVFetcher(exchange_id=args.exchange, cache_dir=Path(args.cache_dir))
    return fetcher.fetch(args.symbol, timeframe=args.timeframe, max_candles=args.max_candles, refresh=args.refresh)


def cmd_fetch_data(args) -> None:
    fetcher = OHLCVFetcher(exchange_id=args.exchange, cache_dir=Path(args.cache_dir))
    df = fetcher.fetch(args.symbol, timeframe=args.timeframe, max_candles=args.max_candles, refresh=True)
    print(f"Merged the latest {args.exchange} candles for {args.symbol} ({args.timeframe}) into the store.")
    print(json.dumps(fetcher.store(args.symbol, args.timeframe).status(), indent=2))
    print(df.tail())


def _store(args):
    from .data.store import OHLCVStore

    return OHLCVStore(Path(args.cache_dir), args.exchange, args.symbol, args.timeframe)


def _backfill(store, exchange: str, symbol: str, days: float, min_interval: float, chunk_days: float) -> None:
    import time as _time

    from .data.kraken_trades import KrakenTradeHistory

    if exchange != "kraken":
        raise SystemExit("backfill currently rebuilds candles from Kraken's public trade history only")
    now_ms = int(_time.time() * 1000)
    end_ms = now_ms - now_ms % store.step_ms  # complete bars only
    start_ms = end_ms - int(days * 86_400_000)
    history = KrakenTradeHistory(symbol, min_interval_s=min_interval)
    ranges = store.missing_ranges(start_ms, end_ms)
    print(f"{len(ranges)} missing range(s), {sum((b - a) // store.step_ms for a, b in ranges)} bars to rebuild", flush=True)
    chunk = int(chunk_days * 86_400_000)
    for a, b in ranges:  # newest first, so stored history extends contiguously backwards
        hi = b
        while hi > a:
            lo = max(a, hi - chunk)
            df = history.candles(lo, hi, store.step_ms)
            filled = df.pop("filled")
            stats = store.merge(df[~filled], source="trades")
            if filled.any():
                store.merge(df[filled], source="gap_fill")
            print(json.dumps({
                "from": pd.Timestamp(lo, unit="ms", tz="UTC").isoformat(),
                "to": pd.Timestamp(hi, unit="ms", tz="UTC").isoformat(),
                "bars": len(df), "gap_filled": int(filled.sum()), "api_calls": history.calls, **stats,
            }), flush=True)
            hi = lo


def _import_file(store, path: Path, fmt: str) -> None:
    from .data.store import OHLCVStore

    if fmt == "kraken-ohlcvt":  # Kraken's bulk OHLCVT download: no header, epoch seconds
        df = pd.read_csv(path, header=None, names=["timestamp", "open", "high", "low", "close", "volume", "trades"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
        print(json.dumps(store.merge(df, source="exchange_csv")))
    elif "source" in pd.read_csv(path, nrows=0).columns:  # another store's CSV (e.g. seed_data/): keep provenance
        src = OHLCVStore(path.parent, "import", "import", store.timeframe)
        src.path = path
        for source, rows in src.load().groupby("source"):
            print(json.dumps({"source": source, **store.merge(rows, source=source)}))
    else:
        print(json.dumps(store.merge(load_csv(path), source="exchange_csv")))


def cmd_backfill(args) -> None:
    store = _store(args)
    _backfill(store, args.exchange, args.symbol, args.days, args.min_interval, args.chunk_days)
    print(json.dumps(store.status(), indent=2))


def cmd_import_csv(args) -> None:
    store = _store(args)
    _import_file(store, Path(args.file), args.format)
    print(json.dumps(store.status(), indent=2))


def cmd_bootstrap(args) -> None:
    """Get a fresh machine to a ready store in one command: seed snapshot ->
    latest official bars -> rebuild whatever is still missing."""
    store = _store(args)
    seed = SEED_DIR / store.path.name
    if seed.exists():
        print(f"[1/3] importing seed snapshot {seed}", flush=True)
        _import_file(store, seed, "ohlcv")
    else:
        print(f"[1/3] no seed snapshot at {seed}; starting from the exchange", flush=True)
    print("[2/3] merging the latest official bars", flush=True)
    OHLCVFetcher(exchange_id=args.exchange, cache_dir=Path(args.cache_dir)).fetch(
        args.symbol, timeframe=args.timeframe, refresh=True
    )
    print(f"[3/3] rebuilding anything missing in the last {args.days:g} days", flush=True)
    _backfill(store, args.exchange, args.symbol, args.days, args.min_interval, args.chunk_days)
    print(json.dumps(store.status(), indent=2))


def cmd_holdout(args) -> None:
    from .research.holdout import run_holdout

    df = _load_history(args)
    from .research.holdout import DEFAULT_GRID

    grid = dict(DEFAULT_GRID, score=args.scores.split(","))
    report = run_holdout(
        df, args.strategy, confirm_bars=int(args.confirm_days * 24), grid=grid, reoptimize_every=args.reoptimize_every,
        fee_rate=args.fee_rate, slippage_rate=args.slippage_rate, order_type=args.order_type,
        carry_rate_per_day=args.carry_rate_per_day, select_by=args.select_by,
        min_walk_forward_score=args.min_walk_forward_score, min_improvement_margin=args.min_improvement_margin,
        workers=args.workers,
    )
    pct = lambda v: f"{v:+.1%}" if v is not None else "n/a"
    print(f"strategy={report.strategy}  confirmation period starts {report.split_timestamp}")
    print(f"chosen on the selection period (by neighbour-averaged {args.select_by}): {report.chosen}")
    print("setting (hist/splits/minT/score) | selection return Sharpe robust | confirm return  Sharpe  maxDD  promo")
    for sel, conf in zip(report.selection, report.confirmation):
        st, m, sm = conf["setting"], conf["metrics"]["self_improving"], sel["metrics"]["self_improving"]
        tag = f"{st['history_candles']}/{st['n_splits']}/{st['min_trades']}/{st['score']}"
        print(f"{tag:>24}{' *' if conf['chosen'] else '  '}      |"
              f" {pct(sm['total_return']):>7} {sm['sharpe']:6.2f} {sel['robust_score']:7.3f} |"
              f" {pct(m['total_return']):>7} {m['sharpe']:6.2f} {pct(m['max_drawdown']):>6} {conf['promotions']:5d}")
    base = report.confirmation[0]["metrics"]
    print(f"confirmation baselines: static {pct(base['static']['total_return'])} (Sharpe {base['static']['sharpe']:.2f}),"
          f" buy&hold {pct(base['buy_hold']['total_return'])} (Sharpe {base['buy_hold']['sharpe']:.2f},"
          f" maxDD {pct(base['buy_hold']['max_drawdown'])})")
    print("chosen setting vs total cost per side:")
    for c in report.cost_sensitivity:
        m = c["metrics"]
        print(f"  {c['cost_per_side']:.2%}: self-improving {pct(m['self_improving']['total_return'])}"
              f" (Sharpe {m['self_improving']['sharpe']:.2f}), static {pct(m['static']['total_return'])}")
    if args.export_json:
        Path(args.export_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.export_json).write_text(json.dumps(report.to_dict(), default=str), encoding="utf-8")
        print(f"wrote {args.export_json}")


def cmd_dashboard(args) -> None:
    from .dashboard.build import build_dashboard

    store = _store(args)
    if args.csv:
        store.path = Path(args.csv)
    out = build_dashboard(store, Path(args.out), Path(args.state_dir), args.exchange, args.symbol, args.strategy)
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")


def cmd_data_status(args) -> None:
    from .data.store import OHLCVStore

    print(json.dumps(OHLCVStore(Path(args.cache_dir), args.exchange, args.symbol, args.timeframe).status(), indent=2))


def cmd_backtest(args) -> None:
    df = _load_history(args)
    strategy_cls = _strategy_cls(args.strategy)
    strategy = strategy_cls(**_parse_params(args.params))
    engine = _engine(args)
    result = engine.run(df, strategy, timeframe=args.timeframe)
    print(f"Strategy: {strategy}")
    print(json.dumps(result.metrics, indent=2))


def cmd_optimize(args) -> None:
    df = _load_history(args)
    strategy_cls = _strategy_cls(args.strategy)
    engine = _engine(args)
    optimizer = WalkForwardOptimizer(engine=engine, n_splits=args.n_splits, min_trades=args.min_trades, score=args.score)
    result = optimizer.optimize(df, strategy_cls, timeframe=args.timeframe)
    print(json.dumps(result.to_dict(), indent=2, default=str))


class CsvReplay:
    """Replays a CSV bar by bar for offline demos. `next_window()` reveals one
    more bar per call (the trader's view); `window()` is everything revealed so
    far, so the optimizer's history can never run ahead of the trader."""

    def __init__(self, df: pd.DataFrame, start: int):
        self.df = df
        self.revealed = min(start - 1, len(df))

    @property
    def remaining(self) -> int:
        return len(self.df) - self.revealed

    def window(self, n: int) -> pd.DataFrame:
        return self.df.iloc[max(0, self.revealed - n) : self.revealed].reset_index(drop=True)

    def next_window(self, n: int) -> pd.DataFrame:
        self.revealed = min(self.revealed + 1, len(self.df))
        return self.window(n)

    def upcoming_window(self, n: int) -> pd.DataFrame:
        """History through the bar the trader will decide on next — what a
        live re-optimization sees, since that bar has closed by then."""
        end = min(self.revealed + 1, len(self.df))
        return self.df.iloc[max(0, end - n) : end].reset_index(drop=True)


def _build_data_provider(args, replay_state: "CsvReplay | None" = None):
    """A zero-arg callable returning the latest OHLCV window for one step.

    With `--csv`, replays the file bar-by-bar instead of hitting the network —
    this is what lets paper-trade/self-improve be demoed and tested with no
    exchange access.
    """
    if args.csv:
        replay_state = replay_state or CsvReplay(load_csv(Path(args.csv)), start=args.window)
        return lambda: replay_state.next_window(args.window)

    fetcher = OHLCVFetcher(exchange_id=args.exchange, cache_dir=Path(args.cache_dir))

    def live_provider() -> pd.DataFrame:
        return fetcher.fetch(
            args.symbol,
            timeframe=args.timeframe,
            max_candles=args.window,
            refresh=True,  # merge the newest bars into the accumulating store
        )

    return live_provider


def cmd_paper_trade(args) -> None:
    strategy_cls = _strategy_cls(args.strategy)
    trader = PaperTrader(
        symbol=args.symbol,
        strategy_cls=strategy_cls,
        params=_parse_params(args.params),
        data_provider=_build_data_provider(args),
        state_dir=Path(args.state_dir),
        timeframe=args.timeframe,
        initial_cash=args.initial_cash,
        fee_rate=args.fee_rate,
        slippage_rate=args.slippage_rate,
        order_type=args.order_type,
        carry_rate_per_day=args.carry_rate_per_day,
    )
    iterations = None if args.iterations <= 0 else args.iterations
    for record in trader.run_loop(iterations=iterations, sleep_seconds=args.sleep_seconds):
        print(json.dumps(record, default=str))


def cmd_self_improve(args) -> None:
    strategy_cls = _strategy_cls(args.strategy)
    csv_replay = None
    if args.csv:
        # Start once enough bars exist for the first re-optimization.
        csv_replay = CsvReplay(load_csv(Path(args.csv)), start=max(args.window, args.history_candles))
    trader = PaperTrader(
        symbol=args.symbol,
        strategy_cls=strategy_cls,
        params=_parse_params(args.params),
        data_provider=_build_data_provider(args, csv_replay),
        state_dir=Path(args.state_dir),
        timeframe=args.timeframe,
        initial_cash=args.initial_cash,
        fee_rate=args.fee_rate,
        slippage_rate=args.slippage_rate,
        order_type=args.order_type,
        carry_rate_per_day=args.carry_rate_per_day,
    )

    if csv_replay is not None:

        def history_provider() -> pd.DataFrame:
            # Ends at the bar the trader is about to decide on, never later.
            return csv_replay.upcoming_window(args.history_candles)

    else:
        fetcher = OHLCVFetcher(exchange_id=args.exchange, cache_dir=Path(args.cache_dir))

        def history_provider() -> pd.DataFrame:
            return fetcher.fetch(
                args.symbol,
                timeframe=args.timeframe,
                max_candles=args.history_candles,
                refresh=True,
            )

    loop = SelfImprovementLoop(
        trader=trader,
        optimizer=WalkForwardOptimizer(
            engine=_engine(args),
            n_splits=args.n_splits,
            min_trades=args.min_trades,
            score=args.score,
        ),
        strategy_cls=strategy_cls,
        history_provider=history_provider,
        state_dir=Path(args.state_dir),
        timeframe=args.timeframe,
        min_walk_forward_score=args.min_walk_forward_score,
        min_improvement_margin=args.min_improvement_margin,
    )

    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "run_config.json").write_text(json.dumps({
        "strategy": args.strategy, "params": dict(trader.strategy.params), "exchange": args.exchange,
        "symbol": args.symbol, "timeframe": args.timeframe, "history_candles": args.history_candles,
        "reoptimize_every": args.reoptimize_every, "n_splits": args.n_splits, "min_trades": args.min_trades,
        "min_walk_forward_score": args.min_walk_forward_score, "min_improvement_margin": args.min_improvement_margin,
        "fee_rate": args.fee_rate, "slippage_rate": args.slippage_rate, "score": args.score,
        "order_type": args.order_type, "carry_rate_per_day": args.carry_rate_per_day,
    }, indent=2), encoding="utf-8")

    def refresh_dashboard():
        if not args.dashboard_out:
            return
        from .dashboard.build import build_dashboard

        try:
            store = OHLCVFetcher(exchange_id=args.exchange, cache_dir=Path(args.cache_dir)).store(args.symbol, args.timeframe)
            if args.csv:
                store.path = Path(args.csv)
            build_dashboard(store, Path(args.dashboard_out), state_dir, args.exchange, args.symbol, args.strategy)
        except Exception as exc:  # a report must never stop the trading loop
            print(json.dumps({"event": "dashboard_error", "error": str(exc)}), flush=True)

    steps = None if args.steps <= 0 else args.steps
    if csv_replay is not None:  # a finite file: stop at its end instead of waiting for bars forever
        steps = csv_replay.remaining if steps is None else min(steps, csv_replay.remaining)
    for event in loop.run_schedule(
        steps=steps, step_seconds=args.step_seconds, reoptimize_every=args.reoptimize_every
    ):
        print(json.dumps(event, default=str), flush=True)
        if event["event"] == "reoptimize":
            refresh_dashboard()  # the daily summary: rebuilt once per re-optimization cycle
    refresh_dashboard()


def cmd_replay(args) -> None:
    df = _load_history(args)
    strategy_cls = _strategy_cls(args.strategy)
    result = replay(
        df,
        strategy_cls,
        initial_params=dict(strategy_cls(**_parse_params(args.params)).params),
        optimizer=WalkForwardOptimizer(
            engine=_engine(args),
            n_splits=args.n_splits,
            min_trades=args.min_trades,
            score=args.score,
        ),
        gate=GateConfig(args.min_walk_forward_score, args.min_improvement_margin),
        history_candles=args.history_candles,
        reoptimize_every=args.reoptimize_every,
        timeframe=args.timeframe,
    )
    promoted = sum(1 for c in result.cycles if c["promoted"])
    print(f"{len(result.cycles)} cycles, {promoted} promotions; final active params: {result.params_list[result.active_by_bar[-1]]}")
    for name, m in result.metrics.items():
        print(f"  {name:15s} return={m['total_return']:+.4f} sharpe={m['sharpe']} max_dd={m['max_drawdown']:+.4f} trades={m['num_trades']}")
    if args.export_json:
        out = Path(args.export_json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result.to_dict()), encoding="utf-8")
        print(f"wrote {out}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trading-bot", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_data_args(p, window_default=None, window_help=""):
        p.add_argument("--exchange", default="kraken")
        p.add_argument("--symbol", default="BTC/USD")
        p.add_argument("--timeframe", default="1h")
        p.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
        p.add_argument("--csv", default=None, help="load OHLCV from this CSV instead of fetching")
        if window_default is not None:
            p.add_argument("--window", type=int, default=window_default, help=window_help)

    fd = sub.add_parser("fetch-data", help="Fetch the latest candles and merge them into the stored history")
    add_data_args(fd)
    fd.add_argument("--max-candles", type=int, default=2000)
    fd.set_defaults(func=cmd_fetch_data)

    bf = sub.add_parser("backfill", help="Rebuild older candles from the exchange's public trade history")
    add_data_args(bf)
    bf.add_argument("--days", type=float, default=180, help="how far back the store should reach")
    bf.add_argument("--chunk-days", type=float, default=2, help="merge into the store after every N days rebuilt")
    bf.add_argument("--min-interval", type=float, default=1.0, help="seconds between API calls")
    bf.set_defaults(func=cmd_backfill)

    bs = sub.add_parser("bootstrap", help="One-command data setup: seed snapshot + latest bars + backfill of gaps")
    add_data_args(bs)
    bs.add_argument("--days", type=float, default=180, help="how far back the store should reach")
    bs.add_argument("--chunk-days", type=float, default=4)
    bs.add_argument("--min-interval", type=float, default=1.0, help="seconds between API calls")
    bs.set_defaults(func=cmd_bootstrap)

    ic = sub.add_parser("import-csv", help="Merge an OHLCV CSV (e.g. Kraken's OHLCVT download) into the store")
    add_data_args(ic)
    ic.add_argument("--file", required=True)
    ic.add_argument("--format", choices=["ohlcv", "kraken-ohlcvt"], default="ohlcv")
    ic.set_defaults(func=cmd_import_csv)

    ho = sub.add_parser("holdout", help="Choose self-improvement rules on older data, confirm on the newest period")
    add_data_args(ho)
    ho.add_argument("--strategy", default=DEFAULT_STRATEGY, choices=sorted(STRATEGIES))
    ho.add_argument("--max-candles", type=int, default=100_000)
    ho.add_argument("--refresh", action="store_true")
    ho.add_argument("--confirm-days", type=float, default=240)
    ho.add_argument("--reoptimize-every", type=int, default=24)
    ho.add_argument("--fee-rate", type=float, default=0.0002)
    ho.add_argument("--slippage-rate", type=float, default=0.0)
    ho.add_argument("--order-type", choices=["limit", "market"], default="limit")
    ho.add_argument("--carry-rate-per-day", type=float, default=0.0004)
    ho.add_argument("--scores", default="sharpe,return", help="optimizer objectives to include in the grid")
    ho.add_argument("--select-by", choices=["return", "sharpe"], default="return")
    ho.add_argument("--min-walk-forward-score", type=float, default=0.0)
    ho.add_argument("--min-improvement-margin", type=float, default=0.05)
    ho.add_argument("--workers", type=int, default=4)
    ho.add_argument("--export-json", default=None)
    ho.set_defaults(func=cmd_holdout)

    db = sub.add_parser("dashboard", help="Build the self-contained dashboard HTML (replay + live paper trading)")
    add_data_args(db)
    db.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR))
    db.add_argument("--strategy", default=None, choices=sorted(STRATEGIES), help="live strategy (default: from run_config.json)")
    db.add_argument("--out", default=str(DEFAULT_STATE_DIR / "dashboard.html"))
    db.set_defaults(func=cmd_dashboard)

    ds = sub.add_parser("data-status", help="Show how much history the store holds")
    add_data_args(ds)
    ds.set_defaults(func=cmd_data_status)

    bt = sub.add_parser("backtest", help="Run a single backtest")
    add_data_args(bt)
    bt.add_argument("--max-candles", type=int, default=2000)
    bt.add_argument("--refresh", action="store_true")
    bt.add_argument("--strategy", default=DEFAULT_STRATEGY, choices=sorted(STRATEGIES))
    bt.add_argument("--params", default=None, help='JSON, e.g. \'{"fast_window": 10, "slow_window": 50}\'')
    bt.add_argument("--initial-cash", type=float, default=10_000.0)
    bt.add_argument("--fee-rate", type=float, default=0.0002, help="per-side fee (default: 0.02%% limit/maker)")
    bt.add_argument("--slippage-rate", type=float, default=0.0, help="per-side spread/impact (market orders)")
    bt.add_argument("--order-type", choices=["limit", "market"], default="limit",
                       help="limit: fills only if the next bar trades through the close")
    bt.add_argument("--carry-rate-per-day", type=float, default=0.0004, help="margin carry on open positions")
    bt.set_defaults(func=cmd_backtest)

    opt = sub.add_parser("optimize", help="Walk-forward grid search for strategy parameters")
    add_data_args(opt)
    opt.add_argument("--max-candles", type=int, default=3000)
    opt.add_argument("--refresh", action="store_true")
    opt.add_argument("--strategy", default=DEFAULT_STRATEGY, choices=sorted(STRATEGIES))
    opt.add_argument("--initial-cash", type=float, default=10_000.0)
    opt.add_argument("--fee-rate", type=float, default=0.0002, help="per-side fee (default: 0.02%% limit/maker)")
    opt.add_argument("--slippage-rate", type=float, default=0.0, help="per-side spread/impact (market orders)")
    opt.add_argument("--order-type", choices=["limit", "market"], default="limit",
                       help="limit: fills only if the next bar trades through the close")
    opt.add_argument("--carry-rate-per-day", type=float, default=0.0004, help="margin carry on open positions")
    opt.add_argument("--n-splits", type=int, default=4)
    opt.add_argument("--min-trades", type=int, default=5)
    opt.add_argument("--score", choices=["sharpe", "return"], default="sharpe")
    opt.set_defaults(func=cmd_optimize)

    pt = sub.add_parser("paper-trade", help="Run the (simulated-only) paper trading loop")
    add_data_args(pt, window_default=300, window_help="how many recent candles to keep for signal calc")
    pt.add_argument("--strategy", default=DEFAULT_STRATEGY, choices=sorted(STRATEGIES))
    pt.add_argument("--params", default=None, help="JSON params for the strategy")
    pt.add_argument("--initial-cash", type=float, default=10_000.0)
    pt.add_argument("--fee-rate", type=float, default=0.0002, help="per-side fee (default: 0.02%% limit/maker)")
    pt.add_argument("--slippage-rate", type=float, default=0.0, help="per-side spread/impact (market orders)")
    pt.add_argument("--order-type", choices=["limit", "market"], default="limit",
                       help="limit: fills only if the next bar trades through the close")
    pt.add_argument("--carry-rate-per-day", type=float, default=0.0004, help="margin carry on open positions")
    pt.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR))
    pt.add_argument("--iterations", type=int, default=1, help="0 = run forever")
    pt.add_argument("--sleep-seconds", type=float, default=60.0)
    pt.set_defaults(func=cmd_paper_trade)

    def add_gate_args(p, history_default):
        p.add_argument("--strategy", default=DEFAULT_STRATEGY, choices=sorted(STRATEGIES))
        p.add_argument("--params", default=None, help="JSON starting params for the strategy")
        p.add_argument("--initial-cash", type=float, default=10_000.0)
        p.add_argument("--fee-rate", type=float, default=0.0002, help="per-side fee (default: 0.02%% limit/maker)")
        p.add_argument("--slippage-rate", type=float, default=0.0, help="per-side spread/impact (market orders)")
        p.add_argument("--order-type", choices=["limit", "market"], default="limit",
                           help="limit: fills only if the next bar trades through the close")
        p.add_argument("--carry-rate-per-day", type=float, default=0.0004, help="margin carry on open positions")
        p.add_argument("--n-splits", type=int, default=3)
        p.add_argument("--min-trades", type=int, default=5,
                       help="closed trades a fold needs before its score counts")
        p.add_argument("--history-candles", type=int, default=history_default,
                       help="trailing bars each re-optimization sees")
        p.add_argument("--reoptimize-every", type=int, default=24, help="re-optimize every N bars")
        p.add_argument("--score", choices=["sharpe", "return"], default="sharpe",
                       help="what the walk-forward optimizer maximizes (annualized)")
        p.add_argument("--min-walk-forward-score", type=float, default=0.0)
        p.add_argument("--min-improvement-margin", type=float, default=0.05)

    si = sub.add_parser("self-improve", help="Run the self-improving system: trade every bar, re-optimize on a schedule")
    add_data_args(si, window_default=300, window_help="how many recent candles to keep for signal calc")
    add_gate_args(si, history_default=720)
    si.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR))
    si.add_argument("--steps", type=int, default=1, help="bars to run; 0 = run forever")
    si.add_argument("--step-seconds", type=float, default=3600.0, help="wall-clock seconds per bar")
    si.add_argument("--dashboard-out", default=None, help="rebuild this dashboard HTML after every re-optimization")
    si.set_defaults(func=cmd_self_improve)

    rp = sub.add_parser("replay", help="Backtest the self-improving system itself over history")
    add_data_args(rp)
    add_gate_args(rp, history_default=720)
    rp.add_argument("--max-candles", type=int, default=100_000)
    rp.add_argument("--refresh", action="store_true")
    rp.add_argument("--export-json", default=None, help="write the full replay (cycles, equity) as JSON")
    rp.set_defaults(func=cmd_replay)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
