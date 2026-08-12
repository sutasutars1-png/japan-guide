"""Google Gemini adapter (roadmap Phase 4 — the default free provider).

Talks to the Gemini REST API (generativelanguage.googleapis.com) over httpx so
the exact request shape is explicit and easy to test, and so the API boots fine
before a key is configured (httpx is imported lazily inside `complete`).

Secret masking (Phase 3) is applied to every message before it leaves the
process. Function-calling / tools mapping is deferred to a later Phase 4 stage.
"""
from __future__ import annotations

import os
from typing import Any

from ..secrets import mask_secrets
from .base import LLMMessage, LLMProvider, LLMResponse, LLMUsage

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


def build_request_body(messages: list[LLMMessage], max_tokens: int) -> dict[str, Any]:
    """Turn provider-neutral messages into a Gemini generateContent body.

    - system messages → `systemInstruction`
    - user/assistant → `contents` (assistant maps to Gemini's "model" role)
    - every text is masked so no secret value leaves the process
    """
    system = "\n".join(m.content for m in messages if m.role == "system")
    contents: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "system":
            continue
        role = "model" if m.role == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": mask_secrets(m.content)}]})

    body: dict[str, Any] = {
        "contents": contents,
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": mask_secrets(system)}]}
    return body


def parse_response(data: dict[str, Any]) -> LLMResponse:
    """Extract text + usage + stop reason from a Gemini response payload."""
    candidates = data.get("candidates") or []
    text = ""
    stop_reason = "end_turn"
    if candidates:
        parts = candidates[0].get("content", {}).get("parts", []) or []
        text = "".join(p.get("text", "") for p in parts)
        finish = candidates[0].get("finishReason") or "STOP"
        stop_reason = "end_turn" if finish in ("STOP", "MAX_TOKENS") else str(finish).lower()

    usage = data.get("usageMetadata", {}) or {}
    return LLMResponse(
        text=text,
        usage=LLMUsage(
            input_tokens=usage.get("promptTokenCount", 0),
            output_tokens=usage.get("candidatesTokenCount", 0),
        ),
        stop_reason=stop_reason,
    )


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = (
            api_key
            or os.getenv("GEMINI_API_KEY", "")
            or os.getenv("GOOGLE_API_KEY", "")
        )

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        if not self._api_key:
            raise RuntimeError("GEMINI_API_KEY is not set — configure it in Connections.")
        import httpx  # lazy: only needed when a completion is actually requested

        body = build_request_body(messages, max_tokens)
        url = f"{BASE_URL}/models/{model}:generateContent"
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url, params={"key": self._api_key}, json=body)
            resp.raise_for_status()
            data = resp.json()
        return parse_response(data)
