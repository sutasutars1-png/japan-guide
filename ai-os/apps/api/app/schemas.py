"""Pydantic schemas — the API contract, derived directly from the Phase 1 mock UI.

Per the roadmap's core strategy, the UI's data shapes *are* the spec. These
models mirror exactly what `aiosmockui.tsx` renders, so the frontend can drop
its fake data and read the same shapes from the API unchanged.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class Agent(BaseModel):
    id: str
    name: str
    model: str
    state: str = "idle"  # idle | run | done
    caps: list[str] = Field(default_factory=list)
    role: str = ""


class Project(BaseModel):
    id: str
    name: str
    status: str  # run | review | idle
    data: float


class Guard(BaseModel):
    name: str
    desc: str
    hits: str = "—"


class Store(BaseModel):
    name: str
    kind: str
    loc: str
    size: float
    enc: bool


class LogLine(BaseModel):
    t: str  # sys | cmd | out | ok | warn | err | halt | fold
    s: str


class Comment(BaseModel):
    who: str
    model: str
    type: str  # proceed | answer | approval
    risk: int
    text: str


class ApprovalRequest(BaseModel):
    agent: str
    action: str
    target: str
    risk: int
    reason: str
    changes: str


class ApprovalDecision(BaseModel):
    approved: bool


class RunCommand(BaseModel):
    command: str
    actor: str = "Builder"
    allow_domains: list[str] = Field(default_factory=list)


class PolicyCheck(BaseModel):
    command: str


class PolicyCheckResult(BaseModel):
    allowed: bool
    risk: int
    reason: str
    requires_approval: bool


class ToolSpec(BaseModel):
    name: str
    description: str
    capability: str
    risk: int
    input_schema: dict


class Capabilities(BaseModel):
    capabilities: list[str]
    models: list[str]
