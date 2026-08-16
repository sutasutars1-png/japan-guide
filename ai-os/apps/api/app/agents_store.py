"""Agent store — the single source of truth for agent config, now persisted.

Both the catalog router (UI edits) and the agent loop read from here, so what
the user configures (model, skills, applied preset) is what the loop runs. State
is saved to a small git-ignored JSON file next to `.env`, so a model change made
in the UI **survives an API restart** instead of resetting to the seed.

Falls back to `seed.AGENTS` when no state file exists (fresh install). Best-effort
persistence: a write failure never breaks a request.
"""
from __future__ import annotations

import json
import logging
from copy import deepcopy

from . import seed
from .env_file import env_path

log = logging.getLogger("aios")


def _state_path():
    # Next to the .env: ai-os/.aios-agents.json (repo) or /srv/.aios-agents.json.
    return env_path().parent / ".aios-agents.json"


def _load() -> list[dict]:
    path = _state_path()
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return data
    except Exception as exc:  # noqa: BLE001 — corrupt/unreadable → fall back to seed
        log.warning("agent state unreadable (%s); using seed", exc)
    return deepcopy(seed.AGENTS)


_agents: list[dict] = _load()


def _save() -> None:
    try:
        path = _state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_agents, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 — never break a request on a write error
        log.warning("could not persist agent state: %s", exc)


def list_agents() -> list[dict]:
    return _agents


def get_by_id(agent_id: str) -> dict | None:
    return next((a for a in _agents if a["id"] == agent_id), None)


def get_by_name(name: str) -> dict | None:
    return next((a for a in _agents if a["name"] == name), None)


def add(agent: dict) -> dict:
    _agents.append(agent)
    _save()
    return agent


def remove(agent_id: str) -> bool:
    for i, a in enumerate(_agents):
        if a["id"] == agent_id:
            del _agents[i]
            _save()
            return True
    return False


def replace(agent_id: str, agent: dict) -> dict | None:
    for i, a in enumerate(_agents):
        if a["id"] == agent_id:
            _agents[i] = agent
            _save()
            return agent
    return None


def patch(agent_id: str, changes: dict) -> dict | None:
    a = get_by_id(agent_id)
    if a is None:
        return None
    a.update(changes)
    _save()
    return a


def skills_for(name: str) -> list[str]:
    a = get_by_name(name)
    return list(a.get("skills", [])) if a else []


def reset_to_seed() -> None:
    """Discard persisted state and reload the seed (used by tests)."""
    global _agents
    _agents = deepcopy(seed.AGENTS)
    _save()
