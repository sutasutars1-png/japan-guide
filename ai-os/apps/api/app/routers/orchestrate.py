"""Orchestrate endpoints — goal → 統括AI plan → workers auto-dispatch.

- WS   /orchestrate/stream : give a goal, watch the whole run live (UI mode)
- POST /orchestrate        : run to completion, return the full log
"""
from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from ..orchestrator import get_orchestrator
from ..schemas import LogLine

router = APIRouter(tags=["orchestrate"])


class OrchestrateRequest(BaseModel):
    goal: str
    orchestrator: str = "Planner"


@router.post("/orchestrate", response_model=list[LogLine])
async def orchestrate(body: OrchestrateRequest) -> list[dict]:
    lines: list[dict] = []
    try:
        async for line in get_orchestrator().run(body.goal, orchestrator=body.orchestrator):
            lines.append({"t": line.t, "s": line.s})
    except Exception as exc:  # noqa: BLE001
        lines.append({"t": "err", "s": f"orchestrate error: {exc}"})
    return lines


@router.websocket("/orchestrate/stream")
async def stream(ws: WebSocket) -> None:
    """Send {"goal": "...", "orchestrator"?} to start; receive live log lines."""
    await ws.accept()
    try:
        msg = await ws.receive_json()
        goal = (msg or {}).get("goal", "").strip()
        if not goal:
            await ws.send_json({"t": "err", "s": "no goal provided"})
            return
        orchestrator = (msg or {}).get("orchestrator", "Planner")
        async for line in get_orchestrator().run(goal, orchestrator=orchestrator):
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
