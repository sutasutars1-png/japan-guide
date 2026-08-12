"""LocalSubprocessRuntime — DEV-ONLY fallback (roadmap explicitly warns: NOT isolated).

This exists so the loop can be exercised on a machine without Docker. It is
NOT a security boundary: a subprocess shares the host kernel and filesystem.
It refuses to run unless AIOS_ALLOW_UNSAFE_LOCAL=1 is set, and it still applies
rlimits + a wall-clock timeout + a scratch workdir so accidents are contained,
never malice. Production always uses the Docker runtime.
"""
from __future__ import annotations

import asyncio
import os
import resource
import shutil
import tempfile
import time
import uuid
from typing import AsyncIterator, Optional

from .base import ExecChunk, ExecResult, SandboxHandle, SandboxRuntime, SandboxSpec


class LocalSubprocessRuntime(SandboxRuntime):
    backend = "local"

    def __init__(self) -> None:
        if os.getenv("AIOS_ALLOW_UNSAFE_LOCAL") != "1":
            raise RuntimeError(
                "LocalSubprocessRuntime is DEV-ONLY and NOT isolated. "
                "Set AIOS_ALLOW_UNSAFE_LOCAL=1 to acknowledge, or use SANDBOX_RUNTIME=docker."
            )
        self._dirs: dict[str, str] = {}
        self._limits: dict[str, object] = {}
        self._results: dict[str, ExecResult] = {}

    async def create(self, spec: SandboxSpec) -> SandboxHandle:
        sbx_id = "sbx-" + uuid.uuid4().hex[:6]
        workdir = tempfile.mkdtemp(prefix=f"aios-{sbx_id}-")
        self._dirs[sbx_id] = workdir
        self._limits[sbx_id] = spec.limits
        return SandboxHandle(id=sbx_id, backend=self.backend, non_root_uid=os.getuid())

    def _preexec(self, limits) -> None:  # pragma: no cover - runs in child process
        # Best-effort containment: address space, cpu time, file size, procs.
        resource.setrlimit(
            resource.RLIMIT_AS,
            (limits.memory_mb * 1024 * 1024, limits.memory_mb * 1024 * 1024),
        )
        resource.setrlimit(resource.RLIMIT_CPU, (limits.timeout_seconds, limits.timeout_seconds))
        resource.setrlimit(
            resource.RLIMIT_FSIZE,
            (limits.disk_mb * 1024 * 1024, limits.disk_mb * 1024 * 1024),
        )
        try:
            resource.setrlimit(resource.RLIMIT_NPROC, (limits.pids, limits.pids))
        except (ValueError, OSError):
            pass
        os.setsid()

    async def execute(
        self, handle: SandboxHandle, command: list[str]
    ) -> AsyncIterator[ExecChunk]:
        workdir = self._dirs[handle.id]
        limits = self._limits[handle.id]
        started = time.monotonic()
        yield ExecChunk("system", f"$ {' '.join(command)}")

        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=workdir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            preexec_fn=lambda: self._preexec(limits),
            env={"PATH": os.getenv("PATH", "/usr/bin:/bin"), "HOME": workdir},
        )

        timed_out = False

        async def _pump(reader, stream):
            async for raw in reader:
                yield ExecChunk(stream, raw.decode("utf-8", "replace").rstrip("\n"))

        async def _merge():
            out = _pump(proc.stdout, "stdout")
            err = _pump(proc.stderr, "stderr")
            # simple sequential drain is fine for line-oriented dev output
            async for c in out:
                yield c
            async for c in err:
                yield c

        try:
            async for chunk in _merge():
                yield chunk
            await asyncio.wait_for(proc.wait(), timeout=limits.timeout_seconds)
        except asyncio.TimeoutError:
            timed_out = True
            proc.kill()
            yield ExecChunk("system", f"killed: exceeded {limits.timeout_seconds}s timeout")

        self._results[handle.id] = ExecResult(
            exit_code=proc.returncode if proc.returncode is not None else -1,
            duration_seconds=time.monotonic() - started,
            timed_out=timed_out,
            killed_reason="timeout" if timed_out else None,
        )

    def last_result(self, handle: SandboxHandle) -> Optional[ExecResult]:
        return self._results.get(handle.id)

    async def upload(self, handle: SandboxHandle, path: str, data: bytes) -> None:
        full = os.path.join(self._dirs[handle.id], path.lstrip("/"))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as f:
            f.write(data)

    async def download(self, handle: SandboxHandle, path: str) -> bytes:
        full = os.path.join(self._dirs[handle.id], path.lstrip("/"))
        with open(full, "rb") as f:
            return f.read()

    async def destroy(self, handle: SandboxHandle) -> None:
        workdir = self._dirs.pop(handle.id, None)
        if workdir and os.path.isdir(workdir):
            shutil.rmtree(workdir, ignore_errors=True)
        self._limits.pop(handle.id, None)
        self._results.pop(handle.id, None)
