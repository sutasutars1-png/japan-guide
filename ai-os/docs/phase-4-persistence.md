# Phase 4 · Persistence expansion — connections / presets / flows

Closes the "durable stores for flows/presets/connections" *Next* item. Until now
only agent config and API keys survived a restart; connections' model lists,
presets, and flows were in-memory (or fixed seed). This makes them durable and —
for presets/flows — editable.

## Implementation

- `app/json_store.py` — the shared load/save helper behind the local stores
  (`load_json`/`save_json` to a git-ignored file next to `.env`). Best-effort:
  a read error falls back to a default, a write error is logged and swallowed.
  Never stores secrets.
- **Connections** (`connections.py`) — the per-provider model lists now persist to
  `.aios-connections.json` (`_load_state`/`_persist_state`, saved on
  `refresh_models`, `add_manual_model`, `remove_manual_model`, `clear_key`). So a
  **manually-curated model** (e.g. for `claude-web`) survives a restart instead of
  resetting to defaults; api providers still re-discover on boot. New
  `remove_manual_model` + `DELETE /connections/{id}/models`.
- **Presets** (`presets.py`) — split into read-only `SEED_PRESETS` + a persisted
  custom layer (`.aios-presets.json`). `add_preset`/`update_preset`/`remove_preset`
  operate on custom presets only (id prefix `custom.`); seed presets can't be
  edited/deleted. Endpoints: `POST /presets`, `PUT /presets/{id}`,
  `DELETE /presets/{id}`.
- **Flows** (`flow.py`) — same shape: read-only `SEED_FLOWS` + persisted custom
  flows (`.aios-flows.json`, id prefix `flow.custom.`). `add_flow`/`update_flow`/
  `remove_flow`; endpoints `POST /flows`, `PUT /flows/{id}`, `DELETE /flows/{id}`.
  Custom flows are resolvable by the flow runner like seed flows.

### Frontend
- `lib/api.ts`: `removeManualModel`, `createPreset`/`deletePreset`/`isCustomPreset`,
  `createFlow`/`deleteFlow`/`isCustomFlow`, `fetchFlows`.
- **AgentDetail**: preset row gains 「現在の選択を保存」(create a custom preset from the
  agent's current skills) and 「削除」for the selected custom preset; custom presets
  are marked ★.
- **FlowView**: a 「保存済みフロー」panel lists real flows (seed/custom tags), saves the
  current drag order as a custom flow, and deletes custom flows. Saved flows are
  selectable in the Execution 🔀 flow picker.
- **ConnectionCard**: each manual model gets a ✕ to delete; a note says additions
  persist across restarts.

## Tests

`tests/test_persistence.py` (7). Full suite **130 passed** (was 123). Web builds.
- json_store round-trip + default fallback.
- manual model persists to the store and is removable (fn + `DELETE` endpoint).
- preset CRUD; seed presets reject edit/delete (400); custom preset survives a
  fresh load from disk.
- flow CRUD; seed flows reject edit/delete; empty-stations create rejected; custom
  flow survives reload and resolves via `get_flow`.

## Security / posture

- All three files are git-ignored (machine-local); they hold only non-sensitive
  config (model ids, skill ids, station lists) — never keys.
- Seed presets/flows are immutable, so the built-in safe defaults can't be
  clobbered; only user-created (`custom.` / `flow.custom.`) entries are mutable.

## Known Issues / Next

- Custom flows can reference an agent name that was later deleted; the runner skips
  unknown stations, but a UI validation pass would be friendlier.
- No import/export of the custom stores yet (the environment Template covers agents
  only); bundling presets/flows into the Template export is a later slice.
