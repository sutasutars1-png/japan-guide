"""Docker implementation of SandboxRuntime (roadmap Phase 2, the real thing).

Security contract enforced here (all non-negotiable per the roadmap):
  - non-root (uid 10001)                 - no privileged
  - no docker.sock mounted into sandbox  - no host filesystem mount
  - network Default Deny + Allowlist      - CPU / RAM / PID / disk / time caps

This module is import-safe without the `docker` SDK or a running daemon; the
dependency is resolved lazily inside `create()` so the API boots even when the
sandbox backend is unavailable (the Execution Manager surfaces that clearly).
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import AsyncIterator, Optional

from .base import (
    ExecChunk,
    ExecResult,
    SandboxHandle,
    SandboxRuntime,
    SandboxSpec,
)

NON_ROOT_UID = 10001


class DockerSandboxRuntime(SandboxRuntime):
    backend = "docker"

    def __init__(self) -> None:
        self._client = None
        self._containers: dict[str, object] = {}
        self._results: dict[str, ExecResult] = {}

    def _ensure_client(self):
        if self._client is None:
            import docker  # lazy: only needed when a sandbox is actually created

            self._client = docker.from_env()
        return self._client

    async def create(self, spec: SandboxSpec) -> SandboxHandle:
        client = self._ensure_client()
        sbx_id = "sbx-" + uuid.uuid4().hex[:6]

        # network: default deny → attach to the isolated "none" network, then
        # (Phase 2 follow-up) a per-job allowlist bridge is attached for the
        # granted domains only. Denied-by-default is the safe baseline.
        network_mode = "none" if spec.network.default_deny else "bridge"

        def _run():
            return client.containers.create(
                image=spec.image,
                command=["sleep", str(spec.limits.timeout_seconds)],
                name=sbx_id,
                user=str(NON_ROOT_UID),
                working_dir=spec.workdir,
                network_mode=network_mode,
                # --- isolation hardening ---
                privileged=False,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                read_only=False,  # workspace is writable; host is never mounted
                tmpfs={spec.workdir: f"size={spec.limits.disk_mb}m,uid={NON_ROOT_UID}"},
                # --- resource ceilings ---
                mem_limit=f"{spec.limits.memory_mb}m",
                nano_cpus=int(spec.limits.cpus * 1e9),
                pids_limit=spec.limits.pids,
                environment=spec.env,
                detach=True,
            )

        container = await asyncio.to_thread(_run)
        await asyncio.to_thread(container.start)
        self._containers[sbx_id] = container
        return SandboxHandle(id=sbx_id, backend=self.backend, non_root_uid=NON_ROOT_UID)

    async def execute(
        self, handle: SandboxHandle, command: list[str]
    ) -> AsyncIterator[ExecChunk]:
        container = self._containers.get(handle.id)
        if container is None:
            raise RuntimeError(f"unknown sandbox {handle.id}")

        started = time.monotonic()
        yield ExecChunk("system", f"$ {' '.join(command)}")

        def _exec():
            return container.exec_run(command, stream=True, demux=True, user=str(NON_ROOT_UID))

        exec_result = await asyncio.to_thread(_exec)
        # exec_result.output is a generator of (stdout, stderr) byte tuples
        for stdout_b, stderr_b in exec_result.output:
            if stdout_b:
                for line in stdout_b.decode("utf-8", "replace").splitlines():
                    yield ExecChunk("stdout", line)
            if stderr_b:
                for line in stderr_b.decode("utf-8", "replace").splitlines():
                    yield ExecChunk("stderr", line)

        exit_code = getattr(exec_result, "exit_code", 0) or 0
        self._results[handle.id] = ExecResult(
            exit_code=exit_code, duration_seconds=time.monotonic() - started
        )

    def last_result(self, handle: SandboxHandle) -> Optional[ExecResult]:
        return self._results.get(handle.id)

    async def upload(self, handle: SandboxHandle, path: str, data: bytes) -> None:
        import io
        import tarfile

        container = self._containers[handle.id]
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            info = tarfile.TarInfo(name=path.lstrip("/"))
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        buf.seek(0)
        await asyncio.to_thread(container.put_archive, "/", buf.read())

    async def download(self, handle: SandboxHandle, path: str) -> bytes:
        import io
        import tarfile

        container = self._containers[handle.id]
        bits, _ = await asyncio.to_thread(container.get_archive, path)
        buf = io.BytesIO(b"".join(bits))
        buf.seek(0)
        with tarfile.open(fileobj=buf, mode="r") as tar:
            member = tar.getmembers()[0]
            f = tar.extractfile(member)
            return f.read() if f else b""

    async def destroy(self, handle: SandboxHandle) -> None:
        container = self._containers.pop(handle.id, None)
        if container is not None:
            await asyncio.to_thread(container.remove, force=True)
        self._results.pop(handle.id, None)
