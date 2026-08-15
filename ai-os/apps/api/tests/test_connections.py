"""Connections + manual-bridge tests — no network, no real keys."""
import asyncio
import os

os.environ.setdefault("AIOS_ALLOW_UNSAFE_LOCAL", "1")

import pytest  # noqa: E402

from app import connections  # noqa: E402
from app.core.llm import LLMMessage, get_provider_for_model  # noqa: E402
from app.core.llm.manual_provider import ManualBridgeProvider, render_prompt  # noqa: E402
from app.core.secrets import store as secret_store  # noqa: E402
from app.manual_bridge import bridge  # noqa: E402


@pytest.fixture(autouse=True)
def _tmp_env(tmp_path, monkeypatch):
    # keep .env writes off the real file
    monkeypatch.setenv("AIOS_ENV_FILE", str(tmp_path / ".env"))
    yield


# ---- key + live discovery ---------------------------------------------------

def test_set_key_persists_masks_and_discovers(monkeypatch):
    seen = {}
    monkeypatch.setattr(connections, "_discover_gemini", lambda key: (seen.setdefault("key", key), ["gemini-9.9-pro", "gemini-9.9-flash"])[1])
    conn = connections.set_key("gemini", "AIzaTESTKEY123456")
    # discovered, not hard-coded
    assert conn["models"] == ["gemini-9.9-pro", "gemini-9.9-flash"]
    assert conn["connected"] is True
    # key registered for masking, only a masked hint leaves
    assert "AIzaTESTKEY123456" not in conn["key_hint"]
    assert secret_store.mask("my key AIzaTESTKEY123456 here") != "my key AIzaTESTKEY123456 here"
    # .env written (git-ignored path via fixture)
    assert os.path.exists(os.environ["AIOS_ENV_FILE"])
    connections.clear_key("gemini")


def test_discovery_error_is_captured_not_raised(monkeypatch):
    def boom(key):
        raise RuntimeError("401 unauthorized")
    monkeypatch.setattr(connections, "_discover_anthropic", boom)
    conn = connections.set_key("anthropic", "sk-ant-bad")
    assert conn["error"] and "失敗" in conn["error"]
    connections.clear_key("anthropic")


def test_manual_provider_needs_no_key_and_lists_models():
    conns = {c["id"]: c for c in connections.list_connections()}
    cw = conns["claude-web"]
    assert cw["kind"] == "manual"
    assert cw["connected"] is True          # ready without a key
    assert "claude-web" in cw["models"]


def test_add_manual_model():
    conn = connections.add_manual_model("claude-web", "claude-web-next")
    assert "claude-web-next" in conn["models"]


def test_model_routing_picks_provider():
    assert isinstance(get_provider_for_model("claude-web"), ManualBridgeProvider)
    assert get_provider_for_model("claude-web").name == "manual"


# ---- manual bridge ----------------------------------------------------------

def test_render_prompt_masks_secrets():
    secret_store.set("TESTSECRET", "supersecretvalue")
    text = render_prompt([
        LLMMessage(role="system", content="be careful"),
        LLMMessage(role="user", content="token is supersecretvalue ok"),
    ])
    assert "supersecretvalue" not in text
    assert "be careful" in text
    secret_store._values.pop("TESTSECRET", None)
    secret_store._rebuild_pattern()


async def test_manual_bridge_roundtrip():
    prov = ManualBridgeProvider(label="Test")

    async def human():
        # wait for the prompt to appear, then paste a reply
        for _ in range(50):
            pend = bridge.list()
            if pend:
                bridge.submit(pend[0]["id"], "DONE: 人間が貼り付けた返答")
                return
            await asyncio.sleep(0.01)

    task = asyncio.create_task(human())
    resp = await prov.complete([LLMMessage(role="user", content="hi")], model="claude-code")
    await task
    assert resp.text == "DONE: 人間が貼り付けた返答"
    assert bridge.list() == []  # consumed
