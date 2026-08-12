"""Catalog endpoints — serve the Phase 1 data shapes (agents, projects, etc.).

These return the seed data that the mock UI used to hard-code. In-memory state
lets the UI's edits (toggle a capability, add an agent) round-trip through the
API today, before any database wiring.
"""
from __future__ import annotations

from copy import deepcopy

from fastapi import APIRouter, HTTPException

from .. import seed
from ..schemas import Agent, Capabilities, Comment, Guard, Project, Store

router = APIRouter(tags=["catalog"])

# Mutable in-memory mirrors of the seed so the UI can edit them this session.
_agents: list[dict] = deepcopy(seed.AGENTS)


@router.get("/capabilities", response_model=Capabilities)
def capabilities() -> Capabilities:
    return Capabilities(capabilities=seed.CAPABILITIES, models=seed.MODELS)


@router.get("/agents", response_model=list[Agent])
def list_agents() -> list[dict]:
    return _agents


@router.post("/agents", response_model=Agent, status_code=201)
def create_agent(agent: Agent) -> dict:
    _agents.append(agent.model_dump())
    return agent.model_dump()


@router.put("/agents/{agent_id}", response_model=Agent)
def update_agent(agent_id: str, patch: Agent) -> dict:
    for i, a in enumerate(_agents):
        if a["id"] == agent_id:
            _agents[i] = patch.model_dump()
            return _agents[i]
    raise HTTPException(status_code=404, detail="agent not found")


@router.get("/projects", response_model=list[Project])
def list_projects() -> list[dict]:
    return seed.PROJECTS


@router.get("/guardrails", response_model=list[Guard])
def guardrails() -> list[dict]:
    return seed.GUARDS


@router.get("/stores", response_model=list[Store])
def stores() -> list[dict]:
    return seed.STORES


@router.get("/comments", response_model=list[Comment])
def comments() -> list[dict]:
    return seed.COMMENTS
