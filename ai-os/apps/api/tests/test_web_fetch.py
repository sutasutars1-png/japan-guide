"""web.fetch tool — SSRF guard, redirect re-validation, and agent-loop wiring.
No real network: the happy path injects a fake opener; guard paths reject before
any connection."""
import os

os.environ.setdefault("AIOS_ALLOW_UNSAFE_LOCAL", "1")

import pytest  # noqa: E402

from app.agent_loop import AgentLoop, _agent_caps, parse_agent_action  # noqa: E402
from app.core.llm.base import LLMResponse, LLMUsage  # noqa: E402
from app.core.sandbox.local_runtime import LocalSubprocessRuntime  # noqa: E402
from app.core.tools import web_fetch  # noqa: E402
from app.core.tools.web_fetch import _host_public_reason, _strip_html, safe_fetch  # noqa: E402
from app.execution_manager import ExecutionManager  # noqa: E402


# ---- SSRF guard -------------------------------------------------------------

@pytest.mark.parametrize("host", [
    "127.0.0.1", "localhost", "169.254.169.254", "10.0.0.5", "192.168.1.1",
    "172.16.0.9", "0.0.0.0", "::1",
])
def test_blocks_non_public_hosts(host):
    assert _host_public_reason(host) is not None


def test_allows_public_ip_literal():
    assert _host_public_reason("8.8.8.8") is None


def test_safe_fetch_rejects_non_http_scheme():
    assert safe_fetch("file:///etc/passwd").ok is False
    assert safe_fetch("ftp://example.com/x").ok is False


def test_safe_fetch_refuses_metadata_without_network():
    # must fail at the guard, before any socket is opened
    res = safe_fetch("http://169.254.169.254/latest/meta-data/")
    assert res.ok is False and "blocked" in res.error


# ---- fake-opener happy path + redirect re-validation ------------------------

class _Resp:
    def __init__(self, status, headers, body=b""):
        self.status = status
        self.headers = headers
        self._body = body

    def getcode(self):
        return self.status

    def read(self, n=-1):
        return self._body[:n] if n and n > 0 else self._body


class _FakeOpener:
    def __init__(self, responses):
        self._responses = list(responses)
        self.opened = []

    def open(self, req, timeout=None):
        self.opened.append(req.full_url)
        return self._responses.pop(0)


def test_safe_fetch_returns_text_and_strips_html():
    opener = _FakeOpener([_Resp(200, {"Content-Type": "text/html"},
                                b"<html><body><h1>Hi</h1><script>bad()</script>note</body></html>")])
    res = safe_fetch("http://8.8.8.8/page", opener=opener)
    assert res.ok
    assert "Hi" in res.output["text"] and "note" in res.output["text"]
    assert "bad()" not in res.output["text"]  # script stripped


def test_safe_fetch_revalidates_redirect_target():
    # 8.8.8.8 (public) → redirect to a metadata IP: the second hop must be refused
    opener = _FakeOpener([
        _Resp(302, {"Location": "http://169.254.169.254/"}),
    ])
    res = safe_fetch("http://8.8.8.8/start", opener=opener)
    assert res.ok is False and "blocked" in res.error


def test_safe_fetch_non_text_not_returned():
    opener = _FakeOpener([_Resp(200, {"Content-Type": "image/png"}, b"\x89PNG")])
    res = safe_fetch("http://8.8.8.8/img.png", opener=opener)
    assert res.ok is False and "non-text" in res.error


def test_strip_html_basic():
    assert _strip_html("<p>a</p><style>x{}</style><b>b</b>") == "a b"


# ---- parser + agent-loop wiring --------------------------------------------

def test_parse_fetch_action():
    assert parse_agent_action("FETCH: https://example.com/x") == ("fetch", "https://example.com/x")


class SeqProvider:
    name = "fake"

    def __init__(self, replies):
        self._replies = list(replies)
        self._i = 0

    async def complete(self, messages, *, model, tools=None, max_tokens=1024):
        text = self._replies[min(self._i, len(self._replies) - 1)]
        self._i += 1
        return LLMResponse(text=text, usage=LLMUsage(input_tokens=1, output_tokens=1))


async def test_agent_loop_fetch_uses_host_not_sandbox(monkeypatch):
    # grant web.fetch to the test agent + stub the fetch so no network is touched
    monkeypatch.setattr("app.agent_loop._agent_caps", lambda name: {"web.fetch"})
    from app.core.tools.base import ToolResult
    calls = []

    def fake_fetch(url, **kw):
        calls.append(url)
        return ToolResult(ok=True, output={"url": url, "status": 200,
                                           "content_type": "text/html", "truncated": False,
                                           "text": "調査結果の本文"})
    monkeypatch.setattr("app.core.tools.web_fetch.safe_fetch", fake_fetch)

    loop = AgentLoop(
        provider=SeqProvider(["FETCH: https://note.com/x", "DONE: まとめました"]),
        manager=ExecutionManager(LocalSubprocessRuntime()), model="fake",
    )
    lines = [l async for l in loop.run("調べて", agent_name="Researcher", max_iterations=4)]
    joined = "\n".join(l.s for l in lines)
    assert calls == ["https://note.com/x"]                 # fetched via host
    assert "FETCH（ホスト側" in joined
    assert "[web.fetch]" in joined


async def test_agent_loop_fetch_denied_without_capability(monkeypatch):
    monkeypatch.setattr("app.agent_loop._agent_caps", lambda name: set())  # no grant
    called = []
    monkeypatch.setattr("app.core.tools.web_fetch.safe_fetch",
                        lambda url, **kw: called.append(url))
    loop = AgentLoop(
        provider=SeqProvider(["FETCH: https://note.com/x", "DONE: done"]),
        manager=ExecutionManager(LocalSubprocessRuntime()), model="fake",
    )
    lines = [l async for l in loop.run("g", agent_name="Builder", max_iterations=4)]
    assert not called                                       # never fetched
    assert any("web.fetch 権限がありません" in l.s for l in lines)
