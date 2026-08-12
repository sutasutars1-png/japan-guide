"""Dangerous-command detection + risk classification (roadmap Phase 3).

Two jobs:
  1. BLOCK a small set of catastrophic commands outright (rm -rf /, mkfs, dd,
     fork bombs, curl|bash …) — these never run, even with approval.
  2. CLASSIFY a command's risk level (L0–L4) so the Approval gate knows when to
     pause for a human (any L3/L4 halts).

Detection is best-effort defense-in-depth, not the primary boundary — the
sandbox is. But it stops the obvious foot-guns before they reach the sandbox.
"""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

from ..tools.base import RiskLevel

# Patterns that are refused outright. Ordered, matched against the raw string.
_BLOCK_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("recursive force delete of a root path", re.compile(r"\brm\s+(-[a-zA-Z]*\s+)*-?[rf]{1,2}f?\s+(/|/\*|~|\$HOME)\s*$")),
    ("filesystem format", re.compile(r"\bmkfs(\.\w+)?\b")),
    ("raw disk write", re.compile(r"\bdd\b.*\bof=/dev/(sd|nvme|hd|xvd)")),
    ("overwrite block device", re.compile(r">\s*/dev/(sd|nvme|hd|xvd)\w*")),
    ("pipe remote script to shell", re.compile(r"\b(curl|wget)\b[^|;&]*\|\s*(sudo\s+)?(ba)?sh\b")),
    ("fork bomb", re.compile(r":\(\)\s*\{\s*:\|:\s*&\s*\}\s*;")),
    ("shutdown/reboot host", re.compile(r"\b(shutdown|reboot|halt|poweroff)\b")),
    ("chmod the whole filesystem", re.compile(r"\bchmod\s+-R\s+\d{3,4}\s+/\s*$")),
]

# Substrings that push a command up the risk ladder (classification only).
_HIGH = ["git push", "docker ", "systemctl", "kill ", "chown ", "chmod "]
_CRITICAL = ["prod", "production", "drop table", "drop database", "truncate ", "delete from"]


@dataclass
class PolicyDecision:
    allowed: bool
    risk: RiskLevel
    reason: str
    requires_approval: bool


def evaluate(command: str) -> PolicyDecision:
    """Evaluate a shell command string against the policy."""
    normalized = command.strip()

    for reason, pat in _BLOCK_PATTERNS:
        if pat.search(normalized):
            return PolicyDecision(
                allowed=False,
                risk=RiskLevel.CRITICAL,
                reason=f"blocked: {reason}",
                requires_approval=False,
            )

    lowered = normalized.lower()
    risk = _classify(lowered)
    requires_approval = risk >= RiskLevel.HIGH
    return PolicyDecision(
        allowed=True,
        risk=risk,
        reason="ok" if not requires_approval else "high-risk action requires human approval",
        requires_approval=requires_approval,
    )


def _classify(lowered: str) -> RiskLevel:
    if any(k in lowered for k in _CRITICAL):
        return RiskLevel.CRITICAL
    if any(k in lowered for k in _HIGH):
        return RiskLevel.HIGH
    try:
        tokens = shlex.split(lowered)
    except ValueError:
        tokens = lowered.split()
    head = tokens[0] if tokens else ""
    if head in {"rm", "mv", "sudo", "apt", "apt-get", "pip", "npm"} or ">" in lowered:
        return RiskLevel.MEDIUM
    if head in {"ls", "cat", "pwd", "echo", "grep", "find", "head", "tail", "git"}:
        # git subcommands that only read stay L0; writes were caught above
        return RiskLevel.READ_ONLY if head != "git" else RiskLevel.LOW
    return RiskLevel.LOW
