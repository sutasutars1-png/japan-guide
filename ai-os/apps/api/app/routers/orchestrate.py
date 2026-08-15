"""Orchestrate endpoints — goal → 統括AI plan → workers auto-dispatch.

- POST /orchestrate/plan   : ask the orchestrator for a plan (for an editable UI)
- WS   /orchestrate/stream : run a goal (or a pre-approved plan) live
- POST /orchestrate        : run to completion, return the full log
"""
from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from ..orchestrator import get_orchestrator
from ..schemas import LogLine

router = APIRouter(tags=["orchestrate"])


class Step(BaseModel):
    agent: str
    task: str


class OrchestrateRequest(BaseModel):
    goal: str
    orchestrator: str = "Planner"
    steps: list[Step] | None = None  # pre-approved plan (skip planning)


class PlanRequest(BaseModel):
    goal: str
    orchestrator: str = "Planner"


class PlanResult(BaseModel):
    text: str
    plan: list[Step]


@router.post("/orchestrate/plan", response_model=PlanResult)
async def plan(body: PlanRequest) -> dict:
    return await get_orchestrator().make_plan(body.goal, orchestrator=body.orchestrator)


@router.post("/orchestrate", response_model=list[LogLine])
async def orchestrate(body: OrchestrateRequest) -> list[dict]:
    steps = [s.model_dump() for s in body.steps] if body.steps else None
    lines: list[dict] = []
    try:
        async for line in get_orchestrator().run(
            body.goal, orchestrator=body.orchestrator, steps=steps
        ):
            lines.append({"t": line.t, "s": line.s})
    except Exception as exc:  # noqa: BLE001
        lines.append({"t": "err", "s": f"orchestrate error: {exc}"})
    return lines


@router.websocket("/orchestrate/stream")
async def stream(ws: WebSocket) -> None:
    """Send {"goal", "orchestrator"?, "steps"?} to start; receive live log lines.

    If `steps` (a pre-approved/edited plan) is present, planning is skipped.
    """
    await ws.accept()
    try:
        msg = await ws.receive_json()
        goal = (msg or {}).get("goal", "").strip()
        if not goal:
            await ws.send_json({"t": "err", "s": "no goal provided"})
            return
        orchestrator = (msg or {}).get("orchestrator", "Planner")
        raw_steps = (msg or {}).get("steps")
        steps = [
            {"agent": s.get("agent", ""), "task": s.get("task", "")}
            for s in raw_steps if s.get("agent") and s.get("task")
        ] if isinstance(raw_steps, list) and raw_steps else None
        async for line in get_orchestrator().run(goal, orchestrator=orchestrator, steps=steps):
            await ws.send_json({"t": line.t, "s": line.s})
    except WebSocketDisconnect:
        return
    except Exception as exc:  # noqa: BLE001
        try:
            await ws.send_json({"t": "err", "s": f"orchestrate error: {exc}"})
        except Exception:
            pass
    finally:
        try:
            await ws.send_json({"t": "sys", "s": "stream closed"})
        except Exception:
            pass
