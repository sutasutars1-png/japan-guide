"""LLM provider factory."""
from __future__ import annotations

import os

from .base import LLMMessage, LLMProvider, LLMResponse, LLMUsage

__all__ = [
    "LLMMessage",
    "LLMProvider",
    "LLMResponse",
    "LLMUsage",
    "get_llm_provider",
    "get_provider_for_model",
]


def get_llm_provider(name: str | None = None) -> LLMProvider:
    name = (name or os.getenv("LLM_PROVIDER", "gemini")).lower()
    if name == "gemini":
        from .gemini_provider import GeminiProvider

        return GeminiProvider()
    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider()
    if name == "openai":
        from .openai_provider import OpenAIProvider

        return OpenAIProvider()
    if name in ("claude-cli", "claude-code"):
        from .claude_cli_provider import ClaudeCliProvider

        return ClaudeCliProvider()
    if name in ("claude-web", "manual"):
        from .manual_provider import ManualBridgeProvider

        return ManualBridgeProvider(label=name)
    raise ValueError(f"unknown LLM provider: {name}")


def get_provider_for_model(model: str) -> LLMProvider:
    """Pick the provider that serves `model`, consulting the Connections registry
    (live-discovered / curated model lists). Falls back to the configured default.
    Manual models route to the manual bridge — so an API-less AI works like any
    other behind this boundary.
    """
    from ...connections import provider_id_for_model  # lazy: avoid import cycle

    pid = provider_id_for_model(model)
    if pid:
        return get_llm_provider(pid)
    return get_llm_provider()
