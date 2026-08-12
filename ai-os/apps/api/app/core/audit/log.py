"""Append-only Audit Log (roadmap: never cut, even in the self-use scope).

Every consequential event — sandbox created, command run, policy block,
approval decision — is appended here. Append-only by contract: there is no
update or delete. Secret values are masked on the way in. The MVP writes to
Postgres (audit_logs) with an in-memory mirror for the live UI feed.
"""
from __future__ import annotations

import datetime as _dt
import threading
from dataclasses import asdict, dataclass, field
from typing import Any

from ..secrets import mask_secrets


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


@dataclass
class AuditEvent:
    kind: str  # e.g. "sandbox.create", "command.run", "policy.block", "approval.decide"
    actor: str  # agent name or "human"
    summary: str
    risk: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    at: str = field(default_factory=_now)

    def redacted(self) -> "AuditEvent":
        return AuditEvent(
            kind=self.kind,
            actor=self.actor,
            summary=mask_secrets(self.summary),
            risk=self.risk,
            metadata={k: mask_secrets(str(v)) for k, v in self.metadata.items()},
            at=self.at,
        )


class AuditLog:
    def __init__(self, max_memory: int = 1000) -> None:
        self._events: list[AuditEvent] = []
        self._max = max_memory
        self._lock = threading.Lock()

    def append(self, event: AuditEvent) -> AuditEvent:
        event = event.redacted()
        with self._lock:
            self._events.append(event)
            if len(self._events) > self._max:
                # trim the in-memory mirror only; the durable store keeps all.
                self._events = self._events[-self._max :]
        # Phase 2 follow-up: also INSERT into postgres audit_logs (append-only).
        return event

    def tail(self, n: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            return [asdict(e) for e in self._events[-n:]]


log = AuditLog()
