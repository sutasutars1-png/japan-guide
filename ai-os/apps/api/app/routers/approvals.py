"""Approval endpoints (roadmap Phase 3 — the destructive-op yes/no gate).

A minimal in-memory approval queue: high-risk (L3/L4) actions create a pending
approval; a human decides; the decision is recorded to the audit log.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from ..core.audit import AuditEvent, log
from ..schemas import ApprovalDecision, ApprovalRequest

router = APIRouter(prefix="/approvals", tags=["approvals"])

_pending: dict[str, dict] = {}


@router.get("")
def list_pending() -> list[dict]:
    return [{"id": k, **v} for k, v in _pending.items()]


@router.post("", status_code=201)
def request_approval(req: ApprovalRequest) -> dict:
    approval_id = "apr-" + uuid.uuid4().hex[:8]
    _pending[approval_id] = req.model_dump()
    log.append(AuditEvent("approval.request", req.agent, req.action, req.risk))
    return {"id": approval_id, **req.model_dump()}


@router.post("/{approval_id}/decide")
def decide(approval_id: str, decision: ApprovalDecision) -> dict:
    req = _pending.pop(approval_id, None)
    if req is None:
        raise HTTPException(status_code=404, detail="approval not found or already decided")
    verdict = "approved" if decision.approved else "rejected"
    log.append(
        AuditEvent("approval.decide", "human", f"{verdict}: {req['action']}", req["risk"])
    )
    return {"id": approval_id, "decision": verdict, "action": req["action"]}
