"""Deliverable endpoints — save a run's 成果物, list them, and download.

- GET    /deliverables                 : list saved deliverables (metadata only)
- GET    /deliverables/{id}            : one deliverable, with artifact bodies
- POST   /deliverables                 : save a deliverable (from artifacts or log lines)
- GET    /deliverables/{id}/download   : download as md | txt | json (?format=)
- DELETE /deliverables/{id}            : delete one

An orchestration run auto-saves its deliverable (see `orchestrator.py`); this
POST lets the UI also save agent/flow runs it captured client-side.
"""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from .. import deliverables
from ..core.audit import AuditEvent, log

router = APIRouter(tags=["deliverables"])


class ArtifactIn(BaseModel):
    agent: str = "AI"
    task: str = ""
    content: str


class SaveDeliverable(BaseModel):
    goal: str = ""
    title: str | None = None
    source: str = "manual"
    orchestrator: str | None = None
    status: str = "complete"
    artifacts: list[ArtifactIn] = Field(default_factory=list)
    # Fallback: raw streamed log lines the UI captured; the store reconstructs
    # per-step artifacts from them when `artifacts` isn't supplied.
    lines: list[dict] = Field(default_factory=list)


@router.get("/deliverables")
def list_all() -> list[dict]:
    return deliverables.list_deliverables()


@router.get("/deliverables/{deliverable_id}")
def get_one(deliverable_id: str) -> dict:
    item = deliverables.get(deliverable_id)
    if item is None:
        raise HTTPException(status_code=404, detail="no such deliverable")
    return item


@router.post("/deliverables")
def save(body: SaveDeliverable) -> dict:
    artifacts = [a.model_dump() for a in body.artifacts]
    if not artifacts and body.lines:
        artifacts = deliverables.artifacts_from_lines(body.lines)
    if not artifacts:
        raise HTTPException(status_code=400, detail="no content to save")
    item = deliverables.save(
        goal=body.goal,
        artifacts=artifacts,
        source=body.source,
        orchestrator=body.orchestrator,
        title=body.title,
        status=body.status,
    )
    log.append(AuditEvent("deliverable.save", "human", item["id"]))
    return item


def _attachment(body, media_type: str, filename: str, ascii_stem: str) -> Response:
    # HTTP headers are latin-1; a Japanese filename needs RFC 5987 encoding, with
    # an ASCII fallback for old clients.
    ext = filename.rsplit(".", 1)[-1] if "." in filename else "bin"
    disposition = (
        f"attachment; filename=\"{ascii_stem}.{ext}\"; "
        f"filename*=UTF-8''{quote(filename)}"
    )
    return Response(content=body, media_type=media_type,
                    headers={"Content-Disposition": disposition})


@router.get("/deliverables/{deliverable_id}/download")
def download(deliverable_id: str, format: str = "md") -> Response:
    item = deliverables.get(deliverable_id)
    if item is None:
        raise HTTPException(status_code=404, detail="no such deliverable")
    log.append(AuditEvent("deliverable.download", "human", f"{deliverable_id} · {format}"))
    if (format or "").lower() == "zip":  # whole bundle as a ZIP (bytes)
        body, media_type, filename = deliverables.export_zip(item)
        return _attachment(body, media_type, filename, deliverable_id)
    try:
        body, media_type, filename = deliverables.export(item, format)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _attachment(body, media_type, filename, deliverable_id)


@router.get("/deliverables/{deliverable_id}/artifacts/{index}/download")
def download_artifact(deliverable_id: str, index: int, format: str = "raw") -> Response:
    """Download ONE artifact (file or report) of a deliverable."""
    item = deliverables.get(deliverable_id)
    if item is None:
        raise HTTPException(status_code=404, detail="no such deliverable")
    try:
        body, media_type, filename = deliverables.export_artifact(item, index, format)
    except IndexError:
        raise HTTPException(status_code=404, detail="no such artifact")
    log.append(AuditEvent("deliverable.download_artifact", "human", f"{deliverable_id}#{index}"))
    return _attachment(body, media_type, filename, f"{deliverable_id}-{index}")


@router.delete("/deliverables/{deliverable_id}")
def delete(deliverable_id: str) -> Response:
    if not deliverables.remove(deliverable_id):
        raise HTTPException(status_code=404, detail="no such deliverable")
    log.append(AuditEvent("deliverable.delete", "human", deliverable_id))
    return Response(status_code=204)
