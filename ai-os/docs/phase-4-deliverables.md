# Phase 4 · Deliverables — 成果物のアウトプット & ダウンロード

Turns a run's output (成果物) from ephemeral streamed log lines into a **saved,
downloadable deliverable**. Closes the "Deliverable save/download flow" slice
listed under *Next* in `CLAUDE.md`.

## Implementation

**Backend**
- `app/deliverables.py` — the store. Persists to a git-ignored
  `.aios-deliverables.json` next to `.env` (same pattern as `agents_store`), so
  saved deliverables survive an API restart. Best-effort writes never break a
  request; the store is bounded to `MAX_DELIVERABLES` (newest kept).
  - `save(...)`, `list_deliverables()` (metadata only), `get(id)`, `remove(id)`,
    `clear()` (tests).
  - `artifacts_from_lines(lines)` — reconstructs per-step artifacts from streamed
    log lines by reading the orchestrator's `▶ 工程 N: <agent> — <task>` markers
    and the `[agent] …` output that follows. Lets the UI save agent/flow runs it
    captured client-side.
  - `render_markdown` / `render_text` / `export(item, fmt)` — on-demand rendering,
    so the download format (`md` | `txt` | `json`) is chosen at export time.
- `app/routers/deliverables.py`
  - `GET /deliverables` — list (metadata only).
  - `GET /deliverables/{id}` — full deliverable with artifact bodies.
  - `POST /deliverables` — save from explicit `artifacts` or fallback `lines`.
  - `GET /deliverables/{id}/download?format=md|txt|json` — file download with a
    proper `Content-Disposition` (RFC 5987 for the Japanese filename + an ASCII
    `dlv_….ext` fallback).
  - `DELETE /deliverables/{id}` — returns `204` (via `Response(status_code=204)`,
    per the FastAPI-0.115 gotcha in `CLAUDE.md`).
- `app/orchestrator.py` — **auto-save**. The runner accumulates each successful
  worker report as an artifact and persists a deliverable at every terminal path
  (completion, max-steps, halt, re-plan limit). Complete runs are `status:
  "complete"`, early exits `"partial"`. Nothing is saved when no worker produced
  output. Emits a `📦 成果物を保存しました · <id>` log line.
- `app/schemas.py` — `Artifact`, `DeliverableMeta`, `Deliverable` added to the
  contract. `main.py` registers the router.

**Frontend**
- `lib/api.ts` — `fetchDeliverables`, `fetchDeliverable`, `saveDeliverable`,
  `deleteDeliverable`, `deliverableDownloadUrl`, and `downloadDeliverable` (fetches
  the blob and triggers a browser download, honoring the server filename).
- `components/AiOsApp.tsx`
  - New **Deliverables** nav entry + `DeliverablesView`: lists saved deliverables,
    expands a row to preview its artifacts, and downloads as MD / TXT / JSON or
    deletes. Empty-state guides the user to run a goal.
  - `SaveDeliverableBar` in the Execution view: after any run finishes with
    output, offers "成果物として保存" (captures the client-side log) → then a direct
    Markdown download + link to the list. Orchestrate runs also auto-save server-side.

## Tests

`apps/api/tests/test_deliverables.py` (12 tests, all green; full suite **95
passed**, up from 83):
- store round-trip; empty-artifact pruning; `MAX_DELIVERABLES` bound.
- markdown/text/json export; unsupported format raises.
- `artifacts_from_lines` groups output by step and excludes trailer lines.
- endpoints: save → list → get → download (asserts `Content-Disposition:
  attachment`) → delete → 404; save-from-lines; empty save `400`; bad format `400`.
- orchestrator auto-saves on success and saves nothing when no output.

`cd apps/api && pip install -r requirements.txt && pytest` · `cd apps/web && npm
run build` (type-checks).

## Security Tests

- Deliverable content is worker output that already passed through the sandbox +
  policy layer; saving it adds no new command execution path.
- Save/download/delete are audited (`deliverable.save|download|delete` +
  `orchestrate.deliverable`) via `core.audit.log`.
- `.aios-deliverables.json` is git-ignored — deliverables are machine-local and
  never committed.
- The download filename is header-injection-safe: sanitized `_slug` stem, ASCII
  fallback, and RFC 5987 percent-encoding for the UTF-8 name.
- No secrets path touched; the store holds only already-emitted worker output.

## Known Issues

- Client-side `saveDeliverable(lines)` reconstruction relies on the orchestrator's
  `▶ 工程` / `[agent]` log shape; a run with an unusual log format saves fewer
  artifacts (the backend auto-save from orchestrate is the reliable path).
- The store is a flat JSON file (in-repo/local), not a shared DB — same tier as
  agents; a durable store is the broader *Next* slice.
- No pagination on `GET /deliverables` yet (bounded to `MAX_DELIVERABLES`).

## Next

- Durable/shared store for deliverables (with flows/presets/connections).
- Bundle a multi-file deliverable as a ZIP; per-artifact download.
- Wire the remaining ⚠サンプル panels (Projects/Data) to real data.
