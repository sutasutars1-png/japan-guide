# Phase 4 · Host-side web.fetch (research without opening the sandbox)

Resolves the tension raised in review: a per-domain allowlist on the *code
sandbox* is impractical for open-ended research (sources are chosen by the LLM at
run time), but opening the sandbox's egress is dangerous (prompt-injection →
exfiltration, SSRF → cloud-metadata/lateral movement, malware download+exec,
third-party abuse). The fix separates the two channels: **fetching is done by the
backend, not the code sandbox**, so any domain works with no allowlist while the
sandbox stays Default-Deny.

## Implementation

- `core/tools/web_fetch.py`
  - `safe_fetch(url)` — GET from the host with an **SSRF guard**: http/https only;
    the target host must resolve to a **public** address (private, loopback,
    link-local incl. `169.254.169.254` metadata, multicast, reserved, unspecified
    are refused); redirects are followed **manually and each hop is re-validated**
    (redirect-to-internal is the classic bypass); GET-only, size/redirect/timeout
    capped; only textual content types are returned; HTML is tag-stripped; the body
    is returned marked UNTRUSTED. Honors env proxies. Accepts an injected `opener`
    for testing.
  - `WebFetchTool` — the registry Tool (`capability="web.fetch"`, risk LOW) wrapping
    `safe_fetch`; gated by the agent's capability grant.
- `agent_loop.py`
  - New `FETCH: <url>` loop action (alongside `RUN:`/`DONE:`). The protocol now
    tells the model the sandbox has no internet and to use FETCH for the web.
  - `_do_fetch` runs `safe_fetch` on the **host** (never the sandbox), gated by the
    `web.fetch` capability (`_agent_caps`), shows a short preview line, and feeds a
    capped snippet back to the model explicitly labelled UNTRUSTED.
  - `parse_agent_action` recognises `FETCH:`.
- `routers/tools.py` registers `WebFetchTool`; `GET /execution/sandbox-info` and the
  UI sandbox chips expose `web_fetch_enabled`.
- UI: the AgentDetail allowlist field is re-labelled "上級者向け・通常は空でOK" — research
  goes through web.fetch, so the sandbox allowlist stays empty in the normal case.
- Config (`config.py`): `AIOS_WEB_FETCH` (on), `AIOS_WEB_FETCH_MAX_BYTES` (512 KiB),
  `AIOS_WEB_FETCH_TIMEOUT` (15s), `AIOS_WEB_FETCH_MAX_REDIRECTS` (4).

## Why this is safe where an open sandbox is not

- web.fetch **cannot run code, cannot read the sandbox filesystem**, and only does
  GET — so an injected page can't turn it into `curl|sh`, arbitrary exfiltration of
  sandbox files, or a shell. The blast radius is "text of a public URL entered the
  model's context", which is the same **intake** risk as manual research (and is
  not something a network allowlist ever addressed).
- The SSRF guard blocks the escalation paths that an open code-sandbox egress
  opens: cloud metadata, internal hosts, loopback services.
- Capability-gated: only an agent granted `web.fetch` (e.g. Researcher) can fetch.

## Tests

`tests/test_web_fetch.py` (18). Full suite **123 passed** (was 105). Web builds.
- SSRF: rejects loopback/private/link-local/metadata/`::1`/`0.0.0.0`; accepts a
  public IP literal; rejects non-http schemes; refuses metadata before any socket.
- Fake-opener happy path (HTML tag-stripped), redirect-target re-validation blocks
  a 302→metadata, non-text content refused.
- Parser recognises `FETCH:`; the loop fetches via the host and feeds it back;
  fetch is denied without the capability (and never calls out).

## Known Issues / Next

- DNS-rebinding TOCTOU (host validated, then re-resolved at connect) isn't fully
  closed; acceptable for local single-user use, notable if exposed multi-user.
- No `web.search` yet (only direct `web.fetch`); a search adapter is a later slice.
- The sandbox per-domain egress (for the rare case a sandbox command itself must
  reach the net) is still coarse — unchanged by this slice.
