# Phase 4 · Connections — keys, live model discovery, and the manual bridge

*Report format per roadmap §2.2. Makes the Connections view real: API keys are
stored safely, model versions are discovered live (no hard-coded strings), and
API-less assistants (Claude Code, Claude in the browser) become usable through a
human copy-paste bridge behind the same `LLMProvider` boundary.*

## What prompted this

Three requests:
1. The Connections buttons (Edit key, Add, …) were a static mock — nothing worked.
2. Model versions shouldn't be hard-coded strings; after a key is set, pull the
   **actually available** models from the provider so it survives new releases.
3. Claude / Claude Code / other added AIs don't use an API but should be usable
   via direct input / auto copy-paste — built safely with `.env` + masking.

## Implementation

### Keys — `.env` + Secret Store (safe by construction)
- **`app/env_file.py`** upserts `KEY=value` into the git-ignored `ai-os/.env`
  (chmod 0600) and the live process env. Keys survive a restart; they're never
  committed.
- Setting a key also registers it in the **Secret Store** (Phase 3), so from that
  instant every prompt/log/stdout is masked against it. The UI only ever sees a
  masked hint (`••••••••abcd`), never the value.

### Live model discovery (no hard-coded versions)
- **`app/connections.py`** holds the provider catalog and, after a key is set,
  calls each provider's list-models endpoint:
  - Gemini → `GET /v1beta/models` (keeps `generateContent`-capable ids)
  - Anthropic → `GET /v1/models`
  - OpenAI → `GET /v1/models` (chat families)
  Discovery errors are captured as status, never crash the app. `GET /models`
  serves the flat list that now populates every model picker in the UI (Agents,
  New agent) — falling back to constants only when the API is unreachable.

### Manual bridge (API-less AIs, actually usable)
- **`app/manual_bridge.py`** + **`app/core/llm/manual_provider.py`**: a
  `ManualBridgeProvider` implements the normal `complete()` interface, but instead
  of a network call it surfaces the (masked) prompt to a human and awaits the
  pasted reply. The agent loop, flows, presets — nothing upstream knows the
  transport is a person. This reuses the Phase 4 "human as the handoff" idea.
- Provider routing: `get_provider_for_model()` maps a model id → provider via the
  Connections registry, so an agent set to `claude-code` routes to the bridge and
  one set to `gemini-2.5-pro` routes to Gemini. `AgentLoop` now resolves each
  agent's model + provider at run time (was a single global model).
- **UI**: a 🔗 手動ブリッジ panel in the Execution view shows any waiting prompt
  with a **Copy** button and a reply box — paste into Claude/Claude Code, paste
  the answer back, and the run continues.

### Endpoints
`GET /connections`, `PUT /connections/{id}/key`, `POST /connections/{id}/refresh`,
`DELETE /connections/{id}/key`, `POST /connections/{id}/models` (manual),
`GET /models`, `GET /manual/pending`, `POST /manual/submit`.

## Tests
- `pytest` green (66). New `test_connections.py`: set-key persists + masks +
  discovers (discovery injected, no network); discovery error is captured not
  raised; manual providers are ready without a key and list models; add manual
  model; model→provider routing picks the manual bridge; `render_prompt` masks
  secrets; a full manual-bridge round-trip (prompt surfaced → human submits →
  completion resolves).
- `next build` compiles and type-checks with the live Connections UI.

## Security Tests
- Keys never leave the process in the clear: only a masked hint is serialized;
  `.env` is git-ignored and chmod 0600. The manual-bridge prompt is masked before
  it is ever surfaced (verified), so no secret is copied out to an external AI.
- Discovery and manual submission add no capability — Default Deny, sandbox
  isolation, and the approval gate are untouched.

## Known Issues
- Connection state (discovered models) is in-memory; it's re-discovered on boot
  from the stored key. Keys themselves persist in `.env`.
- The manual bridge is a single-process asyncio store (no durable queue yet); a
  forgotten prompt times out after 30 min so a run can't wedge forever.
- Per-provider usage/quota meters from the old mock were dropped (they were fake);
  real usage metering is a later slice.

## Next
- Optional: durable connection store; live usage metering; auto-launch of the
  Claude Code CLI as a semi-automated bridge (still no API, but less manual).
