# Phase 3 — Safety Gate (Approval + Secret + Audit)

*Report format per roadmap §2.2 / §48.*

## Implementation
- **Approval modal, end to end.** A destructive/high-risk command (L3/L4) now
  halts the run and pops the UI's Approval modal with the real command. The
  human decides:
  - **Approve** → the exact command is re-run with `approved=true`, which skips
    the approval gate and executes it in the sandbox ("approved by you · running").
  - **Reject** → the command is not run; a "拒否しました" line is shown.
  The approval *request* is recorded to the audit log either way.
- **Destructive `rm -rf` routing.** `rm -rf /` (and `~`, `$HOME`) stays blocked
  outright — never runnable, even with approval. A recursive-force delete of a
  *non-root* path (`rm -rf ./build`, `rm -fr node_modules`, `rm -r -f dist`) is
  now classified L3 and routed to the approval modal, matching the roadmap DoD.
- **Audit log persisted to Postgres.** Every consequential event (command run,
  policy block, approval request/grant, sandbox create/destroy) is appended to
  the append-only `audit_logs` table via a startup-wired sink, with an in-memory
  mirror for the live UI feed. Secret values are masked before storage.
- **Audit feed in the UI.** The Guardrails view now shows a live, auto-refreshing
  list of recent audit events (kind · summary · risk · time).

## Tests
- `pytest` green (23 tests), including new cases: `rm -rf ./build` is allowed +
  requires approval; `rm -fr` / `rm -r -f` variants too; `rm -rf /` stays blocked.
- Approval flow verified via the Execution Manager on the local runtime: no
  approval → halt; `approved=True` → executes.
- `next build` compiles and type-checks.

## Security Tests
- Approval gate cannot be bypassed by `approved=true` for a *blocked* command —
  blocked commands never run regardless of approval.
- Secret masking still applies to audit summaries and metadata on the way into
  the store (`redacted()` before append).
- Audit table is append-only (no update/delete path in code).

## Known Issues
- Postgres persistence was exercised against the compose Postgres; in CI (no DB)
  the sink stays unset and the in-memory audit still works — verify persistence
  on a normal `docker compose up`.
- Reject is recorded client-side as a log line; the server already audits the
  approval *request*. Persisting the explicit reject decision is a small follow-up.

## Next Phase
- Phase 4: put an LLM in the PLAN → EXECUTE → OBSERVE loop (provider choice —
  Gemini free / manual paste / paid — to be decided first).

## DoD
- ✅ rm -rf(非rootパス)で承認モーダルが出る。承認で実行、拒否でブロック。
- ✅ Secret がログ・stdout・監査に出ない。全操作が Audit に残る。
