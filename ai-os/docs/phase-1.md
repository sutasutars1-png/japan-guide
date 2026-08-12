# Phase 1 — Mock UI on the API Contract

*Report format per roadmap §2.2 / §48.*

## Implementation
- Ported the design mock into `apps/web/components/AiOsApp.tsx` as a Next.js
  client component: 3-pane control plane (Projects / Task·Chat·Execution /
  Status rail), Execution viewer with live log replay, log compress/clean modes,
  Agents editor (per-agent capabilities under Default Deny), Flow/orchestration,
  Data & storage, Connections, Guardrails, and the Export/Template view.
- The Approval modal is fully wired to the L0–L4 risk system.
- The API serves the same shapes the UI renders (`schemas.py` + `seed.py`):
  `/agents`, `/projects`, `/guardrails`, `/stores`, `/comments`,
  `/capabilities`, `/execution/demo`. The UI hydrates from these when the API is
  up and falls back to embedded fake data when it is down.
- `lib/api.ts` provides the typed client and a `streamExecution` websocket helper
  (the Phase 2 live-log seam).

## Tests
- `next build` compiles + type-checks (the ported mock is `@ts-nocheck` as it is
  untyped design code; the typed boundary is `lib/api.ts`).
- API contract smoke tests in `tests/test_api.py` assert the agent/capability/
  tool/approval shapes the UI depends on.

## Security Tests
- The Connections + Template views never render secret values (masked display
  only); the export template explicitly excludes secrets, project data, and logs.

## Known Issues
- The `CommandBar` "Send" is presentational; wiring it to `POST /execution/run`
  (or the websocket) is a Phase 2 task.
- Projects/guardrails/stores are still served from seed data (fake) by design.

## Next Phase
- Phase 2: replace the scripted execution log with real sandbox output over the
  websocket; wire the command bar to the Execution Manager.

## DoD
- ✅ The beautiful UI runs; clicking through shows fake jobs, logs, and the
  approval flow — and reads its data from the API contract when available.
