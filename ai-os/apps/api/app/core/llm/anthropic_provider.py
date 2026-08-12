"""Anthropic adapter (roadmap Phase 4 — the first, and for MVP the only, provider).

Import-safe without the SDK or a key: the client is constructed lazily so the
API boots fine before any LLM is configured. Secret masking (Phase 3) is applied
to every message before it leaves the process.
"""
from __future__ import annotations

import os
from typing import Any

from ..secrets import mask_secrets
from .base import LLMMessage, LLMProvider, LLMResponse, LLMUsage


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self._client = None

    def _ensure_client(self):
        if not self._api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set — configure it in Connections.")
        if self._client is None:
            import anthropic  # lazy import

            self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
        return self._client

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        client = self._ensure_client()

        system = "\n".join(m.content for m in messages if m.role == "system")
        convo = [
            {"role": m.role, "content": mask_secrets(m.content)}
            for m in messages
            if m.role in ("user", "assistant")
        ]

        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": convo,
        }
        if system:
            kwargs["system"] = mask_secrets(system)
        if tools:
            kwargs["tools"] = tools

        resp = await client.messages.create(**kwargs)

        text_parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
        tool_calls = [
            {"name": b.name, "input": b.input, "id": b.id}
            for b in resp.content
            if getattr(b, "type", "") == "tool_use"
        ]
        return LLMResponse(
            text="".join(text_parts),
            tool_calls=tool_calls,
            usage=LLMUsage(
                input_tokens=resp.usage.input_tokens,
                output_tokens=resp.usage.output_tokens,
            ),
            stop_reason=resp.stop_reason or "end_turn",
        )
