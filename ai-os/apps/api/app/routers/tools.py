"""Tool catalog endpoint — exposes registered Tools and their specs."""
from __future__ import annotations

from fastapi import APIRouter

from ..core.tools import registry
from ..core.tools.shell_tool import ShellTool
from ..core.tools.web_fetch import WebFetchTool
from ..schemas import ToolSpec

router = APIRouter(prefix="/tools", tags=["tools"])

# Register the built-in tools at import time.
if registry.get("shell.execute") is None:
    registry.register(ShellTool())
if registry.get("web.fetch") is None:
    registry.register(WebFetchTool())


@router.get("", response_model=list[ToolSpec])
def list_tools() -> list[dict]:
    return registry.specs()
