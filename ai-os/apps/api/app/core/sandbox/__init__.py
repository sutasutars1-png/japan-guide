"""Sandbox factory — pick the backend without the caller knowing which one."""
from __future__ import annotations

import os

from .base import (
    ExecChunk,
    ExecResult,
    NetworkPolicy,
    ResourceLimits,
    SandboxHandle,
    SandboxRuntime,
    SandboxSpec,
)

__all__ = [
    "ExecChunk",
    "ExecResult",
    "NetworkPolicy",
    "ResourceLimits",
    "SandboxHandle",
    "SandboxRuntime",
    "SandboxSpec",
    "get_sandbox_runtime",
]

_singleton: SandboxRuntime | None = None


def get_sandbox_runtime() -> SandboxRuntime:
    """Return the process-wide runtime chosen by SANDBOX_RUNTIME."""
    global _singleton
    if _singleton is not None:
        return _singleton

    backend = os.getenv("SANDBOX_RUNTIME", "docker").lower()
    if backend == "local":
        from .local_runtime import LocalSubprocessRuntime

        _singleton = LocalSubprocessRuntime()
    else:
        from .docker_runtime import DockerSandboxRuntime

        _singleton = DockerSandboxRuntime()
    return _singleton
