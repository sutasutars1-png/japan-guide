# Phase 4 · Persistent sandbox, network allowlist & materials

Follow-up to the deliverables slice, fixing the three issues found when a real
orchestrate run never reached a deliverable (see the diagnosis in that session):
files didn't survive between an agent's commands, research tasks had no network,
and agents had no source material. Plus the root-cause bug (a non-zero shell exit
discarded a valid report) fixed earlier.

## Implementation

### #2 · Persistent sandbox per agent loop + deliverable-file collection
Previously `ExecutionManager.run()` created **and destroyed a fresh sandbox for
every command**, so a file an agent wrote vanished before its next step. Now an
agent loop runs in **one** sandbox for its whole lifetime and its generated files
are collected as deliverables.
- `execution_manager.py` — new session API alongside the per-command `run()`:
  `open_session()` (create once + copy in materials), `exec_in()` (run a command
  in the existing sandbox, no create/destroy), `collect_files()` (read text files
  created under the workdir), `close_session()`. `collect_files` runs one trusted
  base64-piped python walker in-sandbox (portable across runtimes; sidesteps the
  local-vs-docker upload/download path-model difference), excludes `materials/`
  and dotdirs, and is bounded by `deliverable_max_files` / `_max_bytes`.
- `agent_loop.py` — opens a session at loop start (falls back to per-command if it
  can't), runs each command via `exec_in`, and at every normal exit (DONE, budget,
  max-iter) emits collected files as **`file` log lines** (`{path,size,content}`
  JSON). Closes the session in `finally`.
- `orchestrator.py` / `flow.py` — consume `file` lines: capture them as artifacts
  (orchestrator) and show a friendly `📄 生成ファイル: <path>` line instead of raw
  JSON. A step that produced **a report OR a file** now counts as success.
- `deliverables.artifacts_from_lines` — parses `file` lines too, so a client-saved
  agent/flow run keeps its generated files.

### #3 · Network allowlist actually wired
- `Agent.allow_domains` (schema) — per-agent allowlist, **human-set, never widened
  by the LLM**. Editable in the UI (AgentDetail). `settings.default_allow_domains`
  (`AIOS_DEFAULT_ALLOW_DOMAINS`) applies on top.
- `agent_loop._resolve_domains` merges explicit ∪ agent-config ∪ default, and the
  session sandbox is created with that allowlist.
- `docker_runtime` — when an allowlist is granted, the container attaches to the
  bridge network (egress on) instead of `none`. **Known limitation:** egress is
  currently coarse (bridge = all outbound), not per-domain filtered; the Execution
  Manager logs this plainly. A per-domain egress proxy is the follow-up.
- `agent` router accepts a run-scope `allow_domains`.

### #4 · Materials copy-in (source material for the sandbox)
- `materials.py` — filters a host directory (`AIOS_WORKSPACE_MOUNT`) to text-ish
  files within caps, **hard-excluding** secrets/VCS/deps (`.env`, `.git`,
  `node_modules`, `*.pem`, the app's own `.aios-*.json`, binaries, …).
- `open_session` **copies** them into `<workdir>/materials/` via the `upload` verb
  — a one-way copy, **never a live host mount**, preserving the isolation invariant
  ("no host filesystem mount into sandboxes"). Collected deliverables exclude
  `materials/` so source isn't re-emitted.
- `GET /execution/sandbox-info` surfaces the session config; the UI shows
  永続SBX / 成果物回収 / 資料マウント chips in the sandbox header.

## Tests

`tests/test_sandbox_session.py` (8) + additions to `test_deliverables.py` and
`test_orchestrate.py`. Full suite **105 passed** (was 96). Web `npm run build`
type-checks. Highlights:
- materials filtering (secrets/binaries/dirs excluded; caps respected);
- a file written across **two** commands survives and is collected (persistence);
- `materials/` is not re-collected as a deliverable;
- the agent loop emits a `file` line for a generated file;
- the orchestrator captures a `file` line as an artifact and swallows the raw JSON;
- allowlist merge/de-dupe; `sandbox-info` endpoint shape.

## Security Tests / posture

- Isolation invariant intact: materials are **copied in**, not mounted; host FS is
  never exposed to the sandbox.
- Secrets never enter the sandbox: `materials.py` hard-denies `.env`, keys, and the
  app's local state files, and skips binaries.
- The network allowlist is **human-controlled** (agent config / request / env) —
  an LLM can't grant itself egress. Coarse egress is logged as a warning and only
  applies when a human granted domains; empty allowlist = fully offline (default).
- All new side-effects are audited (`sandbox.create/materials/destroy`,
  `agent.files`, `command.run`).

## Known Issues / Next

- Docker egress allowlist is coarse (bridge = all outbound). Next: a per-domain
  egress proxy to enforce the list literally.
- `collect_files` gathers text files only (binaries skipped) and is size/count
  capped; a ZIP export of larger/binary artifacts is a later slice.
- Materials copy-in is a snapshot at session open (no live sync).
