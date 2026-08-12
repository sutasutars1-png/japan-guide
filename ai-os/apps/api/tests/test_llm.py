"""Tests for the Gemini adapter (no network — pure request/response helpers)."""
import pytest

from app.core.llm import LLMMessage, get_llm_provider
from app.core.llm.gemini_provider import (
    GeminiProvider,
    build_request_body,
    parse_response,
)
from app.core.secrets import SecretStore


def test_factory_returns_gemini_by_name():
    assert get_llm_provider("gemini").name == "gemini"


def test_build_request_body_splits_system_and_roles():
    body = build_request_body(
        [
            LLMMessage(role="system", content="You are helpful."),
            LLMMessage(role="user", content="hi"),
            LLMMessage(role="assistant", content="hello"),
        ],
        max_tokens=512,
    )
    assert body["systemInstruction"]["parts"][0]["text"] == "You are helpful."
    assert body["generationConfig"]["maxOutputTokens"] == 512
    roles = [c["role"] for c in body["contents"]]
    assert roles == ["user", "model"]  # assistant → "model"


def test_build_request_body_masks_secrets(monkeypatch):
    # Register a secret in the process-wide store, then ensure it's masked.
    from app.core.secrets import store as global_store

    global_store.set("TESTKEY", "sk-super-secret-abcdef")
    body = build_request_body(
        [LLMMessage(role="user", content="my key is sk-super-secret-abcdef ok")],
        max_tokens=64,
    )
    text = body["contents"][0]["parts"][0]["text"]
    assert "sk-super-secret-abcdef" not in text
    assert "••••••••" in text


def test_parse_response_extracts_text_and_usage():
    data = {
        "candidates": [
            {"content": {"parts": [{"text": "the answer is 42"}]}, "finishReason": "STOP"}
        ],
        "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 5},
    }
    r = parse_response(data)
    assert r.text == "the answer is 42"
    assert r.usage.input_tokens == 12
    assert r.usage.output_tokens == 5
    assert r.stop_reason == "end_turn"


def test_parse_response_handles_empty():
    r = parse_response({})
    assert r.text == ""
    assert r.usage.total == 0


@pytest.mark.asyncio
async def test_complete_without_key_raises():
    p = GeminiProvider(api_key="")
    with pytest.raises(RuntimeError):
        await p.complete([LLMMessage(role="user", content="hi")], model="gemini-2.5-flash")
