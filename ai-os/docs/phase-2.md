# Phase 2 — Real Safe Execution, Wired to the UI

*Report format per roadmap §2.2 / §48.*

## Implementation
- The Execution view's command bar now **runs real commands**. Typing a command
  and pressing Enter (or Send) opens a WebSocket to `/execution/stream`, which
  drives the Execution Manager → SandboxRuntime and streams live log lines back
  into the Sandbox pane. The scripted demo still plays on first load; the first
  real command switches the pane to live output.
- `DockerSandboxRuntime.execute` now streams **incrementally**: a worker thread
  pumps the blocking `docker exec` output into an asyncio queue, so lines reach
  the UI as they are produced rather than all at once. The real process exit
  code is read via `exec_inspect`.
- Every run still flows through the full safety path: policy gate (block +
  L0–L4 classification) → secret masking → sandbox create/execute/destroy →
  append-only audit log.

## Tests
- `pytest` green (20 tests).
- WebSocket path verified end-to-end (`/execution/stream` with a command):
  sandbox created → real stdout streamed (`echo`, `python -c`) → exit 0 →
  stream closed.
- `next build` compiles and type-checks.

## Security Tests
- Dangerous commands are refused before any sandbox is created
  (`rm -rf /`, `mkfs`, `dd`, `curl|bash`, fork bomb, shutdown) — see
  `tests/test_policy.py`.
- L3/L4 commands (prod writes, `git push`, deploys) halt for approval instead
  of executing.
- Docker sandboxes run non-root, `cap_drop ALL`, `no-new-privileges`, network
  `none` by default, with CPU/RAM/PID/disk/timeout ceilings, and never mount the
  docker socket or host filesystem.

## Known Issues
- Live streaming was exercised via the dev-only local runtime in CI (no nested
  Docker daemon here). On a normal machine with Docker Desktop, the same path
  uses the Docker runtime for true isolation — verify there.
- The Status-rail instruments (CPU/RAM/tokens) are still cosmetic during a live
  run; wiring real container stats is a follow-up.
- Network is Default Deny, so commands needing the internet (e.g. `pip install`)
  won't reach it until a per-job allowlist bridge is added (Phase 2 follow-up).

## Next Phase
- Phase 3: surface the approval halt as the UI's Approval modal end-to-end, and
  persist the audit log to Postgres.

## DoD
- ✅ UIでコマンド入力 → Sandboxで実行 → 本物のログがリアルタイムで流れる。
