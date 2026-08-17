"""Tiny JSON persistence helper — the shared pattern behind the local stores.

`agents_store` and `deliverables` each persist to a small git-ignored JSON file
next to `.env`. This factors that out so `connections`, `presets`, and `flows`
can persist the same way without copy-pasting the load/save boilerplate.

Best-effort: a read error falls back to the default; a write error is logged and
swallowed so it never breaks a request. Never store secret values here — only
non-sensitive config (model ids, skill ids, station lists).
"""
from __future__ import annotations

import json
import logging
from typing import Any

from .env_file import env_path

log = logging.getLogger("aios")


def _path(name: str):
    # e.g. name=".aios-flows.json" → ai-os/.aios-flows.json (or /srv/… in Docker)
    return env_path().parent / name


def load_json(name: str, default: Any) -> Any:
    path = _path(name)
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — corrupt/unreadable → fall back
        log.warning("%s unreadable (%s); using default", name, exc)
    return default


def save_json(name: str, data: Any) -> None:
    try:
        path = _path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 — never break a request on a write error
        log.warning("could not persist %s: %s", name, exc)
