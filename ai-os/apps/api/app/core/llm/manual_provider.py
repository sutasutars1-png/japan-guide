"""Manual-bridge provider (Phase 4 · Connections) — an LLMProvider with no API.

Implements the standard `LLMProvider.complete()` interface, but instead of a
network call it surfaces the (masked) prompt to a human via `manual_bridge` and
awaits the pasted reply. This is how Claude in the browser / the Claude Code CLI
/ any API-less assistant become usable behind the same boundary as Gemini and
Anthropic — nothing upstream (the agent loop, flows) needs to know the transport
is a person.

Secret masking (Phase 3) is applied to every message before it is surfaced, so a
secret value is never copied out to the external assistant.
"""
from __future__ import annotations

import asyncio
from typing import Any

from ..secrets import mask_secrets
from .base import LLMMessage, LLMProvider, LLMResponse, LLMUsage

# Long ceiling: a human may take a while to paste. Bounded so a forgotten prompt
# can't wedge a run forever.
_DEFAULT_TIMEOUT_S = 1800


def render_prompt(messages: list[LLMMessage]) -> str:
    """Flatten messages into one copy-pasteable, fully-masked block."""
    out: list[str] = []
    for m in messages:
        if m.role == "system":
            out.append(mask_secrets(m.content))
        elif m.role == "assistant":
            out.append(f"[前回のあなたの返答]\n{mask_secrets(m.content)}")
        else:  # user / tool
            out.append(mask_secrets(m.content))
    return "\n\n".join(out).strip()


class ManualBridgeProvider(LLMProvider):
    name = "manual"

    def __init__(self, label: str = "Manual", timeout_s: int = _DEFAULT_TIMEOUT_S) -> None:
        self._label = label
        self._timeout = timeout_s

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        # Imported here so importing this module never drags in app state.
        from ...manual_bridge import bridge

        prompt = render_prompt(messages)
        pending = bridge.create(title=f"{self._label} · {model}", prompt=prompt)
        try:
            reply = await asyncio.wait_for(pending.future, timeout=self._timeout)
        except asyncio.TimeoutError as exc:
            bridge.cancel(pending.id, "timed out waiting for a pasted reply")
            raise RuntimeError(
                "手動ブリッジがタイムアウトしました（貼り付け待ち）。"
            ) from exc
        # Usage is unknown for a human relay; report zeros (never fabricate counts).
        return LLMResponse(text=reply, usage=LLMUsage())
