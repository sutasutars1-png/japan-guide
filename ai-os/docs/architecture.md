# Architecture — AI-OS Execution Plane

## Flow of one task

```
UI (Next.js)
  │  POST /execution/run  {command, actor}      (or WS /execution/stream)
  ▼
Execution Manager  (apps/api/app/execution_manager.py)
  │  1. Policy gate   → block dangerous / classify risk / halt L3+ for approval
  │  2. Secret mask   → nothing secret leaves the process
  │  3. Sandbox       → create → execute (live chunks) → destroy
  │  4. Audit         → append every step, redacted
  ▼
SandboxRuntime  (Docker: non-root, net-deny, resource-capped, single-use)
```

## The three boundaries (never removed — roadmap §2.1)

### 1. SandboxRuntime — `core/sandbox/base.py`
`create / execute / upload / download / destroy`. Swappable isolation.
- `DockerSandboxRuntime` — the real thing: uid 10001, `cap_drop ALL`,
  `no-new-privileges`, `network_mode=none` by default, mem/cpu/pids/tmpfs caps,
  **no** docker.sock or host mount.
- `LocalSubprocessRuntime` — DEV ONLY, refuses to run without
  `AIOS_ALLOW_UNSAFE_LOCAL=1`; applies rlimits + timeout in a scratch dir.
- Future: `gVisorRuntime`, `FirecrackerRuntime` drop in with no caller changes.

### 2. Tool — `core/tools/base.py`
`name / description / input_schema / capability / risk / execute`. Default Deny:
a tool only runs for an agent granted its capability. `ToolRegistry` exposes
specs to the LLM. First tool: `ShellTool`.

### 3. LLMProvider — `core/llm/base.py`
A provider-neutral `complete(messages, model, tools, max_tokens)` adapter.
`AnthropicProvider` is the MVP; adding another provider is a new adapter, not a
rewrite. All prompts pass through secret masking first.

## Safety primitives (never dropped)

| Primitive | Module | Guarantee |
|---|---|---|
| Sandbox isolation | `core/sandbox` | non-root, no host access, resource caps |
| Command policy | `core/policy` | block catastrophic cmds; classify L0–L4 |
| Approval gate | `routers/approvals` + manager | L3/L4 pause for a human |
| Secret masking | `core/secrets` | values never reach LLM/log/stdout |
| Audit log | `core/audit` | append-only, redacted, every event |

## Boot resilience
The API boots with no Postgres, no Docker daemon, and no LLM key: DB init is
best-effort, and the Docker/Anthropic SDKs are imported lazily only when a
sandbox is created or a completion is requested. This keeps the Phase 1 UI
reachable at all times.
