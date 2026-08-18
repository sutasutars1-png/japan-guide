"""Execution Manager (roadmap Phase 2) — the orchestrator that proves the core.

Owns the lifecycle: create sandbox → for each command run the policy gate →
stream live output → record everything to the audit log → destroy sandbox.
It is intentionally runtime-agnostic (talks only to the SandboxRuntime
interface) and provider-agnostic. Phase 4 plugs the LLM loop on top of it.
"""
from __future__ import annotations

import base64
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import AsyncIterator

from .config import settings
from .core.audit import AuditEvent, log
from .core.policy import evaluate
from .core.sandbox import (
    NetworkPolicy,
    ResourceLimits,
    SandboxHandle,
    SandboxRuntime,
    SandboxSpec,
    get_sandbox_runtime,
)
from .core.secrets import mask_secrets

WORKDIR = "/workspace"

# Trusted in-sandbox walker: collect text files created under the workdir (cwd),
# excluding the copied-in materials/ and dotdirs, and print them as JSON.
# base64-encoded before send so quoting/newlines can't break the shell command.
_WALKER = """
import os, json
out, tot = [], 0
MAXF, MAXB, PERB = {maxf}, {maxb}, {perb}
for dp, dns, fns in os.walk('.'):
    dns[:] = [d for d in dns if not d.startswith('.') and d not in ('materials', 'inputs', '__pycache__', 'node_modules')]
    for fn in sorted(fns):
        if fn.startswith('.'):
            continue
        p = os.path.join(dp, fn)
        rel = os.path.relpath(p, '.')
        if rel.split('/', 1)[0] in ('materials', 'inputs'):
            continue
        try:
            sz = os.path.getsize(p)
        except OSError:
            continue
        if sz > PERB or len(out) >= MAXF or tot >= MAXB:
            continue
        try:
            with open(p, 'rb') as f:
                data = f.read()
        except OSError:
            continue
        if bytes([0]) in data:
            continue
        out.append({{'path': rel, 'size': sz, 'content': data.decode('utf-8', 'replace')}})
        tot += len(data)
print(json.dumps(out))
"""


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

    # ---- persistent session (roadmap: one sandbox per agent loop) -----------
    # The per-command `run()` above creates and destroys a sandbox each call, so
    # files never survive between an agent's steps. A *session* keeps one sandbox
    # alive for the whole loop (open_session → exec_in* → collect_files →
    # close_session), so an agent can build a file across steps and hand it back
    # as a deliverable.

    async def open_session(
        self, *, actor: str = "Builder", allow_domains: list[str] | None = None,
        materials: bool = True, seed_files: list[dict] | None = None,
    ) -> tuple[SandboxHandle, list[LogLine]]:
        """Create one sandbox for a whole agent loop; copy in materials and any
        prior-step outputs (`seed_files` → `inputs/`). Returns the handle plus the
        prep log lines to emit."""
        allow = [d for d in (allow_domains or []) if d]
        spec = SandboxSpec(
            limits=ResourceLimits(),
            network=NetworkPolicy(default_deny=True, allow_domains=allow),
        )
        lines = [LogLine("sys", "preparing sandbox… (first run may download the image)")]
        handle = await self._runtime.create(spec)
        log.append(AuditEvent("sandbox.create", actor,
                              f"{handle.id} · non-root(uid {handle.non_root_uid}) · {handle.backend} · allow={allow}"))
        lines.append(LogLine("sys", f"sandbox {handle.id} created · non-root(uid {handle.non_root_uid}) · {handle.backend}"))
        if allow:
            lines.append(LogLine("warn",
                f"network ALLOWLIST {allow} · 注意: egressは粗い（許可時は全outbound到達可）。人間が許可した場合のみ有効"))
        else:
            lines.append(LogLine("sys", "network DEFAULT DENY · allow[]"))
        if materials and settings.workspace_mount:
            try:
                from . import materials as materials_mod
                items = materials_mod.iter_materials(
                    settings.workspace_mount,
                    max_files=settings.materials_max_files,
                    max_bytes=settings.materials_max_bytes,
                    per_file_bytes=settings.deliverable_max_bytes,
                )
                n = await self._upload_files(handle, items, "materials/")
                if n:
                    log.append(AuditEvent("sandbox.materials", actor, f"{n} files → materials/"))
                    lines.append(LogLine("sys", f"📥 資料を {n} ファイル コピーしました → {WORKDIR}/materials/（読み取り用）"))
            except Exception as exc:  # noqa: BLE001 — materials are best-effort
                lines.append(LogLine("warn", f"資料のコピーに失敗しました: {exc}"))
        if seed_files:  # prior-step outputs so this worker can build on / review them
            try:
                items = [(f["path"], (f.get("content") or "").encode("utf-8"))
                         for f in seed_files if f.get("path")]
                n = await self._upload_files(handle, items, "inputs/")
                if n:
                    log.append(AuditEvent("sandbox.inputs", actor, f"{n} files → inputs/"))
                    lines.append(LogLine("sys", f"📎 前工程の成果物 {n} 件を {WORKDIR}/inputs/ に配置しました"))
            except Exception as exc:  # noqa: BLE001 — best-effort
                lines.append(LogLine("warn", f"前工程成果物の配置に失敗: {exc}"))
        return handle, lines

    async def _upload_files(self, handle: SandboxHandle, items, subdir: str) -> int:
        """Write (relpath, bytes) files into <workdir>/<subdir>. Local runtime's
        root IS the workdir; docker extracts at "/" so it needs the /workspace prefix."""
        base = (f"{WORKDIR}/{subdir}" if getattr(self._runtime, "backend", "") == "docker" else subdir)
        n = 0
        for rel, data in items:
            safe = "/".join(p for p in str(rel).replace("\\", "/").split("/") if p not in ("", ".", ".."))
            if not safe:
                continue
            try:
                await self._runtime.upload(handle, base + safe, data)
                n += 1
            except Exception:  # noqa: BLE001 — skip a file we can't place
                continue
        return n

    async def exec_in(
        self, handle: SandboxHandle, command: str, *, actor: str = "Builder", approved: bool = False,
    ) -> AsyncIterator[LogLine]:
        """Run one command in an EXISTING session sandbox (no create/destroy)."""
        decision = evaluate(command)
        if not decision.allowed:  # defense-in-depth (the loop also gates)
            yield LogLine("err", f"policy blocked: {decision.reason}")
            log.append(AuditEvent("policy.block", actor, decision.reason, int(decision.risk)))
            return
        if decision.requires_approval and not approved:
            yield LogLine("halt", f"approval required · {command} · L{int(decision.risk)}")
            log.append(AuditEvent("approval.request", actor, command, int(decision.risk)))
            return
        started = time.monotonic()
        argv = ["/bin/sh", "-lc", command]
        log.append(AuditEvent("command.run", actor, command, int(decision.risk)))
        async for chunk in self._runtime.execute(handle, argv):
            if chunk.stream == "system":
                yield LogLine("cmd", mask_secrets(chunk.text))
            elif chunk.stream == "stderr":
                yield LogLine("warn", mask_secrets(chunk.text))
            else:
                yield LogLine("out", mask_secrets(chunk.text))
        result = getattr(self._runtime, "last_result", lambda h: None)(handle)
        code = result.exit_code if result else 0
        dur = time.monotonic() - started
        yield LogLine("ok" if code == 0 else "err", f"exited {code} · {dur:.1f}s")

    async def _run_capture(self, handle: SandboxHandle, command: str) -> tuple[int, str]:
        """Run a trusted, system-internal command and capture its stdout."""
        argv = ["/bin/sh", "-lc", command]
        out: list[str] = []
        async for chunk in self._runtime.execute(handle, argv):
            if chunk.stream == "stdout":
                out.append(chunk.text)
        result = getattr(self._runtime, "last_result", lambda h: None)(handle)
        code = result.exit_code if result else 0
        return code, "\n".join(out)

    async def collect_files(
        self, handle: SandboxHandle, *, max_files: int | None = None,
        max_bytes: int | None = None,
    ) -> list[dict]:
        """List + read text files the agent created under the workdir (excluding
        the copied-in `materials/`), returning [{path, size, content}]. Runs one
        trusted python walker in-sandbox, so it's portable across runtimes and
        avoids the upload/download path-model differences."""
        max_files = max_files if max_files is not None else settings.deliverable_max_files
        max_bytes = max_bytes if max_bytes is not None else settings.deliverable_max_bytes
        walker = _WALKER.format(maxf=max_files, maxb=max_bytes, perb=max_bytes)
        b64 = base64.b64encode(walker.encode("utf-8")).decode("ascii")
        code, stdout = await self._run_capture(handle, f"echo {b64} | base64 -d | python3 -")
        if code != 0 or not stdout.strip():
            return []
        try:
            data = json.loads(stdout.strip().splitlines()[-1])
        except Exception:  # noqa: BLE001 — no parseable listing → nothing collected
            return []
        return data if isinstance(data, list) else []

    async def close_session(self, handle: SandboxHandle) -> None:
        try:
            await self._runtime.destroy(handle)
            log.append(AuditEvent("sandbox.destroy", "system", handle.id))
        except Exception:  # noqa: BLE001 — never raise from teardown
            pass


# Lazily-constructed process-wide manager (constructing a runtime may need
# Docker, so we defer until first use).
_manager: ExecutionManager | None = None


def get_execution_manager() -> ExecutionManager:
    global _manager
    if _manager is None:
        _manager = ExecutionManager()
    return _manager
