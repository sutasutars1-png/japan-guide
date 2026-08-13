"""Skill library endpoints (Phase 4, design stage 3)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import skills as skill_lib
from ..schemas import Skill

router = APIRouter(prefix="/skills", tags=["skills"])


@router.get("", response_model=list[Skill])
def list_skills(layer: str | None = None, role: str | None = None) -> list[dict]:
    """All skills, filtered by `layer` (thinking|domain|execution|overlay)
    and/or suggested `role`/stage (e.g. ?layer=domain, ?role=Builder)."""
    return skill_lib.list_skills(layer=layer, role=role)


@router.get("/layers")
def layers() -> list[str]:
    return skill_lib.LAYERS


@router.get("/roles")
def roles() -> list[str]:
    return skill_lib.ROLES


@router.get("/{skill_id}", response_model=Skill)
def get_skill(skill_id: str) -> dict:
    s = skill_lib.get_skill(skill_id)
    if s is None:
        raise HTTPException(status_code=404, detail="skill not found")
    return s
