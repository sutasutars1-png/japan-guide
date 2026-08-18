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

## Status & how to resume (fresh session: start here)

**Where we are:** Roadmap phases 0–4 are implemented and merged to `main`. Phase 4
delivered, in order: Gemini adapter → agent loop (PLAN→EXECUTE→OBSERVE) → layered
skill DB → presets/overlays → multi-agent flows → Connections (keys + live model
discovery) → manual bridge → **Claude Code CLI provider (#5)** → **orchestrator**
(goal→plan→dispatch) → report chaining + re-plan + editable plan review, then UI
polish, Docker/host run modes, a string of Windows/boot-crash fixes, agent-config
persistence, and a Claude-CLI login UI. Merged via PRs #13–#33. **83 pytest green;
`next build` type-checks.**

**Verified working end-to-end (user-confirmed):** UI goal → **Claude orchestrator**
(`claude-cli`, subscription login, no API charge) → **Gemini workers**, in **Mode B**
(host api). Also Mode A (all-Docker) with Gemini. The whole "type a goal in the 🧭
command bar → 統括 → workers" loop runs. Seed defaults are now Planner=`claude-cli`,
workers=`gemini-2.5-flash` (so it works out of the box; no paid API is touched).
Claude CLI login is a **one-time** subscription login (`claude auth login`), managed
from the Connections → Claude Code card; it persists across restarts.

**Dev workflow (do this every stage):**
- Develop on branch **`claude/ai-execution-platform-o2qef8`**.
- Stage = commit → open PR → merge to `main`. **After each merge, restart the
  branch from `main` before the next stage** (the merged PR is done, don't stack
  on it):
  `git fetch origin main && git checkout -B claude/ai-execution-platform-o2qef8 origin/main`
- Each phase ends with a `docs/phase-*.md` report (Implementation / Tests /
  Security Tests / Known Issues / Next).
- Never put a specific Claude model identifier (the exact `claude-<family>-<ver>`
  string) in commits/PRs/code/artifacts. Use `claude-cli` (subscription CLI) or a
  generic label instead.

**Persistence:** agent config, deliverables, **connections' model lists, custom
presets, and custom flows** all persist to git-ignored `.aios-*.json` files next
to `.env` (shared helper `json_store.py`); **API keys persist** in `.env`. Seed
presets/flows are read-only defaults; only `custom.`/`flow.custom.` entries are
editable. Still in-memory: the skills DB itself (seed). A shared multi-user DB is
a later slice.

**Environment note:** this repo's dev environment is itself Claude Code with the
`claude` binary on PATH — which is exactly what the #5 CLI provider shells out to.
Premise for #5: run the backend on a machine logged into Claude Code (personal,
single-user).

**Two run modes (`docs/run-modes.md`):** the web UI is identical in both — you
always type the goal into the 🧭 command bar at localhost:3000. What differs is
where `api` runs. **Mode A** (`START-AI-OS.bat`, all-Docker): simplest, Gemini
workers work, but `claude-cli` is "未検出" (no `claude` in the container). **Mode B**
(`START-AI-OS-CLAUDE.bat`, db+web in Docker + **api on the host** via uvicorn):
the api shells out to your own logged-in `claude` → automatic Claude orchestrator,
subscription, no token injection. Set Planner's Model to `claude-cli`. Mounting
`~/.claude` into a container is the rejected token-injection path — never do it.

**Operational gotchas (each cost a debugging round — don't repeat):**
- **Test against pinned deps.** `pip install -r requirements.txt` before pytest.
  Example that only bit in Docker: FastAPI 0.115 asserts a `status_code=204` route
  has no response body; a `-> None`/response-model 204 route crashes at import.
  Return `Response(status_code=204)` and don't annotate a body.
- **`__file__`-relative paths must survive the container layout.** In the image the
  app is at `/srv/app` (3 parents), not `…/ai-os/apps/api/app` (4). `parents[3]`
  → IndexError. See `env_file._default_env()` for the guard.
- **Always pass `encoding="utf-8"` to file reads/writes.** Windows defaults to
  cp932; a UTF-8 `.env` (Japanese comments) crashed the host api with
  `UnicodeDecodeError`. Reads use `errors="replace"` so a stray byte can't crash boot.
- **Docker images are baked (`COPY app`).** `docker compose up` without `--build`
  runs stale code. The api source is now bind-mounted + `--reload` so a `git pull`
  → `docker compose restart api` suffices; **web still needs `--build`.**
- **`.bat` echoes:** cmd + `chcp 65001` mis-parses fullwidth `（） 「」` and colons —
  keep launcher echoes to plain text.
- **The api loads `.env` at boot** (`main.py` → `load_env_file()`), so keys saved
  via the UI survive a restart in host mode (Docker injects env itself).
- **Windows subprocess:** `asyncio.create_subprocess_exec` raises
  `NotImplementedError` on Windows uvicorn loops — run external CLIs via
  `subprocess.run` inside `asyncio.to_thread` (see `claude_cli_provider`). Also, the
  `claude` shim may be `claude.cmd` (exec it via `%COMSPEC% /c`, see `_exec_argv`)
  or `claude.EXE` (direct). Surface the CLI's stderr **or** stdout on failure so the
  real reason (e.g. "Not logged in · run /login") reaches the UI.
- **Seed agent models decide routing + billing.** A `claude-*` API model id routes
  to the metered `anthropic` provider (needs a key). Use `claude-cli` for the
  keyless subscription orchestrator; keep paid model ids out of the seed.

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
# API — install the PINNED deps before pytest; version drift can hide errors that
# crash the Docker image (e.g. FastAPI 0.115 asserts a 204 route has no body,
# newer versions don't). Always test against requirements.txt versions.
cd apps/api && pip install -r requirements.txt && pytest
uvicorn app.main:app --reload

# Web
cd apps/web && npm install && npm run build   # build also type-checks
npm run dev

# Full stack
docker compose up

# Applying updates after `git pull`:
#  - api: source is bind-mounted + uvicorn --reload → just `docker compose restart api`
#    (or it auto-reloads). No rebuild needed for Python code changes.
#  - web: production build baked into the image → needs a rebuild:
#    `docker compose up --build web`  (or `--build` for the whole stack)
#  - if requirements.txt / package.json changed: `docker compose up --build`.
```

**Stale-image trap:** `docker compose up` (no `--build`) reuses cached images. If
a code change doesn't appear or the container crashes with an error from a line
you already fixed, you're running an old image — rebuild with `--build`.

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
  connection; config via `AIOS_CLAUDE_CLI*`. **Billing safety:** spawns `claude`
  with `ANTHROPIC_API_KEY`/`_AUTH_TOKEN` stripped from its env (default), so it
  uses the **subscription login**, never metered API — not logged in ⇒ clean
  failure, never a surprise charge (`AIOS_CLAUDE_CLI_FORCE_SUBSCRIPTION=0` to opt
  out). Which Claude tier bills: **manual `claude-web`** = your browser subscription
  (free); **`claude-cli` (#5)** = subscription (free); **`anthropic` API models**
  = metered, and only if the user sets an Anthropic key AND assigns an agent a
  `claude-*` API model.
- **Orchestrator (`/orchestrate`):** `app/orchestrator.py` — goal → composed
  orchestrator prompt → **single-shot** provider call → `parse_plan` → auto-dispatch
  each `<agent>: <task>` step to the worker's loop. Orchestrator defaults to
  **Planner**; its model decides its tier (set it to `claude-cli` for keyless
  auto-Claude). UI: 「🧭 統括AIに任せる」 command-bar mode (the default). End-to-end
  "goal → 統括 → workers" path. Now also:
  - **Report chaining:** each worker's DONE report feeds the next step's context.
  - **Re-plan loop:** a worker that produces no result triggers a bounded re-plan
    (`max_replans`); an L3/L4 halt still stops (human decision, never re-planned).
  - **Plan-first UI:** `POST /orchestrate/plan` + `run(steps=…)` / WS `steps` field;
    a 「計画を確認してから実行」 toggle shows an editable `PlanReview` checklist.
- **Agent config persistence:** `agents_store` ↔ `.aios-agents.json` (per-agent
  model/skills/preset survive restart). Delete agent = `DELETE /agents/{id}` + UI
  button; the AgentDetail 「変更を保存」 button is wired.
- **Claude CLI login UI:** Connections → Claude Code card shows login status
  (`claude auth status`) + ログイン/ログアウト/再確認 (`GET/POST
  /connections/claude-cli/auth|login|logout`); login opens a console on Windows.
- **UI honesty:** ⚠サンプル badges mark still-mock sections (Projects, Task header,
  AI-decisions, Instruments/Risk meters, Data); skills render from an embedded seed
  (`lib/seed.ts`) so they show without the backend; a SetupBanner / BackendDownBanner
  guide when no key / no backend.

### Next (not yet built — candidate slices)
- Surface iteration/worker/re-plan budgets in the UI.
- Optional `→NEXT:`-style conditional routing inside a single plan.
- Wire the remaining sample panels (Projects/Data) to real data.
- Bundle custom presets/flows into the environment Template export; `web.search`.

**Done since (WRITE action — heredoc trap fix):** the loop runs one command per
turn and `parse_agent_action` took only the RUN line, so an agent's `cat > f <<EOF`
heredoc lost its body and wrote an EMPTY file (then burned its budget debugging).
Added a first-class `WRITE: <path>` action (content on the following lines,
multi-line) → `ExecutionManager.write_file` (deterministic base64 upload, no shell
quoting). `LOOP_PROTOCOL` now mandates WRITE for files and forbids heredocs.

**Done since (inter-step file handoff):** each worker runs in its OWN fresh
sandbox, so a later step (e.g. Reviewer) couldn't see files an earlier step
(Builder) wrote — it would wander the filesystem looking for them. Now the
orchestrator hands every file produced so far to the next worker under `inputs/`
(`open_session(seed_files=…)` → `_upload_files`, excluded from re-collection like
`materials/`). `SANDBOX_NOTES` tells agents to read `inputs/`, not to scan system
dirs, and to report-and-stop if expected files are absent.

**Done since (sandbox-aware prompts):** workers and the orchestrator are now told
the sandbox truth up front — no network (`pip`/`apt`/downloads fail; stdlib only),
**write the core text deliverable first**, and **make images as SVG** (plain text,
no PIL/matplotlib). `SANDBOX_NOTES` (system-owned, appended in `agent_loop`) +
`ENV_CONSTRAINTS` (in the orchestration/replan prompts). This stops agents burning
their whole iteration budget on impossible setup and finishing empty-handed.

**Done since (deliverable ZIP):** a deliverable downloads as a ZIP
(`export_zip` → `deliverable.md` + `artifacts/…`) and any single artifact
downloads on its own (`export_artifact`; `GET /deliverables/{id}/download?format=zip`,
`GET /deliverables/{id}/artifacts/{i}/download`). UI: ZIP + per-artifact ⤓ buttons.
See `docs/phase-4-deliverable-zip.md`.

**Done since:** Deliverable save/download flow — an orchestrate run auto-saves its
成果物; a Deliverables view lists/previews them and downloads as md/txt/json
(`app/deliverables.py`, `routers/deliverables.py`, `DeliverablesView` +
`SaveDeliverableBar`). See `docs/phase-4-deliverables.md`.

**Done since (sandbox session):** an agent loop now runs in ONE sandbox for its
whole life (files persist across steps) and its generated files are collected as
deliverables (`file` log lines → artifacts); the network allowlist is wired
(`Agent.allow_domains`, human-set, UI-editable) and materials can be **copied in**
(not mounted) from `AIOS_WORKSPACE_MOUNT`. Fixed the bug where a non-zero shell
exit discarded a valid worker report. `open_session/exec_in/collect_files/
close_session` in `execution_manager.py`; `app/materials.py`;
`GET /execution/sandbox-info`. See `docs/phase-4-sandbox-session.md`.

**Done since (web.fetch):** research is done by the **backend**, not the code
sandbox — a `FETCH: <url>` loop action calls a host-side, SSRF-guarded
`core/tools/web_fetch.py:safe_fetch` (public-IP-only, redirect-revalidated,
GET/size/timeout-capped, returns UNTRUSTED text), gated by the `web.fetch`
capability. So the code sandbox stays Default-Deny and any research domain works
with no allowlist. `AIOS_WEB_FETCH*` config. See `docs/phase-4-web-fetch.md`.
**Design rule:** never make the code sandbox the web fetcher; brain(host)/hands
(sandbox) separation extends to network — intake goes through web.fetch, the
sandbox keeps no egress.

### Docs map (`docs/`)
phase-0..3, phase-4-design, -skill-layers, -gemini-adapter, -agent-loop, -skills,
-skills-layered, -presets, -flows, -connections, -claude-cli, -orchestrate,
**run-modes** (Docker vs host api).

### Launchers (repo root of `ai-os/`)
- `START-AI-OS.bat` — Mode A, all-Docker (Gemini). `docker compose up --build`.
- `START-AI-OS-CLAUDE.bat` — Mode B, db+web in Docker + **api on host** (for the
  keyless `claude-cli` orchestrator; needs Docker + logged-in `claude` + Python).
- `STOP-AI-OS.bat` — `docker compose down` (host api stops when its window closes).

---

## File map (where things live)

**Backend `apps/api/app/`**
- `main.py` — FastAPI app; includes all routers; boot hooks (`init_db`, model
  discovery `connections.bootstrap()`).
- `config.py` — `Settings` from env (sandbox, llm defaults, `AIOS_CLAUDE_CLI*`).
- `schemas.py` / `seed.py` — data shapes; seed agents (Planner/Researcher/Builder/
  Reviewer/Executor) + layered skills.
- `agents_store.py` — **live** agent config; single source of truth the loop reads.
- `execution_manager.py` — sandbox run orchestration; `LogLine` type.
- `agent_loop.py` — one agent's PLAN→EXECUTE→OBSERVE; resolves each agent's
  **model + provider** at run time (`_agent_model` → `get_provider_for_model`).
- `flow.py` — fixed multi-agent pipelines + `→NEXT:` handoff parser.
- `orchestrator.py` — goal → `compose_orchestration_prompt` → single-shot plan →
  `parse_plan` → dispatch; `_with_context` (report chaining); `compose_replan_prompt`
  (re-plan); `make_plan()` (plan-first).
- `connections.py` — provider catalog, key set/clear, **live model discovery**,
  `provider_id_for_model`, `all_models`, `bootstrap`.
- `env_file.py` — upsert keys into git-ignored `.env` (chmod 0600).
- `manual_bridge.py` — human-paste bridge store (pending prompts + futures).
- `skills.py` / `presets.py` — layered skill DB (thinking×domain×execution×overlay)
  + presets; `compose_system(agent, skill_ids)`.
- `core/llm/` — `base.py` (LLMProvider), `__init__.py` (factory +
  `get_provider_for_model`), providers: `gemini_provider`, `anthropic_provider`,
  `openai_provider`, `manual_provider`, `claude_cli_provider`.
- `core/sandbox/` — `SandboxRuntime` (docker default, local dev-only),
  `core/policy/` (dangerous-command block + L0–L4), `core/secrets/` (store + mask),
  `core/audit` (append-only log).
- `routers/` — `agent`, `approvals`, `catalog`, `connections`, `execution`,
  `flow`, `llm`, `orchestrate`, `skills`, `tools`.

**Frontend `apps/web/`**
- `components/AiOsApp.tsx` (`@ts-nocheck`, the whole UI). Key components: `App`
  (state + run handlers), `ExecView`, `CommandBar` (modes: 🧭 orchestrate / ✨ goal
  / 🔀 flow / › cmd; orchestrate has a 「計画を確認」 toggle), `PlanReview`,
  `ManualBridgePanel`, `AgentsView`/`AgentDetail` (skills/preset/model editors),
  `ConnectionsView`/`ConnectionCard`, `FlowView`.
- `lib/api.ts` — typed client: `streamOrchestrate` (+ `fetchPlan`), `streamFlow`,
  `streamAgent`, `streamExecution`, connections + models + manual-bridge helpers.

## Endpoint reference
- Agents/loop: `WS /agent/stream`, `POST /agent/run` (accepts `overlays`).
- Flows: `GET /flows`, `POST /flow/run`, `WS /flow/stream`.
- **Orchestrate:** `POST /orchestrate/plan` (plan only), `POST /orchestrate`,
  `WS /orchestrate/stream` (both accept optional pre-approved `steps`).
- **Deliverables:** `GET /deliverables`, `GET /deliverables/{id}`,
  `POST /deliverables` (artifacts or captured `lines`),
  `GET /deliverables/{id}/download?format=md|txt|json`, `DELETE /deliverables/{id}`.
- Connections: `GET /connections`, `PUT /connections/{id}/key`,
  `POST /connections/{id}/refresh`, `DELETE /connections/{id}/key`,
  `POST`/`DELETE /connections/{id}/models` (manual, persisted), `GET /models`.
- Presets CRUD (custom only): `POST /presets`, `PUT/DELETE /presets/{id}`.
- Flows CRUD (custom only): `POST /flows`, `PUT/DELETE /flows/{id}`.
- Manual bridge: `GET /manual/pending`, `POST /manual/submit`.
- Skills/presets/catalog: `GET /skills`, `GET /presets`, `GET/POST/PUT /agents`,
  `POST /agents/{id}/apply-preset|reset-preset`.
- Execution/safety: `WS /execution/stream`, `GET /execution/audit`,
  `GET /execution/sandbox-info` (session config), approvals.
- Sandbox session env: `AIOS_PERSISTENT_SANDBOX` (1), `AIOS_COLLECT_FILES` (1),
  `AIOS_WORKSPACE_MOUNT` (materials copy-in dir), `AIOS_DEFAULT_ALLOW_DOMAINS`,
  `AIOS_DELIVERABLE_MAX_FILES`/`_MAX_BYTES`, `AIOS_MATERIALS_MAX_FILES`/`_MAX_BYTES`.
- web.fetch env: `AIOS_WEB_FETCH` (1), `AIOS_WEB_FETCH_MAX_BYTES`,
  `AIOS_WEB_FETCH_TIMEOUT`, `AIOS_WEB_FETCH_MAX_REDIRECTS`. Loop action `FETCH: <url>`.

## Quickstart: the orchestrator flow
1. `cd ai-os && cp .env.example .env` — set `GEMINI_API_KEY` (free) for workers.
2. To use the **keyless Claude orchestrator**, run the backend on a machine logged
   into Claude Code (`claude` on PATH). Otherwise pick an API/manual orchestrator.
3. `docker compose up` (or run `apps/api` + `apps/web` separately).
4. **Agents** view: set **Planner** (orchestrator) `model` = `claude-cli` (auto,
   keyless) / `claude-web` (one paste) / `gemini-*` (API). Set workers
   (Builder/Researcher/Reviewer) to `gemini-*` for free automatic execution.
   Models come from Connections (live discovery); set keys there.
5. **Execution** view → 🧭「統括AIに任せる」 → type a goal. Optional: tick
   「計画を確認してから実行」 to edit the plan (`PlanReview`) before dispatch. A
   `claude-web` orchestrator surfaces one prompt in the 🔗 manual-bridge panel.

## Locked decisions (don't relitigate without the user)
- **Gemini free** = default provider; Anthropic/OpenAI are paid.
- **Skill DB** is layered (thinking × domain × execution × overlay); usage is
  **manual selection** (option B) — flows pair naturally with manual selection.
- **Prompt composition** = human-readable Japanese sections. `RUN:`/`DONE:` and
  the flow `→NEXT:` handoff are **system-owned**, appended last, and authoritative
  over user skills (skills never widen capabilities — Default Deny is separate).
- **Bridges:** API / CLI(#5) / manual only. Never build browser-automation or
  token-injection bridges (ToS-grey). CLI(#5) is single-user personal use.
- **Orchestrator is single-shot** (one plan per goal) so a manual/CLI orchestrator
  costs at most one human touch; workers are the automatic bulk.
