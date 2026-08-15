"""In-memory agent store — the single source of truth for agent config.

Both the catalog router (UI edits) and the agent loop read from here, so what
the user configures (skills, applied preset) is what the loop actually runs.
Seeded from `seed.AGENTS`; a DB-backed store drops in behind the same functions.
"""
from __future__ import annotations

from copy import deepcopy

from . import seed

_agents: list[dict] = deepcopy(seed.AGENTS)


def list_agents() -> list[dict]:
    return _agents


def get_by_id(agent_id: str) -> dict | None:
    return next((a for a in _agents if a["id"] == agent_id), None)


def get_by_name(name: str) -> dict | None:
    return next((a for a in _agents if a["name"] == name), None)


def add(agent: dict) -> dict:
    _agents.append(agent)
    return agent


def replace(agent_id: str, agent: dict) -> dict | None:
    for i, a in enumerate(_agents):
        if a["id"] == agent_id:
            _agents[i] = agent
            return agent
    return None


def remove(agent_id: str) -> bool:
    for i, a in enumerate(_agents):
        if a["id"] == agent_id:
            del _agents[i]
            return True
    return False


def patch(agent_id: str, changes: dict) -> dict | None:
    a = get_by_id(agent_id)
    if a is None:
        return None
    a.update(changes)
    return a


def skills_for(name: str) -> list[str]:
    a = get_by_name(name)
    return list(a.get("skills", [])) if a else []
