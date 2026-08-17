"""Catalog endpoints — serve the Phase 1 data shapes (agents, projects, etc.).

These return the seed data that the mock UI used to hard-code. In-memory state
lets the UI's edits (toggle a capability, add an agent) round-trip through the
API today, before any database wiring.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from .. import agents_store, presets, seed
from ..schemas import (
    Agent,
    ApplyPreset,
    Capabilities,
    Comment,
    Guard,
    Preset,
    Project,
    Store,
)

router = APIRouter(tags=["catalog"])


class PresetBody(BaseModel):
    name: str
    stage: str
    skills: list[str] = Field(default_factory=list)


@router.get("/capabilities", response_model=Capabilities)
def capabilities() -> Capabilities:
    return Capabilities(capabilities=seed.CAPABILITIES, models=seed.MODELS)


@router.get("/agents", response_model=list[Agent])
def list_agents() -> list[dict]:
    return agents_store.list_agents()


@router.post("/agents", response_model=Agent, status_code=201)
def create_agent(agent: Agent) -> dict:
    return agents_store.add(agent.model_dump())


@router.put("/agents/{agent_id}", response_model=Agent)
def update_agent(agent_id: str, patch: Agent) -> dict:
    updated = agents_store.replace(agent_id, patch.model_dump())
    if updated is None:
        raise HTTPException(status_code=404, detail="agent not found")
    return updated


@router.delete("/agents/{agent_id}")
def delete_agent(agent_id: str) -> Response:
    if not agents_store.remove(agent_id):
        raise HTTPException(status_code=404, detail="agent not found")
    return Response(status_code=204)


# ---- presets (Phase 4: base-skill bundles, resettable) ----

@router.get("/presets", response_model=list[Preset])
def list_presets(stage: str | None = None) -> list[dict]:
    return presets.list_presets(stage)


@router.post("/presets", response_model=Preset, status_code=201)
def create_preset(body: PresetBody) -> dict:
    return presets.add_preset(body.name, body.stage, body.skills)


@router.put("/presets/{preset_id}", response_model=Preset)
def update_preset(preset_id: str, body: PresetBody) -> dict:
    updated = presets.update_preset(preset_id, body.model_dump())
    if updated is None:
        raise HTTPException(status_code=400, detail="preset not found or read-only (seed preset)")
    return updated


@router.delete("/presets/{preset_id}")
def delete_preset(preset_id: str) -> Response:
    if not presets.remove_preset(preset_id):
        raise HTTPException(status_code=400, detail="preset not found or read-only (seed preset)")
    return Response(status_code=204)


@router.post("/agents/{agent_id}/apply-preset", response_model=Agent)
def apply_preset(agent_id: str, body: ApplyPreset) -> dict:
    preset = presets.get_preset(body.preset_id)
    if preset is None:
        raise HTTPException(status_code=404, detail="preset not found")
    updated = agents_store.patch(agent_id, {"skills": list(preset["skills"]), "preset": preset["id"]})
    if updated is None:
        raise HTTPException(status_code=404, detail="agent not found")
    return updated


@router.post("/agents/{agent_id}/reset-preset", response_model=Agent)
def reset_preset(agent_id: str) -> dict:
    agent = agents_store.get_by_id(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    preset = presets.get_preset(agent.get("preset") or "")
    if preset is None:
        raise HTTPException(status_code=400, detail="agent has no active preset to reset to")
    updated = agents_store.patch(agent_id, {"skills": list(preset["skills"])})
    return updated


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
