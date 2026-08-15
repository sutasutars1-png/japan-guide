"""Persist secret-bearing settings to the git-ignored `.env` (Phase 4 · Connections).

The golden rule (Phase 3) is unchanged: secret VALUES live only in `.env` and the
in-process Secret Store, and never reach an LLM, a log, or stdout. This helper is
the *write* side — when the user sets an API key in the UI, we upsert it into
`ai-os/.env` so it survives a restart, register it for masking, and load it into
the live process env.

`.env` is git-ignored (`ai-os/.gitignore`), so keys are never committed.
"""
from __future__ import annotations

import os
import re
import threading
from pathlib import Path

_lock = threading.Lock()

def _default_env() -> Path:
    """Where to persist keys, robust to layout.

    - Repo checkout: …/ai-os/apps/api/app/env_file.py → ai-os/.env (parents[3]).
    - Docker image: /srv/app/env_file.py has only 3 parents, so parents[3] would
      IndexError — fall back to the app package's parent (WORKDIR, e.g. /srv/.env).
    Overridable at runtime via AIOS_ENV_FILE.
    """
    p = Path(__file__).resolve()
    parents = p.parents
    if len(parents) >= 4 and (parents[3] / "apps").is_dir():
        return parents[3] / ".env"          # monorepo root (ai-os/)
    return (parents[1] if len(parents) >= 2 else p.parent) / ".env"


# ai-os/.env in a checkout; /srv/.env in the container.
_DEFAULT_ENV = _default_env()


def env_path() -> Path:
    override = os.getenv("AIOS_ENV_FILE")
    return Path(override) if override else _DEFAULT_ENV


def load_env_file() -> None:
    """Load `KEY=value` pairs from the .env into os.environ, WITHOUT overriding
    vars already set. Docker injects env itself (those win); when the API runs on
    the host this makes keys the user saved via the UI survive a restart.
    """
    path = env_path()
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if key and key not in os.environ:
            os.environ[key] = val


_VALID_KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")


def set_env_value(key: str, value: str) -> None:
    """Upsert `KEY=value` in `.env` and in the live process environment.

    Idempotent and line-preserving: an existing key is rewritten in place, a new
    one is appended. The file is created (0600) if missing. Never logs `value`.
    """
    if not _VALID_KEY.match(key):
        raise ValueError(f"invalid env key: {key!r}")
    with _lock:
        path = env_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = path.read_text().splitlines() if path.exists() else []
        prefix = f"{key}="
        replaced = False
        for i, line in enumerate(lines):
            # match `KEY=…` and `#KEY=…` (commented placeholder), ignore other text
            stripped = line.lstrip("#").lstrip()
            if stripped.startswith(prefix):
                lines[i] = f"{key}={value}"
                replaced = True
                break
        if not replaced:
            lines.append(f"{key}={value}")
        path.write_text("\n".join(lines) + "\n")
        try:
            os.chmod(path, 0o600)  # keys are readable only by the owner
        except OSError:
            pass
        os.environ[key] = value


def unset_env_value(key: str) -> None:
    """Remove `KEY=` from `.env` and the live environment (comment it out)."""
    if not _VALID_KEY.match(key):
        raise ValueError(f"invalid env key: {key!r}")
    with _lock:
        path = env_path()
        if path.exists():
            lines = path.read_text().splitlines()
            out = []
            prefix = f"{key}="
            for line in lines:
                stripped = line.lstrip("#").lstrip()
                out.append(f"# {key}=" if stripped.startswith(prefix) else line)
            path.write_text("\n".join(out) + "\n")
        os.environ.pop(key, None)
