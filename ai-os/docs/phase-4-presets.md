# Phase 4 · Stage 3b — Presets (resettable) + run-scope overlays + live store

*Report format per roadmap §2.2 / §48. Implements the 主スキル(preset)/副スキル(overlay)
part of the design.*

## Implementation
- **Live agent store (`app/agents_store.py`)** — a single in-memory source of
  truth for agent config, seeded from `seed.AGENTS`. Both the catalog router (UI
  edits) and the agent loop read from it, so **what the user configures is what
  the loop runs**. The catalog router was refactored onto it.
- **Presets (`app/presets.py`)** — named base-skill bundles per stage. Each agent
  has a default preset equal to its base skills; extra presets (e.g. Builder
  「Web・汎用」 vs 「データ分析」) switch a whole skill-set at once. Serializable.
- **Endpoints:** `GET /presets` (`?stage=`), `POST /agents/{id}/apply-preset`
  (sets skills + active preset), `POST /agents/{id}/reset-preset` (restore the
  active preset's skills — undo edits).
- **Run-scope overlays (副スキル):** the agent run/stream accepts `overlays: [ids]`
  appended to the agent's current skills for that run only.
- **Loop composes from the store:** `compose_system` reads role text from the
  store (reflects edits) and is fed the agent's current skills + run overlays.
- **UI (Agents view):** a preset selector + 「プリセットに戻す」 button; skill /
  capability / model / role edits **persist to the backend** (PUT / apply / reset),
  so the loop reflects them immediately.

## Tests
- `pytest` green (55 tests). New `test_presets.py`: default presets equal base
  skills; list + stage filter; apply → skills+preset change and the store
  reflects it; reset restores; unknown preset 404; editing skills (PUT) persists
  to the store and `compose_system` picks it up (DOM-LEG appears).
- `next build` compiles and type-checks.

## Security Tests
- Presets/overlays are skills (guidance) only; capabilities (Default Deny)
  unchanged. Skill content is masked like all prompt text before leaving.

## Known Issues
- Overlays are run-scope (per goal-run) or persisted-as-edits; a distinct
  project-scoped overlay store is not separated out yet.
- Presets/store are in-memory (reset on API restart); a DB/JSON store is a later
  slice behind the same functions.

## Next
- Stage 3c: multi-agent flows with the handoff protocol (Planner→Builder→Reviewer
  auto-chaining).
