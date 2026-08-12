"""ShellTool — the first concrete Tool: run a command inside the sandbox.

Gated by the policy engine (block + risk classification) and capability grant
before a single byte reaches the sandbox. This is the seam Phase 4's LLM loop
calls, and it demonstrates the full Tool contract end to end.
"""
from __future__ import annotations

import shlex
from typing import Any

from ..policy import evaluate
from .base import RiskLevel, Tool, ToolContext, ToolResult


class ShellTool(Tool):
    name = "shell.execute"
    description = "Run a shell command inside the isolated sandbox and capture its output."
    capability = "shell.execute"
    risk = RiskLevel.MEDIUM

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to run, e.g. 'pytest -q'.",
                }
            },
            "required": ["command"],
        }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        command = str(args.get("command", "")).strip()
        if not command:
            return ToolResult(ok=False, error="empty command")

        if not ctx.is_granted(self.capability):
            return ToolResult(
                ok=False, error=f"capability '{self.capability}' not granted to this agent"
            )

        decision = evaluate(command)
        if not decision.allowed:
            return ToolResult(ok=False, error=decision.reason)
        if decision.requires_approval:
            # The Execution Manager turns this into an Approval halt (Phase 3).
            return ToolResult(
                ok=False,
                error="approval_required",
                output={"risk": int(decision.risk), "reason": decision.reason},
            )

        # Actual execution is driven by the Execution Manager which owns the
        # sandbox handle + live streaming; the tool returns the vetted argv.
        return ToolResult(ok=True, output={"argv": shlex.split(command), "risk": int(decision.risk)})
