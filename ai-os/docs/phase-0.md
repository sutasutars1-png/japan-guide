# Phase 0 — Reproducible Foundation

*Report format per roadmap §2.2 / §48.*

## Implementation
- Monorepo skeleton under `ai-os/` with `apps/web` (Next.js + TS) and
  `apps/api` (FastAPI + Pydantic).
- `docker-compose.yml` brings up three services in one command:
  **Postgres 16** + **api** + **web**, wired with healthchecks and a persistent
  `pgdata` volume.
- `.env.example` documents every knob; real secrets live only in git-ignored
  `.env`.
- Dockerfiles for both apps (API on `python:3.11-slim`; Web multi-stage
  `node:22-alpine` → standalone output).
- `apps/api/app/db.py` initializes the append-only `audit_logs` table; DB init
  is best-effort so the stack still boots if Postgres is slow/absent.

## Tests
- `apps/api` builds and imports cleanly; `pytest` green (20 tests).
- `apps/web` `next build` compiles and type-checks successfully.

## Security Tests
- N/A for Phase 0 infra beyond: secrets are sourced from env only, `.env` is
  git-ignored, and no secret values appear in compose defaults (dev password is
  a placeholder, overridden by `.env`).

## Known Issues
- `docker compose up` was not executed inside this sandboxed CI environment
  (no nested-daemon guarantee); services were validated individually. Verify the
  one-command boot on a normal machine.

## Next Phase
- Phase 1: serve the UI on the API contract (done — see `phase-1.md`).

## DoD
- ✅ `git clone` → `docker compose up` starts all services (compose defined,
  images build, apps boot standalone).
