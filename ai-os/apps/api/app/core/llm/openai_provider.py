"""OpenAI adapter (Phase 4 · Connections) — REST via httpx, lazy + masked.

Boots fine without a key or the network (httpx is imported inside `complete`).
Secret masking (Phase 3) is applied to every message before it leaves the
process. Uses the Chat Completions API for broad model compatibility.
"""
from __future__ import annotations

import os
from typing import Any

from ..secrets import mask_secrets
from .base import LLMMessage, LLMProvider, LLMResponse, LLMUsage

BASE_URL = "https://api.openai.com/v1"


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.getenv("OPENAI_API_KEY", "")

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        if not self._api_key:
            raise RuntimeError("OPENAI_API_KEY is not set — configure it in Connections.")
        import httpx  # lazy

        convo = [
            {"role": "assistant" if m.role == "assistant" else m.role,
             "content": mask_secrets(m.content)}
            for m in messages
        ]
        body = {"model": model, "messages": convo, "max_tokens": max_tokens}
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()

        choice = (data.get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content", "") or ""
        usage = data.get("usage", {}) or {}
        return LLMResponse(
            text=text,
            usage=LLMUsage(
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
            ),
            stop_reason=choice.get("finish_reason") or "end_turn",
        )
