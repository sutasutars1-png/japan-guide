"""SandboxRuntime — abstraction boundary #1 (roadmap §2.1).

The whole point of this interface is that the isolation *mechanism* can be
swapped (Docker → gVisor → Firecracker) without rewriting the Execution
Manager. Implementations must never leak host access; the contract below is
the security surface every backend has to honor.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional


@dataclass
class ResourceLimits:
    """Ceilings enforced on every sandbox (roadmap §Phase 2 security must-haves)."""

    cpus: float = 2.0
    memory_mb: int = 4096
    pids: int = 128
    disk_mb: int = 2048
    timeout_seconds: int = 600


@dataclass
class NetworkPolicy:
    """Default Deny + Allowlist. Outbound is off unless a domain is granted."""

    default_deny: bool = True
    allow_domains: list[str] = field(default_factory=list)


@dataclass
class SandboxSpec:
    image: str = "python:3.11-slim"
    workdir: str = "/workspace"
    non_root: bool = True
    limits: ResourceLimits = field(default_factory=ResourceLimits)
    network: NetworkPolicy = field(default_factory=NetworkPolicy)
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class SandboxHandle:
    id: str
    backend: str
    non_root_uid: Optional[int] = None


@dataclass
class ExecChunk:
    """A streamed line of output. stream is 'stdout' | 'stderr' | 'system'."""

    stream: str
    text: str


@dataclass
class ExecResult:
    exit_code: int
    duration_seconds: float
    timed_out: bool = False
    killed_reason: Optional[str] = None


class SandboxRuntime(abc.ABC):
    """create / execute / upload / download / destroy — the five verbs (§2.1)."""

    backend: str = "abstract"

    @abc.abstractmethod
    async def create(self, spec: SandboxSpec) -> SandboxHandle:
        ...

    @abc.abstractmethod
    async def execute(
        self, handle: SandboxHandle, command: list[str]
    ) -> AsyncIterator[ExecChunk]:
        """Run a command, yielding live output chunks. Terminal state is
        signalled by the accompanying ExecResult stored on the handle/manager.
        """
        ...

    @abc.abstractmethod
    async def upload(self, handle: SandboxHandle, path: str, data: bytes) -> None:
        ...

    @abc.abstractmethod
    async def download(self, handle: SandboxHandle, path: str) -> bytes:
        ...

    @abc.abstractmethod
    async def destroy(self, handle: SandboxHandle) -> None:
        ...
