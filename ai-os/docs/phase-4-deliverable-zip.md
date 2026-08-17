# Phase 4 · Deliverable ZIP bundle & per-artifact download

Extends the deliverables module so a multi-file 成果物 can be downloaded as one ZIP,
and any single artifact (a generated file or a report) can be downloaded on its own.

## Implementation

- `app/deliverables.py`
  - `artifact_filename(a, i)` — a file-artifact (task `ファイル: <path>`) keeps its
    original relative path; a text report becomes `NN-<agent>.md`.
  - `_safe_member` — strips `/` and `..` so a zip/download path can't traverse.
  - `export_zip(item)` → `(bytes, "application/zip", name)` — a ZIP containing the
    combined `deliverable.md` plus every artifact under `artifacts/…` (paths
    preserved, collisions de-duped).
  - `export_artifact(item, index, fmt)` → one artifact; `raw` infers the media type
    from the filename extension, `txt` coerces to plain text.
- `routers/deliverables.py`
  - `GET /deliverables/{id}/download?format=zip` — whole bundle as a ZIP.
  - `GET /deliverables/{id}/artifacts/{index}/download?format=raw|txt` — one artifact.
  - Shared `_attachment` helper (RFC 5987 filename + ASCII fallback) for all downloads.
- Frontend
  - `lib/api.ts`: `downloadDeliverable(id, "zip")` and `downloadArtifact(id, index)`
    (shared `downloadFrom` honors the server filename).
  - `DeliverablesView`: a **ZIP** button per deliverable, and a **⤓ DL** button on
    each artifact in the expanded preview.

## Tests

Additions to `tests/test_deliverables.py`. Full suite **133 passed** (was 130).
Web builds.
- ZIP contains `deliverable.md`, keeps a file-artifact's path (`artifacts/docs/out.md`),
  and names a report `artifacts/NN-<agent>.md`.
- `export_artifact` returns a file's basename + inferred type, a report as `.md`, and
  a `txt` coercion; out-of-range raises.
- Endpoints: `?format=zip` returns `application/zip`; the per-artifact endpoint
  returns the raw content and 404s on a bad index.

## Notes

- Artifacts are text today (the file collector skips binaries), so ZIP entries are
  UTF-8 text; the structure is ready for binary artifacts if collection later allows them.
- Path safety: zip member names and download filenames are sanitized against traversal.
