# Phase 4 · Stage 1+2 — Layered Skill DB + Layered Composition

*Report format per roadmap §2.2 / §48. Implements the design in
`phase-4-skill-layers.md`. Supersedes the flat skill DB in `phase-4-skills.md`.*

## Implementation
- **Stage 1 — layered DB (`app/skills.py`):** each skill now has a `layer`
  (`thinking` | `domain` | `execution` | `overlay`). Seeded from the user's
  skill-database docs:
  - 5 thinking modes (`BASE-ANA/GEN/SYS/EVAL/DEC`)
  - 25 domain lenses (`DOM-SW … DOM-ESG`)
  - overlays (`OVR-METH-*`, `OVR-GOV-*`, `OVR-BIZ-*`, `OVR-FMT-*`, `OVR-OPT-*`)
  - execution skills (`exec.*`, our sandbox behaviours, migrated from the flat ids)
  - `list_skills(layer, role)` (role filter includes universal `roles:[]` skills),
    `get_skill`, `LAYERS`/`STAGES`.
  - `Skill` schema gains `layer`; `/skills` gains `?layer=` and `/skills/layers`.
- **Stage 2 — layered composition (`compose_system`):** builds the system prompt
  as readable Japanese sections in fixed order — 役割（工程）→ 思考モード →
  専門レンズ → 実行の手順 → 追加の方針. Thinking/domain fold the name into the
  header; execution/overlay list `## name` items. The RUN:/DONE: loop protocol is
  still appended by the loop (last, system-owned, authoritative).
- Default agents get a lean layered base (1 thinking × ~1 domain × execution ×
  light overlay); the full library is available for manual selection (design §5
  option B).
- UI: the Agents view shows/edits skills **grouped by layer**, selecting from the
  full library (manual selection).

## Tests
- `pytest` green (50 tests). New `test_skills.py`: unique ids; valid layers;
  valid stages; layer counts (5 thinking, 25 domains); base skills exist; seed
  agents match; `/skills?layer=` filter; role filter includes universal skills;
  `/skills/layers`; get+404; agents include layered skills; `compose_system` is
  layered + ordered (thinking before execution); overlay rendering; custom-ids
  composition; unknown agent → None.
- `next build` compiles and type-checks.
- Verified composed Builder/Reviewer prompts (role → thinking → domain →
  execution → overlay).

## Security Tests
- Skills are guidance only; capabilities (Default Deny) are untouched.
- The loop protocol stays separate and authoritative; overlays shape content,
  not the RUN:/DONE: envelope.

## Known Issues
- Manual selection only (design §5 option B). Dynamic/hybrid domain selection is
  a later option.
- Presets (multiple, resettable) + per-run/-project overlay scoping not yet
  built — the agent carries a single flat `skills` list (spanning layers) for now.
- Library lives in a Python module; a JSON store / editor is a later slice.

## Next
- Presets + overlay scoping (stage 3), then multi-agent flows with the handoff
  protocol, then the manual-paste provider.

## DoD
- ✅ スキルは層構造(思考×レンズ×実行×方針)。ゴール実行時に層ごとに合成される。
- ✅ 職種レンズ25を全収録。手動選択で付け外しできる(§5 = B)。
