# Phase 4 · Stage 1 — Gemini API Adapter

*Report format per roadmap §2.2 / §48. Implements the first slice of the Phase 4
design (`phase-4-design.md`): a real LLM provider behind the `LLMProvider` boundary.*

## Implementation
- `core/llm/gemini_provider.py` — `GeminiProvider` implementing `LLMProvider`
  against the Gemini REST API (`generativelanguage.googleapis.com/v1beta`) over
  httpx. httpx is imported lazily, so the API still boots with no key/network.
  - Pure, testable helpers: `build_request_body` (splits system → `systemInstruction`,
    maps assistant → Gemini "model" role, masks every text) and `parse_response`
    (extracts text, `usageMetadata`, finish reason).
- Registered in the provider factory (`get_llm_provider("gemini")`), which is now
  the **default** provider.
- Config: `LLM_PROVIDER=gemini`, `LLM_MODEL=gemini-2.5-flash`, `GEMINI_API_KEY`
  wired through `.env.example` and docker-compose. `GEMINI_API_KEY` /
  `GOOGLE_API_KEY` auto-registered for secret masking.
- `routers/llm.py` — `GET /llm` (provider/model/key-present status) and
  `POST /llm/complete` (one-shot completion) so the user can verify a new key.

## Tests
- `pytest` green (30 tests). New `test_llm.py`: factory returns gemini; request
  body splits system/roles and masks secrets; response parsing (text/usage/stop);
  empty-response handling; `complete()` without a key raises.
- `GET /llm` status endpoint tested.
- Full `complete()` wiring verified against a mocked httpx client: correct URL,
  key as query param, system/contents shape, and parsed result.

## Security Tests
- Every message + system instruction is masked (`mask_secrets`) before leaving
  the process — a registered secret never reaches Gemini.
- The API key is sent only as the request's query param and is auto-registered
  for masking so it never appears in logs/stdout.

## Known Issues
- No live call was made in CI (no key/network). Verify against a real free key
  on a normal machine via `POST /llm/complete`.
- Tools / function-calling mapping is not implemented yet (deferred to the loop
  stage). `tools=` is accepted but ignored.
- Streaming is not wired (single-shot `generateContent`); fine for the loop's
  per-step calls.

## Next Phase
- Stage 2: the PLAN→EXECUTE→OBSERVE loop — call the provider, run the produced
  command through the sandbox (Phase 2), observe, iterate (bounded), with the
  handoff-protocol layer and approval gate (Phase 3).

## Prerequisite for the user
- Get a free Gemini API key at https://aistudio.google.com/app/apikey, put it in
  `.env` as `GEMINI_API_KEY=...`, restart, then `POST /llm/complete` to confirm.
