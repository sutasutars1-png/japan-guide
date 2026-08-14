"""Manual bridge (Phase 4 · Connections) — use an AI that has no API.

Some models we want to use (Claude in the browser, the Claude Code CLI, any
future assistant without a usable API) can't be called over HTTP. The bridge
makes them first-class anyway, reusing the Phase 4 "human as the transport"
idea: when an agent is backed by a *manual* provider, its composed prompt is
surfaced to the human, who pastes it into the assistant and pastes the reply
back. The agent loop is unchanged — it still `await`s a completion; the bridge
just fulfils that completion via a human instead of a network call.

Safety carries over unchanged: the prompt is **masked** (Phase 3) before it is
ever surfaced, so no secret value is copied out; nothing here logs prompt or
reply bodies.

The store is an in-process asyncio coordination point — a pending request holds
a Future that `submit()` resolves. It's deliberately small; a durable/queued
backend drops in behind the same functions later.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field


@dataclass
class Pending:
    id: str
    title: str          # e.g. "Builder · Claude Code"
    prompt: str         # already masked, ready to copy-paste
    created: float
    future: "asyncio.Future[str]" = field(repr=False)


class ManualBridge:
    def __init__(self) -> None:
        self._pending: dict[str, Pending] = {}

    def create(self, title: str, prompt: str) -> Pending:
        """Register a prompt awaiting a human's pasted reply. Returns the record."""
        loop = asyncio.get_event_loop()
        p = Pending(
            id=uuid.uuid4().hex[:12],
            title=title,
            prompt=prompt,
            created=time.time(),
            future=loop.create_future(),
        )
        self._pending[p.id] = p
        return p

    def list(self) -> list[dict]:
        """Pending prompts, oldest first — safe to serialize (no futures)."""
        return [
            {"id": p.id, "title": p.title, "prompt": p.prompt, "created": p.created}
            for p in sorted(self._pending.values(), key=lambda x: x.created)
        ]

    def submit(self, pending_id: str, reply: str) -> bool:
        """Deliver the human's pasted reply; resolves the awaiting completion."""
        p = self._pending.pop(pending_id, None)
        if p is None:
            return False
        if not p.future.done():
            p.future.set_result(reply)
        return True

    def cancel(self, pending_id: str, reason: str = "cancelled") -> bool:
        p = self._pending.pop(pending_id, None)
        if p is None:
            return False
        if not p.future.done():
            p.future.set_exception(RuntimeError(reason))
        return True


bridge = ManualBridge()
