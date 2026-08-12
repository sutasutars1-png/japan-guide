"""Execution Manager (roadmap Phase 2) — the orchestrator that proves the core.

Owns the lifecycle: create sandbox → for each command run the policy gate →
stream live output → record everything to the audit log → destroy sandbox.
It is intentionally runtime-agnostic (talks only to the SandboxRuntime
interface) and provider-agnostic. Phase 4 plugs the LLM loop on top of it.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import AsyncIterator

from .core.audit import AuditEvent, log
from .core.policy import evaluate
from .core.sandbox import (
    NetworkPolicy,
    ResourceLimits,
    SandboxRuntime,
    SandboxSpec,
    get_sandbox_runtime,
)
from .core.secrets import mask_secrets


@dataclass
class LogLine:
    """Matches the UI's log line shape: {t, s}. t ∈ sys|cmd|out|ok|warn|err|halt."""

    t: str
    s: str


@dataclass
class Job:
    id: str
    command: str
    status: str = "queued"  # queued|running|done|failed|halted
    lines: list[LogLine] = field(default_factory=list)
    exit_code: int | None = None


class ExecutionManager:
    def __init__(self, runtime: SandboxRuntime | None = None) -> None:
        self._runtime = runtime or get_sandbox_runtime()
        self._jobs: dict[str, Job] = {}

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    async def run(
        self,
        command: str,
        *,
        actor: str = "Builder",
        allow_domains: list[str] | None = None,
        approved: bool = False,
    ) -> AsyncIterator[LogLine]:
        """Run one command in a fresh sandbox, yielding UI-shaped log lines.

        `approved=True` means a human already OK'd this exact command in the
        Approval modal, so the L3/L4 gate is skipped — but a *blocked* command
        (rm -rf /, mkfs, …) never runs, even with approval.
        """
        job = Job(id="job-" + uuid.uuid4().hex[:8], command=command)
        self._jobs[job.id] = job

        decision = evaluate(command)
        if not decision.allowed:
            job.status = "halted"
            line = LogLine("err", f"policy blocked: {decision.reason}")
            job.lines.append(line)
            log.append(AuditEvent("policy.block", actor, decision.reason, int(decision.risk)))
            yield line
            return
        if decision.requires_approval and not approved:
            job.status = "halted"
            line = LogLine("halt", f"approval required · {command} · L{int(decision.risk)}")
            job.lines.append(line)
            log.append(AuditEvent("approval.request", actor, command, int(decision.risk)))
            yield line
            return
        if decision.requires_approval and approved:
            log.append(AuditEvent("approval.granted", "human", command, int(decision.risk)))
            yield self._emit(job, "ok", f"approved by you · running (L{int(decision.risk)})")

        spec = SandboxSpec(
            limits=ResourceLimits(),
            network=NetworkPolicy(default_deny=True, allow_domains=allow_domains or []),
        )
        # Give immediate feedback: the first run may download the sandbox image.
        yield self._emit(job, "sys", "preparing sandbox… (first run may download the image)")
        handle = await self._runtime.create(spec)
        job.status = "running"
        log.append(
            AuditEvent(
                "sandbox.create",
                actor,
                f"{handle.id} · non-root(uid {handle.non_root_uid}) · {handle.backend}",
            )
        )
        yield self._emit(job, "sys", f"sandbox {handle.id} created · non-root(uid {handle.non_root_uid}) · {handle.backend}")
        yield self._emit(job, "sys", "network DEFAULT DENY · allow" + (str(allow_domains) if allow_domains else "[]"))

        started = time.monotonic()
        try:
            argv = ["/bin/sh", "-lc", command]
            log.append(AuditEvent("command.run", actor, command, int(decision.risk)))
            async for chunk in self._runtime.execute(handle, argv):
                if chunk.stream == "system":
                    yield self._emit(job, "cmd", mask_secrets(chunk.text))
                elif chunk.stream == "stderr":
                    yield self._emit(job, "warn", mask_secrets(chunk.text))
                else:
                    yield self._emit(job, "out", mask_secrets(chunk.text))

            result = getattr(self._runtime, "last_result", lambda h: None)(handle)
            code = result.exit_code if result else 0
            job.exit_code = code
            job.status = "done" if code == 0 else "failed"
            dur = time.monotonic() - started
            if code == 0:
                yield self._emit(job, "ok", f"exited 0 · {dur:.1f}s")
            else:
                yield self._emit(job, "err", f"exited {code} · {dur:.1f}s")
        finally:
            await self._runtime.destroy(handle)
            log.append(AuditEvent("sandbox.destroy", actor, handle.id))

    def _emit(self, job: Job, t: str, s: str) -> LogLine:
        line = LogLine(t, s)
        job.lines.append(line)
        return line


# Lazily-constructed process-wide manager (constructing a runtime may need
# Docker, so we defer until first use).
_manager: ExecutionManager | None = None


def get_execution_manager() -> ExecutionManager:
    global _manager
    if _manager is None:
        _manager = ExecutionManager()
    return _manager
