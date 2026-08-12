# AI-OS · Execution Plane

A local-first, safety-first **AI execution platform** — a control plane where AI
agents can write and run code inside isolated sandboxes, with every dangerous
action gated behind a human yes/no. Built to the *削減版ロードマップ v1.0*
(reduced MVP roadmap): UI-first, reproducible, and cost-free to run locally
(only the LLM is pay-per-use).

> **Status:** Phase 0 (foundation) + Phase 1 (UI on the API contract) are done,
> with the Phase 2/3/4 abstraction boundaries and safety primitives already in
> place. See [`docs/`](./docs) for the per-phase reports.

---

## Quick start (Phase 0 DoD)

```bash
cp .env.example .env        # fill in ANTHROPIC_API_KEY later (Phase 4)
docker compose up           # boots Postgres + api + web in one command
```

- Web UI  → http://localhost:3000
- API docs → http://localhost:8000/docs
- Health   → http://localhost:8000/health

That single `docker compose up` **is** the reproducible environment — the seed
of the future product (an "environment you can copy in one command").

### Running without Docker (dev)

```bash
# API
cd apps/api && pip install -r requirements.txt
uvicorn app.main:app --reload            # http://localhost:8000

# Web (separate shell)
cd apps/web && npm install && npm run dev # http://localhost:3000
```

The UI renders fully on embedded fake data even if the API is down, and
hydrates from the API the moment it is reachable.

---

## What's inside

```
ai-os/
├── docker-compose.yml         # Postgres + api + web, one command
├── .env.example               # config template (secrets live only in .env)
├── apps/
│   ├── web/                    # Next.js + TS — the Phase 1 UI (design mock, wired)
│   │   ├── app/                # app router (layout, page)
│   │   ├── components/AiOsApp.tsx   # the 3-pane control plane
│   │   └── lib/api.ts          # typed client + live execution stream (Phase 2 seam)
│   └── api/                    # FastAPI + Pydantic
│       └── app/
│           ├── main.py         # entrypoint; boots without DB/Docker/LLM
│           ├── schemas.py      # the API contract (mirrors the UI's data shapes)
│           ├── seed.py         # Phase 1 fake data == the contract
│           ├── execution_manager.py  # Phase 2 orchestrator
│           ├── routers/        # catalog, execution, approvals, tools
│           └── core/
│               ├── sandbox/    # SandboxRuntime interface + Docker & local impls
│               ├── tools/      # Tool interface + registry + ShellTool
│               ├── llm/        # LLMProvider adapter (Anthropic)
│               ├── policy/     # dangerous-command block + risk classification
│               ├── secrets/    # secret store + masking
│               └── audit/      # append-only audit log
└── docs/                       # per-phase reports (Implementation/Tests/…)
```

## The two things we never cut (roadmap §2)

**(1) The abstraction boundaries** — defined from the start so
`Docker→Firecracker`, `single→multi LLM`, `personal→multi-tenant` are swaps, not
rewrites:

| Boundary | Interface | MVP implementation |
|---|---|---|
| Sandbox | `core/sandbox/base.py :: SandboxRuntime` | Docker (real) + local (dev-only) |
| Tool | `core/tools/base.py :: Tool` | `ShellTool` |
| LLM | `core/llm/base.py :: LLMProvider` | Anthropic adapter |

**(2) The safety primitives** — never dropped, even in self-use scope:

- **Sandbox isolation** — non-root, no `docker.sock`, no host mount, resource caps
- **Secret non-exposure** — values masked out of LLM prompts, logs, and stdout
- **Audit log** — append-only record of every consequential event
- **Destructive-op gate** — `rm -rf`, `mkfs`, prod writes … blocked or paused for approval

## Security model (enforced today)

- Network **Default Deny + Allowlist** on every sandbox
- Resource ceilings: CPU 2c · RAM 4G · PID 128 · disk · 10-min timeout
- Dangerous commands (`rm -rf /`, `dd`, `mkfs`, `curl|bash`, fork-bombs, shutdown) refused outright
- L3/L4 actions (prod writes, `git push`, deploys) pause for an explicit human approval
- Secrets ≥6 chars registered in the store are redacted from anything leaving the process

## Tests

```bash
cd apps/api && pytest        # unit + security tests (policy, secrets, API contract)
```

## Cost

Infra is local `docker-compose` → **free**. The only metered cost is the LLM
(Phase 4+), bounded per task by `LLM_TOKEN_BUDGET`.

## Roadmap

| Phase | Scope | State |
|---|---|---|
| 0 | Reproducible foundation (`docker compose up`) | ✅ done |
| 1 | Mock UI on the API contract | ✅ done |
| 2 | Real sandbox execution + live logs | 🟡 interface + local runtime done; Docker wiring + WS live |
| 3 | Policy + Secret + Audit gate | 🟡 primitives done; UI-driven approval queue next |
| 4 | LLM in the PLAN→EXECUTE→OBSERVE loop | 🟡 provider adapter + tool registry ready |
| 5 | Git loop (diff → approve → commit) | ⬜ next |

See [`docs/phase-0.md`](./docs/phase-0.md) and [`docs/phase-1.md`](./docs/phase-1.md).
