"""Execution endpoints — the Phase 2 wiring point.

- POST /execution/policy-check : classify/gate a command (Phase 3, no run)
- POST /execution/run          : run a command in a sandbox, return the log
- WS   /execution/stream       : live log stream (the UI's websocket seam)
- GET  /execution/demo         : the scripted Phase 1 demo log (fake data)
- GET  /execution/audit        : tail the append-only audit log

The demo endpoint keeps the UI fully alive with fake data when no sandbox
backend is available; run/stream swap in the real thing.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .. import seed
from ..core.audit import log as audit_log
from ..core.policy import evaluate
from ..execution_manager import get_execution_manager
from ..schemas import LogLine, PolicyCheck, PolicyCheckResult, RunCommand

router = APIRouter(prefix="/execution", tags=["execution"])


@router.get("/demo", response_model=list[LogLine])
def demo() -> list[dict]:
    """The scripted Phase 1 execution — pure fake data, always available."""
    return seed.SCRIPT


@router.post("/policy-check", response_model=PolicyCheckResult)
def policy_check(body: PolicyCheck) -> PolicyCheckResult:
    d = evaluate(body.command)
    return PolicyCheckResult(
        allowed=d.allowed, risk=int(d.risk), reason=d.reason, requires_approval=d.requires_approval
    )


@router.post("/run", response_model=list[LogLine])
async def run(body: RunCommand) -> list[dict]:
    """Run a command to completion in a sandbox and return the full log.

    Falls back gracefully: if the sandbox backend is unavailable, the policy
    decision is still returned as log lines so the caller sees what happened.
    """
    mgr = get_execution_manager()
    lines: list[dict] = []
    try:
        async for line in mgr.run(
            body.command, actor=body.actor, allow_domains=body.allow_domains
        ):
            lines.append({"t": line.t, "s": line.s})
    except Exception as exc:  # noqa: BLE001
        lines.append({"t": "err", "s": f"sandbox backend unavailable: {exc}"})
    return lines


@router.get("/audit")
def audit(n: int = 100) -> list[dict]:
    return audit_log.tail(n)


@router.websocket("/stream")
async def stream(ws: WebSocket) -> None:
    """Live log stream. Send {"command": "..."} to run; receive log lines.

    With no message, it replays the scripted demo so the Phase 1 UI has a live
    feed out of the box.
    """
    await ws.accept()
    try:
        try:
            first = await asyncio.wait_for(ws.receive_json(), timeout=0.25)
        except (asyncio.TimeoutError, Exception):
            first = None

        if first and first.get("command"):
            mgr = get_execution_manager()
            async for line in mgr.run(first["command"], actor=first.get("actor", "Builder")):
                await ws.send_json({"t": line.t, "s": line.s})
        else:
            for entry in seed.SCRIPT:
                await ws.send_json(entry)
                await asyncio.sleep(0.76)
        await ws.send_json({"t": "sys", "s": "stream closed"})
    except WebSocketDisconnect:
        return
    except Exception as exc:  # noqa: BLE001
        try:
            await ws.send_json({"t": "err", "s": f"stream error: {exc}"})
        except Exception:
            pass
