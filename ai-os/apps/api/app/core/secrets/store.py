"""Secret Store + masking (roadmap Phase 3 — "the heart of leak prevention").

The invariant: a secret VALUE must never appear in an LLM prompt, a log line,
or stdout. The store holds values keyed by name; everything that leaves the
process passes through `mask_secrets`, which redacts any registered value.

MVP storage is in-process/env-backed. The interface is what matters — a real
KMS/vault backend drops in behind `SecretStore` without touching callers.
"""
from __future__ import annotations

import os
import re
import threading

_MASK = "••••••••"


class SecretStore:
    def __init__(self) -> None:
        self._values: dict[str, str] = {}
        self._lock = threading.Lock()
        self._pattern: re.Pattern[str] | None = None
        self._load_from_env()

    def _load_from_env(self) -> None:
        # Well-known secret-bearing env vars are auto-registered for masking.
        for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
                    "GOOGLE_API_KEY", "GITHUB_TOKEN", "POSTGRES_PASSWORD"):
            val = os.getenv(key)
            if val:
                self.set(key, val)

    def set(self, name: str, value: str) -> None:
        if not value:
            return
        with self._lock:
            self._values[name] = value
            self._rebuild_pattern()

    def get(self, name: str) -> str | None:
        return self._values.get(name)

    def names(self) -> list[str]:
        return sorted(self._values.keys())

    def _rebuild_pattern(self) -> None:
        # Longest values first so a value that contains another masks fully.
        vals = sorted((v for v in self._values.values() if len(v) >= 6), key=len, reverse=True)
        self._pattern = re.compile("|".join(re.escape(v) for v in vals)) if vals else None

    def mask(self, text: str) -> str:
        if not text or self._pattern is None:
            return text
        return self._pattern.sub(_MASK, text)


# Process-wide store.
store = SecretStore()


def mask_secrets(text: str) -> str:
    """Redact every registered secret value from `text`. Cheap; call liberally."""
    return store.mask(text)
