# CLAUDE.md — AI-OS · Execution Plane

Guidance for AI coding agents working in this monorepo.

## What this is

A local-first AI execution platform following the *削減版ロードマップ v1.0*.
The strategy is **UI-first**: a beautiful UI built on fake data defines the API
contract; real execution is wired in behind it. Two things are load-bearing and
must never be removed:

1. **Abstraction boundaries** — `SandboxRuntime`, `Tool`, `LLMProvider`
   (in `apps/api/app/core/`). Add implementations behind them; never bypass them.
2. **Safety primitives** — sandbox isolation, secret masking, audit log, and the
   destructive-operation approval gate. Never weaken these for convenience.

## Layout

- `apps/web` — Next.js + TS. The UI lives in `components/AiOsApp.tsx` (a ported
  design mock, `@ts-nocheck`); the typed boundary is `lib/api.ts`.
- `apps/api` — FastAPI + Pydantic. Contract in `schemas.py`; orchestration in
  `execution_manager.py`; safety + boundaries in `core/`.

## Conventions

- **The UI's data shapes are the spec.** If the UI needs a field, add it to
  `schemas.py` and `seed.py` first, then serve it.
- **Boot must survive missing infra.** The API starts without Postgres, Docker,
  or an LLM key. Keep new dependencies lazily imported (see `docker_runtime.py`,
  `anthropic_provider.py`).
- **Sandbox default is Docker.** The `local` runtime is dev-only and refuses to
  run without `AIOS_ALLOW_UNSAFE_LOCAL=1`. Never make `local` the default.
- **Everything consequential is audited.** Route new side-effects through
  `core.audit.log`, and mask output through `core.secrets.mask_secrets`.
- **Every phase ends with a doc.** Use the report format
  `Implementation / Tests / Security Tests / Known Issues / Next Phase` in `docs/`.

## Commands

```bash
# API
cd apps/api && pip install -r requirements.txt && pytest
uvicorn app.main:app --reload

# Web
cd apps/web && npm install && npm run build   # build also type-checks
npm run dev

# Full stack
docker compose up
```

## Security guardrails (do not regress)

- non-root sandboxes, no `docker.sock`/host mount into sandboxes, resource caps
- network Default Deny + Allowlist
- dangerous-command block list in `core/policy/commands.py`
- L3/L4 actions require human approval
- secrets never reach an LLM, log, or stdout
