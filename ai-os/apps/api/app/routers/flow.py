"""Flow endpoints — run a multi-agent pipeline.

- GET  /flows        : available flow definitions
- WS   /flow/stream  : run a goal through a flow, watch live
- POST /flow/run     : run a goal through a flow, return the full log
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from ..flow import get_flow, get_flow_runner, list_flows
from ..schemas import LogLine

router = APIRouter(tags=["flow"])


class Flow(BaseModel):
    id: str
    name: str
    max_iterations: int
    stations: list[dict]


class FlowRunRequest(BaseModel):
    goal: str
    flow_id: str = "flow.default"


@router.get("/flows", response_model=list[Flow])
def flows() -> list[dict]:
    return list_flows()


@router.post("/flow/run", response_model=list[LogLine])
async def run(body: FlowRunRequest) -> list[dict]:
    flow = get_flow(body.flow_id)
    if flow is None:
        raise HTTPException(status_code=404, detail="flow not found")
    lines: list[dict] = []
    try:
        async for line in get_flow_runner().run(body.goal, flow):
            lines.append({"t": line.t, "s": line.s})
    except Exception as exc:  # noqa: BLE001
        lines.append({"t": "err", "s": f"flow error: {exc}"})
    return lines


@router.websocket("/flow/stream")
async def stream(ws: WebSocket) -> None:
    """Send {"goal": "...", "flow_id"?} to start; receive live log lines."""
    await ws.accept()
    try:
        msg = await ws.receive_json()
        goal = (msg or {}).get("goal", "").strip()
        flow = get_flow((msg or {}).get("flow_id", "flow.default"))
        if not goal:
            await ws.send_json({"t": "err", "s": "no goal provided"})
            return
        if flow is None:
            await ws.send_json({"t": "err", "s": "flow not found"})
            return
        async for line in get_flow_runner().run(goal, flow):
            await ws.send_json({"t": line.t, "s": line.s})
    except WebSocketDisconnect:
        return
    except Exception as exc:  # noqa: BLE001
        try:
            await ws.send_json({"t": "err", "s": f"flow error: {exc}"})
        except Exception:
            pass
    finally:
        try:
            await ws.send_json({"t": "sys", "s": "stream closed"})
        except Exception:
            pass
