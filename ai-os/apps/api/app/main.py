"""AI-OS · Execution Plane — FastAPI entrypoint (Phase 0 + Phase 1 contract).

Boots the API, serves the Phase 1 data shapes, and exposes the Phase 2/3 seams
(execution, policy, approvals, tools). Designed to boot even without Postgres,
Docker, or an LLM key so the UI is always reachable.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

# Load persisted keys from the git-ignored .env into the environment BEFORE
# config/secret-store read it (no-op under Docker, where env is injected).
from .env_file import load_env_file  # noqa: E402

load_env_file()

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from .config import settings  # noqa: E402
from .core.audit import log as audit_log
from .core.secrets import store as secret_store
from .db import audit_sink, init_db
from .routers import (
    agent, approvals, catalog, connections, execution, flow, llm, orchestrate,
    skills, tools,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("aios")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if init_db():  # best-effort; API works without it
        audit_log.set_sink(audit_sink)  # persist audit events to Postgres
    try:
        from .connections import bootstrap as discover_models
        discover_models()  # discover models for any provider whose key is set
    except Exception as exc:  # noqa: BLE001 — never block boot on discovery
        log.warning("model discovery skipped: %s", exc)
    log.info(
        "AI-OS API up · env=%s · sandbox=%s · masking %d secrets",
        settings.env, settings.sandbox_runtime, len(secret_store.names()),
    )
    yield


app = FastAPI(
    title="AI-OS · Execution Plane",
    version="0.1.0",
    description="Local-first AI execution platform. UI-first MVP (削減版ロードマップ v1.0).",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(catalog.router)
app.include_router(execution.router)
app.include_router(approvals.router)
app.include_router(tools.router)
app.include_router(llm.router)
app.include_router(agent.router)
app.include_router(skills.router)
app.include_router(flow.router)
app.include_router(connections.router)
app.include_router(orchestrate.router)


@app.get("/", tags=["meta"])
def root() -> dict:
    return {
        "name": "AI-OS · Execution Plane",
        "version": "0.1.0",
        "env": settings.env,
        "phase": "0+1 (foundation + mock-UI contract) with 2/3/4 interface seams",
        "docs": "/docs",
    }


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {
        "status": "ok",
        "sandbox_runtime": settings.sandbox_runtime,
        "llm_provider": settings.llm_provider,
        "secrets_masked": len(secret_store.names()),
    }
