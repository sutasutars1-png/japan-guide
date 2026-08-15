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

---

## Architecture decisions (Phase 4 · the orchestrator design)

*This section records the design worked out with the user so it can be picked
back up. It is the "why", not just the "what".*

### The product concept
A user gives a **goal** to an **orchestrator AI (統括AI)**, which decomposes it
and dispatches tasks to **worker agents**. The intended split: the orchestrator is
**Claude** (premium reasoning), the workers are **cheap/free API models** (e.g.
Gemini free tier) doing the bulk work. So the expensive brain is used sparingly.

### The hard constraint (why the "bridge" exists)
A browser web UI is sandboxed and **cannot reach another site/app directly**
(it can't type into claude.ai or read its DOM). So access to any AI always flows:

```
UI  →  own backend  →  [bridge]  →  AI
```

The UI never "accesses" an AI; the **backend** or a **human** does. This is why an
API-less AI needs an explicit bridge.

### Provider tiers — every AI plugs in behind `LLMProvider` at its best tier
| Tier | Entry point | Example | Automatic? | Notes |
|---|---|---|---|---|
| **API** | HTTP + key | Gemini / OpenAI / Anthropic | ✅ | keys in `.env` + Secret Store, models discovered live |
| **CLI** | local subprocess | **Claude Code (`claude`)** | ✅ | backend runs the user's own logged-in binary — **#5, chosen** |
| **Manual** | human copy-paste | Claude in the browser | ⛔ (1 paste) | universal fallback; the human is the wire |

Rejected bridges (do **not** build): browser-extension/headless automation of
claude.ai, and **token injection** (extracting an OAuth token into a foreign
container) — both ToS-grey and fragile.

**Key distinction:** running the user's own installed, logged-in `claude` as
themselves (#5) is legitimate personal use. It is *not* token injection. This is
single-user/local only; fanning one login out to many users would be ToS-abusive.

### Brain vs hands (a safety invariant)
The channel that holds a credential (the LLM provider — e.g. the `claude` CLI)
runs on the **host/backend** and must **never** be the channel that executes
LLM-proposed arbitrary commands (the **task sandbox**, Default-Deny, no secrets).
Keeping "brain" and "hands" separate is why a prompt-injected sandbox agent can't
reach the Claude login. Never merge them (e.g. don't put the CLI+credential inside
the task sandbox).

### How "goal → orchestrator" actually works
The app wraps the raw goal into an **orchestration prompt** =
`[orchestrator role] + [available worker agents & capabilities] + [required output
format] + [the user goal]`, then calls the orchestrator's provider. Because of the
`LLMProvider` abstraction this is one code path:
- orchestrator = Gemini → HTTP, fully automatic;
- orchestrator = `claude-cli` → backend runs `claude -p`, fully automatic (#5);
- orchestrator = manual → surfaces for one human paste.
The app owns **composition + parsing + dispatch**; the human/CLI is only transport.
"手間を感じさせない" = make the manual touch **rare** (once per goal), not zero:
one orchestration → many automatic worker steps.

### Provider selection
`get_provider_for_model(model)` (in `core/llm/__init__.py`) maps a model id →
provider via the Connections registry. `AgentLoop` resolves each agent's model +
provider at run time (an agent's `model` field decides its tier). Set an agent's
model to `claude-cli` to make it the keyless Claude orchestrator; `claude-web` for
the manual bridge; `gemini-*` etc. for API workers.

### What is built (as of the Connections + #5 work)
- **Flows (3c):** ordered multi-agent pipelines with a system-owned `→NEXT:`
  handoff protocol (`app/flow.py`). Currently **fixed** station lists.
- **Connections:** provider catalog, `.env`-persisted keys (`env_file.py`) + Secret
  Store masking, **live model discovery** (`connections.py`), `GET /models` feeding
  the UI's model pickers.
- **Manual bridge:** `manual_bridge.py` + `core/llm/manual_provider.py` +
  `/manual/pending|submit`; UI panel in the Execution view (copy prompt / paste
  reply). For API-less AIs (Claude web).
- **Claude Code CLI provider (#5):** `core/llm/claude_cli_provider.py` — backend
  runs the user's `claude -p`; text-only (no `--dangerously-skip-permissions`),
  masked prompt, throwaway cwd, on the host (not the sandbox). `cli`-kind
  connection; config via `AIOS_CLAUDE_CLI*`.

### Next (not yet built)
- **`/orchestrate` entrypoint:** goal → composed orchestrator prompt → (provider) →
  **plan**; a plan parser; **auto-dispatch** to worker agents. With #5 the
  orchestrator step is fully automatic. The flow's stations then become
  **plan-driven** (authored by the orchestrator) rather than fixed.
- Recommended orchestrator output format: start with **(a) task bullet list**
  (`<agent>: <instruction>` lines, then `DONE`), extend to `→NEXT:` routing later.

### Docs map (`docs/`)
phase-0..3, phase-4-design, -skill-layers, -gemini-adapter, -agent-loop, -skills,
-skills-layered, -presets, -flows, **-connections**, **-claude-cli**.
