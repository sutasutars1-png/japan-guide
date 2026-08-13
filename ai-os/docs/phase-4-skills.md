# Phase 4 · Stage 3a — Skill Library (role-tagged, wired into the loop)

*Report format per roadmap §2.2 / §48. Implements the base-skill layer of the
Phase 4 design's Skill/Agent/Flow model.*

## Implementation
- `app/skills.py` — a curated, **role-tagged skill database** (`SKILLS`) plus the
  base-skill mapping per agent role (`AGENT_BASE_SKILLS`) and helpers:
  `list_skills(role)`, `get_skill(id)`, and `compose_system(agent_name)` which
  builds an agent's system prompt from its role text + its base skills' content.
  Kept as a serializable list so it exports with the environment template; a
  JSON-store / editor drops in behind the same accessors later.
- 10 starter skills across the 5 roles (Planner/Researcher/Builder/Reviewer/
  Executor), e.g. ゴール分解, まず観察, 出典は非信頼データ, データ形の確認,
  小さく実行して検証, 完了前にテスト, 読み取り専用レビュー, 失敗の切り分け,
  承認前提の実行, 安全と簡潔報告.
- Agents carry base skills: `seed.AGENTS` gains a `skills` field; the `Agent`
  schema gains `skills`; a `Skill` schema is added.
- `routers/skills.py` — `GET /skills` (optionally `?role=`), `GET /skills/roles`,
  `GET /skills/{id}`.
- **Wired into the loop:** the agent router composes the system prompt from the
  agent's role + skills (`compose_system`) when the caller doesn't pass one, so a
  goal run as "Builder" actually behaves per Builder's skills.
- UI: the Agents view shows each agent's Skills as chips (with descriptions) and
  lets you add role-appropriate skills from the library (same pattern as
  capabilities). Editing applies to the session immediately.

## Tests
- `pytest` green (46 tests). New `test_skills.py`: unique ids; valid roles; every
  agent base skill exists; seed agents match the base map; list/filter/get(+404)
  endpoints; `/agents` includes skills; `compose_system` includes role text + a
  skill's name + its content; unknown agent → None.
- `next build` compiles and type-checks.
- Verified the composed Builder prompt (role + 6 role-appropriate skills).

## Security Tests
- Skills are guidance only; they never widen capabilities. Permissions stay in
  the Default-Deny capability layer (Phase 3), unchanged.

## Known Issues
- Base-skill layer only. Multiple presets + "reset to preset", per-run/-project
  overlays, and a full skills-library editor are later slices (see design doc).
- The library lives in a Python module for now; moving it to a JSON store / DB
  (editable + exportable) is a follow-up behind the same accessors.

## Next Phase
- Presets (multiple, resettable) + overlay skills (project/run scope), then
  multi-agent flows with the handoff protocol, then the manual-paste provider.

## Notes for the user
- Skills are **data** — edit `app/skills.py` (or later, the editor) freely; the
  agent loop picks up the changes on the next run.
