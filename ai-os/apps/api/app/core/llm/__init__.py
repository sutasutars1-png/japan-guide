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
]


def get_llm_provider(name: str | None = None) -> LLMProvider:
    name = (name or os.getenv("LLM_PROVIDER", "anthropic")).lower()
    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider()
    raise ValueError(f"unknown LLM provider: {name}")
