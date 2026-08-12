"""LLM Provider — abstraction boundary #3 (roadmap §2.1).

A thin, swappable Adapter so "single LLM → multiple LLMs" is a config change,
not a rewrite. Phase 4 wires exactly one provider through this interface; the
shape below is deliberately provider-neutral.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMMessage:
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str


@dataclass
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: LLMUsage = field(default_factory=LLMUsage)
    stop_reason: str = "end_turn"


class LLMProvider(abc.ABC):
    name: str = "abstract"

    @abc.abstractmethod
    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        ...
