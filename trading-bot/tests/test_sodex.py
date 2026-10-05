import json

import pytest

from trading_bot.data.fetch import OHLCVFetcher
from trading_bot.data.sodex import SodexAPIError, SodexPublic

HOUR = 3_600_000
NOW = 1_790_000_000_000 // HOUR * HOUR + 600_000  # 10 minutes into an hour


class FakeResponse:
    def __init__(self, body, status=200):
        self.status_code, self._body, self.text = status, body, json.dumps(body)

    def json(self):
        return self._body


class FakeGateway:
    """Serves SoDEX-shaped responses: klines ascending from startTime (or the newest page)."""

    def __init__(self, n_bars=3000, page=1500, now=NOW):
        self.first = now // HOUR * HOUR - (n_bars - 1) * HOUR  # the last bar is the one still forming
        self.n, self.page, self.calls = n_bars, page, []

    def bar(self, i):
        t = self.first + i * HOUR
        return {"t": t, "o": str(100 + i), "h": str(101 + i), "l": str(99 + i), "c": str(100.5 + i), "v": "2.5", "q": "250"}

    def get(self, url, params=None, timeout=None, headers=None):
        self.calls.append((url, dict(params or {})))
        if url.endswith("/klines"):
            assert params["interval"] == "1h" and params["limit"] <= 1500
            limit = min(params["limit"], self.page)
            if "startTime" in params:
                start = max(0, -(-(params["startTime"] - self.first) // HOUR))
                rows = [self.bar(i) for i in range(start, min(self.n, start + limit))]
            else:
                rows = [self.bar(i) for i in range(max(0, self.n - limit), self.n)]
            return FakeResponse({"code": 0, "data": rows})
        if url.endswith("/tickers"):
            return FakeResponse({"code": 0, "data": [{"symbol": "BTC-USD", "lastPx": "71605", "bidPx": "71604",
                                                      "askPx": "71612", "markPrice": "71606", "indexPrice": "71635",
                                                      "fundingRate": "0.0000125", "openInterest": "35.31",
                                                      "quoteVolume": "10693722"}]})
        if url.endswith("/symbols"):
            return FakeResponse({"code": 0, "data": [{"id": 1, "name": "BTC-USD", "status": "TRADING", "makerFee": "0.0001",
                                                      "takerFee": "0.0004", "tickSize": "1", "stepSize": "0.0001",
                                                      "minNotional": "10", "maxLeverage": 50}]})
        return FakeResponse({"code": 404, "message": "not found"}, status=404)


def fetcher_with(gateway):
    f = OHLCVFetcher("sodex", cache_dir="unused", clock=lambda: NOW / 1000)
    f._exchange = SodexPublic(session=gateway)
    return f


def test_klines_are_parsed_oldest_first_and_the_forming_bar_is_dropped():
    gw = FakeGateway(n_bars=100)
    df = fetcher_with(gw)._download("BTC-USD", "1h", None, 1000, 50)
    assert len(df) == 50
    assert df["timestamp"].is_monotonic_increasing
    assert int(df["timestamp"].iloc[-1].timestamp() * 1000) == NOW // HOUR * HOUR - HOUR  # last *closed* bar
    assert df["close"].iloc[-1] == 100.5 + 98


def test_deep_history_is_paged_forward_to_the_present():
    gw = FakeGateway(n_bars=3000, page=1000)
    df = fetcher_with(gw)._download("BTC-USD", "1h", None, 1000, 2200)
    assert len(df) == 2200
    assert df["timestamp"].diff().dropna().dt.total_seconds().eq(3600).all()
    assert int(df["timestamp"].iloc[-1].timestamp() * 1000) == NOW // HOUR * HOUR - HOUR
    assert all("startTime" in p for _, p in gw.calls)  # never relies on the newest-page default


def test_ticker_market_and_errors():
    gw = FakeGateway()
    client = SodexPublic(session=gw)
    t, m = client.ticker("BTC-USD"), client.market("BTC-USD")
    assert t["funding_rate"] == pytest.approx(0.0000125) and t["mark"] == 71606
    assert m["maker_fee"] == pytest.approx(0.0001) and m["taker_fee"] == pytest.approx(0.0004)
    with pytest.raises(SodexAPIError):
        client.ticker("ETH-USD")
    with pytest.raises(ValueError):
        client.fetch_ohlcv("BTC-USD", "2d")
    with pytest.raises(ValueError):
        SodexPublic("devnet")


def test_api_error_envelope_raises():
    class Limited(FakeGateway):
        def get(self, url, **kw):
            return FakeResponse({"code": 4001, "message": "rate limit exceeded"})

    with pytest.raises(SodexAPIError, match="4001"):
        SodexPublic(session=Limited()).market("BTC-USD")


def test_only_public_get_requests_are_ever_sent():
    class Recorder(FakeGateway):
        def post(self, *a, **k):  # pragma: no cover - must never be called
            raise AssertionError("SodexPublic must not send POST requests")

    gw = Recorder()
    client = SodexPublic(session=gw)
    client.fetch_ohlcv("BTC-USD", "1h", limit=10)
    client.ticker("BTC-USD")
    client.market("BTC-USD")
    assert all("/api/v1/perps/markets/" in url for url, _ in gw.calls)


def test_exchange_check_logs_a_snapshot(tmp_path, monkeypatch, capsys):
    import trading_bot.data.sodex as sodex
    from trading_bot.cli import main

    gw = FakeGateway(n_bars=200)
    real_init = sodex.SodexPublic.__init__
    monkeypatch.setattr(sodex.SodexPublic, "__init__", lambda self, network="mainnet": real_init(self, network, session=gw))
    monkeypatch.setattr("time.time", lambda: NOW / 1000)
    log = tmp_path / "market.jsonl"
    main(["exchange-check", "--exchange", "sodex", "--symbol", "BTC-USD", "--cache-dir", str(tmp_path), "--log", str(log)])
    snap = json.loads(log.read_text().splitlines()[0])
    assert snap["market"]["maker_fee"] == pytest.approx(0.0001)
    assert snap["ticker"]["funding_rate"] == pytest.approx(0.0000125)
    assert snap["last_closed_bar"]["bars_returned"] == 50
    capsys.readouterr()


def test_self_improve_runs_on_sodex_data_end_to_end(tmp_path, monkeypatch, capsys):
    """The live path the VPS uses: fetch from SoDEX into the store, re-optimize, decide, paper-trade."""
    import trading_bot.data.sodex as sodex
    from trading_bot.cli import main

    import time

    gw = FakeGateway(n_bars=1300, now=int(time.time() * 1000))  # the CLI's fetcher uses the real clock
    real_init = sodex.SodexPublic.__init__
    monkeypatch.setattr(sodex.SodexPublic, "__init__", lambda self, network="mainnet": real_init(self, network, session=gw))
    state, cache = tmp_path / "state", tmp_path / "cache"
    main(["self-improve", "--exchange", "sodex", "--symbol", "BTC-USD", "--state-dir", str(state), "--cache-dir", str(cache),
          "--steps", "1", "--step-seconds", "0", "--dashboard-out", str(state / "dashboard.html")])
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    assert [e["event"] for e in events] == ["reoptimize", "step"]
    step = events[-1]
    assert step["price"] == 100.5 + 1298  # the newest closed bar, not the forming one
    assert (state / "decisions_BTC-USD.jsonl").exists() and (state / "portfolio_BTC-USD.json").exists()
    assert (cache / "sodex_BTC-USD_1h.csv").exists() and (state / "dashboard.html").exists()
    assert all(not url.endswith(("/orders", "/order")) for url, _ in gw.calls)
