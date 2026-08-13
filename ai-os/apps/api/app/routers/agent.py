"""Agent endpoints — drive the PLAN→EXECUTE→OBSERVE loop.

- WS   /agent/stream : give a goal, watch the loop live (the UI's "AI Goal" mode)
- POST /agent/run    : run a goal to completion, return the full log
"""
from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from ..agent_loop import AgentLoop, get_agent_loop
from ..schemas import LogLine
from ..skills import compose_system

router = APIRouter(prefix="/agent", tags=["agent"])


class GoalRequest(BaseModel):
    goal: str
    agent_name: str = "Builder"
    system: str | None = None
    max_iterations: int = 8


@router.post("/run", response_model=list[LogLine])
async def run(body: GoalRequest) -> list[dict]:
    lines: list[dict] = []
    system = body.system or compose_system(body.agent_name)
    try:
        async for line in get_agent_loop().run(
            body.goal,
            agent_name=body.agent_name,
            system=system,
            max_iterations=body.max_iterations,
        ):
            lines.append({"t": line.t, "s": line.s})
    except Exception as exc:  # noqa: BLE001
        lines.append({"t": "err", "s": f"agent error: {exc}"})
    return lines


@router.websocket("/stream")
async def stream(ws: WebSocket) -> None:
    """Send {"goal": "...", "max_iterations"?} to start; receive live log lines."""
    await ws.accept()
    try:
        msg = await ws.receive_json()
        goal = (msg or {}).get("goal", "").strip()
        if not goal:
            await ws.send_json({"t": "err", "s": "no goal provided"})
            return
        loop: AgentLoop = get_agent_loop()
        agent_name = (msg or {}).get("agent_name", "Builder")
        system = (msg or {}).get("system") or compose_system(agent_name)
        async for line in loop.run(
            goal,
            agent_name=agent_name,
            system=system,
            max_iterations=int((msg or {}).get("max_iterations", 8)),
        ):
            await ws.send_json({"t": line.t, "s": line.s})
    except WebSocketDisconnect:
        return
    except Exception as exc:  # noqa: BLE001
        try:
            await ws.send_json({"t": "err", "s": f"agent error: {exc}"})
        except Exception:
            pass
    finally:
        try:
            await ws.send_json({"t": "sys", "s": "stream closed"})
        except Exception:
            pass
