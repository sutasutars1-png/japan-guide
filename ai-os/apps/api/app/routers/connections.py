"""Connections endpoints (Phase 4) — providers, keys, live models, manual bridge.

- GET  /connections               : providers + masked key hint + discovered models
- PUT  /connections/{id}/key      : set an API key (persist to .env + mask), discover
- POST /connections/{id}/refresh  : re-discover models from the stored key
- DELETE /connections/{id}/key    : forget a key
- POST /connections/{id}/models   : add a model to a manual provider (curated)
- GET  /models                    : flat model list for the UI's pickers
- GET  /manual/pending            : prompts awaiting a human paste
- POST /manual/submit             : deliver a pasted reply into a waiting run

Keys are never returned in the clear — only a masked hint — and never logged.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import connections
from ..manual_bridge import bridge

router = APIRouter(tags=["connections"])


class KeyBody(BaseModel):
    key: str


class ModelBody(BaseModel):
    model: str


class ManualSubmit(BaseModel):
    id: str
    reply: str


@router.get("/connections")
def list_connections() -> list[dict]:
    return connections.list_connections()


@router.put("/connections/{provider_id}/key")
def set_key(provider_id: str, body: KeyBody) -> dict:
    try:
        return connections.set_key(provider_id, body.key)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown provider")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/connections/{provider_id}/refresh")
def refresh(provider_id: str) -> dict:
    try:
        return connections.refresh_models(provider_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown provider")


@router.delete("/connections/{provider_id}/key")
def clear_key(provider_id: str) -> dict:
    try:
        return connections.clear_key(provider_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown provider")


@router.post("/connections/{provider_id}/models")
def add_model(provider_id: str, body: ModelBody) -> dict:
    try:
        return connections.add_manual_model(provider_id, body.model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/models")
def models() -> list[dict]:
    return connections.all_models()


# ---- manual bridge ----------------------------------------------------------

@router.get("/manual/pending")
def manual_pending() -> list[dict]:
    return bridge.list()


@router.post("/manual/submit")
def manual_submit(body: ManualSubmit) -> dict:
    ok = bridge.submit(body.id, body.reply)
    if not ok:
        raise HTTPException(status_code=404, detail="no such pending prompt")
    return {"ok": True}
