"""Tool — abstraction boundary #2 (roadmap §2.1).

Every capability the AI can use is a Tool with an explicit permission level.
Default Deny: a Tool only runs for an agent that has been granted its
capability. This is the object the LLM loop (Phase 4) calls, and the object
the Policy gate (Phase 3) inspects before anything executes.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from enum import IntEnum
from typing import Any


class RiskLevel(IntEnum):
    """Matches the UI's L0–L4 risk gauge."""

    READ_ONLY = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class ToolResult:
    ok: bool
    output: Any = None
    error: str | None = None


class Tool(abc.ABC):
    """name / description / input_schema / permission / execute (§2.1)."""

    name: str = "tool"
    description: str = ""
    capability: str = ""  # e.g. "python.execute" — must be granted to the agent
    risk: RiskLevel = RiskLevel.READ_ONLY

    @property
    @abc.abstractmethod
    def input_schema(self) -> dict[str, Any]:
        """JSON schema of the tool's arguments (fed to the LLM)."""
        ...

    @abc.abstractmethod
    async def execute(self, args: dict[str, Any], ctx: "ToolContext") -> ToolResult:
        ...


@dataclass
class ToolContext:
    """Runtime context handed to a tool: which agent, its grants, the sandbox."""

    agent_id: str
    granted_capabilities: set[str]
    sandbox_handle: Any = None

    def is_granted(self, capability: str) -> bool:
        return capability in self.granted_capabilities


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def specs(self) -> list[dict[str, Any]]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "capability": t.capability,
                "risk": int(t.risk),
                "input_schema": t.input_schema,
            }
            for t in self._tools.values()
        ]

    def __iter__(self):
        return iter(self._tools.values())


registry = ToolRegistry()
