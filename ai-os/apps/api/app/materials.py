"""Materials copy-in — give a sandbox source material to work from (#4).

The isolation invariant forbids a live host filesystem mount into a sandbox
(`docker_runtime` docstring / CLAUDE.md). So instead of *mounting* a directory,
we **copy in** a filtered snapshot of chosen files via the sandbox `upload`
verb — a one-way copy, never a live mount, so the sandbox still cannot reach the
host FS.

Hard filters keep secrets and junk out of the sandbox (and out of any deliverable
collected afterwards): never copy `.env`, VCS/dependency dirs, or the app's own
local state files; skip binaries and anything over the per-file cap; stop at the
total-bytes / file-count caps.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("aios")

# Directory names never copied into a sandbox (secrets, VCS, deps, caches, state).
_DENY_DIRS = {
    ".git", ".hg", ".svn", "node_modules", ".next", "out", "dist", "build",
    "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache", ".idea",
    ".vscode", ".cache",
}
# Filenames / suffixes never copied (secret-bearing or local state).
_DENY_FILES = {".env", ".aios-agents.json", ".aios-deliverables.json"}
_DENY_SUFFIXES = (".env", ".key", ".pem", ".pfx", ".p12")
# Only copy text-ish files (agents work on source/docs, not binaries).
_ALLOW_SUFFIXES = (
    ".md", ".markdown", ".txt", ".rst", ".py", ".js", ".jsx", ".ts", ".tsx",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".csv", ".tsv", ".html",
    ".css", ".sh", ".sql", ".env.example", "Dockerfile", ".dockerfile",
)


def _eligible(name: str) -> bool:
    if name in _DENY_FILES or name.startswith("."):
        return False
    if any(name.endswith(s) for s in _DENY_SUFFIXES):
        return False
    return name == "Dockerfile" or any(name.endswith(s) for s in _ALLOW_SUFFIXES)


def iter_materials(
    root: str, *, max_files: int, max_bytes: int, per_file_bytes: int
) -> list[tuple[str, bytes]]:
    """Return [(relpath, data)] for eligible files under `root`, within caps."""
    root = os.path.abspath(os.path.expanduser(root))
    if not os.path.isdir(root):
        return []
    out: list[tuple[str, bytes]] = []
    total = 0
    for dirpath, dirnames, filenames in os.walk(root):
        # prune denied / hidden dirs in place so os.walk doesn't descend them
        dirnames[:] = [d for d in dirnames if d not in _DENY_DIRS and not d.startswith(".")]
        for fn in sorted(filenames):
            if len(out) >= max_files or total >= max_bytes:
                return out
            if not _eligible(fn):
                continue
            full = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(full) > per_file_bytes:
                    continue
                with open(full, "rb") as f:
                    data = f.read()
            except OSError as exc:  # noqa: PERF203 — best-effort, skip unreadable
                log.debug("materials skip %s: %s", full, exc)
                continue
            if b"\x00" in data:  # binary guard
                continue
            rel = os.path.relpath(full, root)
            out.append((rel, data))
            total += len(data)
    return out
