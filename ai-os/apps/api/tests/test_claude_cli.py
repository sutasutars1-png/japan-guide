"""Claude Code CLI provider (#5) tests — mocked subprocess, no real CLI call."""
import os

os.environ.setdefault("AIOS_ALLOW_UNSAFE_LOCAL", "1")

import pytest  # noqa: E402

from app import connections  # noqa: E402
from app.core.llm import LLMMessage, get_provider_for_model  # noqa: E402
from app.core.llm import claude_cli_provider as ccp  # noqa: E402
from app.core.llm.claude_cli_provider import ClaudeCliProvider  # noqa: E402
from app.core.secrets import store as secret_store  # noqa: E402


class _FakeProc:
    def __init__(self, out=b"", err=b"", code=0):
        self._out, self._err, self.returncode = out, err, code
        self.captured_stdin = None

    async def communicate(self, input=None):
        self.captured_stdin = input
        return self._out, self._err

    def kill(self):
        pass


def _patch_cli(monkeypatch, proc, path="/usr/bin/claude"):
    monkeypatch.setattr(ccp.shutil, "which", lambda _c: path)
    captured = {}

    async def fake_exec(*args, **kwargs):
        captured["args"] = args
        captured["cwd"] = kwargs.get("cwd")
        captured["env"] = kwargs.get("env")
        return proc

    monkeypatch.setattr(ccp.asyncio, "create_subprocess_exec", fake_exec)
    return captured


async def test_cli_returns_stdout(monkeypatch):
    proc = _FakeProc(out=b"Builder: do X\nReviewer: check X\nDONE\n")
    cap = _patch_cli(monkeypatch, proc)
    prov = ClaudeCliProvider()
    resp = await prov.complete([LLMMessage(role="user", content="plan this")], model="claude-cli")
    assert "Builder: do X" in resp.text
    # never passes the dangerous skip-permissions flag
    assert "--dangerously-skip-permissions" not in cap["args"]
    assert "--allow-dangerously-skip-permissions" not in cap["args"]
    # runs in a throwaway cwd, not the repo
    assert cap["cwd"] and "aios-claude-" in cap["cwd"]


async def test_cli_masks_prompt_before_spawn(monkeypatch):
    secret_store.set("CLITEST", "topsecretxyz")
    proc = _FakeProc(out=b"ok")
    _patch_cli(monkeypatch, proc)
    prov = ClaudeCliProvider()
    await prov.complete([LLMMessage(role="user", content="key topsecretxyz here")], model="claude-cli")
    assert b"topsecretxyz" not in (proc.captured_stdin or b"")
    secret_store._values.pop("CLITEST", None)
    secret_store._rebuild_pattern()


async def test_cli_forces_subscription_strips_api_key(monkeypatch):
    # A user may have set an Anthropic API key (for API workers); it must NOT
    # leak into the `claude` subprocess, or the CLI would bill metered API.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-not-leak")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok-should-not-leak")
    proc = _FakeProc(out=b"ok")
    cap = _patch_cli(monkeypatch, proc)
    await ClaudeCliProvider().complete([LLMMessage(role="user", content="x")], model="claude-cli")
    assert "ANTHROPIC_API_KEY" not in cap["env"]
    assert "ANTHROPIC_AUTH_TOKEN" not in cap["env"]


async def test_cli_error_surfaces(monkeypatch):
    proc = _FakeProc(err=b"not logged in", code=1)
    _patch_cli(monkeypatch, proc)
    prov = ClaudeCliProvider()
    with pytest.raises(RuntimeError, match="not logged in"):
        await prov.complete([LLMMessage(role="user", content="x")], model="claude-cli")


async def test_cli_missing_binary(monkeypatch):
    monkeypatch.setattr(ccp.shutil, "which", lambda _c: None)
    prov = ClaudeCliProvider()
    with pytest.raises(RuntimeError, match="見つかりません"):
        await prov.complete([LLMMessage(role="user", content="x")], model="claude-cli")


def test_routing_and_connection(monkeypatch):
    monkeypatch.setattr(ccp.shutil, "which", lambda _c: "/usr/bin/claude")
    assert isinstance(get_provider_for_model("claude-cli"), ClaudeCliProvider)
    conns = {c["id"]: c for c in connections.list_connections()}
    cli = conns["claude-cli"]
    assert cli["kind"] == "cli"
    assert cli["connected"] is True
    assert "CLI検出" in cli["key_hint"]
