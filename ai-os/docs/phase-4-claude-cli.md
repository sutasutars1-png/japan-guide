# Phase 4 · #5 — Claude Code CLI provider (the keyless orchestrator)

*Report format per roadmap §2.2. Lets Claude be the orchestrator (統括AI) with no
API key, no metered cost, and no ToS-grey token injection — by having the backend
shell out to the user's own, already-logged-in `claude` binary.*

## The problem it solves

The user's core design is: user goal → orchestrator (Claude) decomposes and
dispatches → cheap worker agents (Gemini free API) execute. But a browser web UI
**cannot reach an API-less AI directly** (same-origin/sandbox). The access must go
`UI → own backend → bridge → Claude`, and the only clean bridges are:

- the **human** (manual copy-paste bridge — built earlier), or
- the **backend running the local `claude` CLI** — automatic, clean. This is #5.

Using your own installed, logged-in `claude` as yourself is normal personal use.
It is **not** the rejected "token injection" (prying a credential out and smuggling
it into a foreign container).

## Implementation

- **`core/llm/claude_cli_provider.py`** — `ClaudeCliProvider` implements the normal
  `LLMProvider.complete()`: it renders the (masked) messages to a prompt, feeds it
  to `claude -p --output-format text` over **stdin**, and returns stdout. So the
  agent loop / flows / orchestrator call it exactly like Gemini — the only
  difference is the transport.
- **Brain vs hands** — this runs on the **host** (the backend process), never
  inside the task sandbox. The credential channel (Claude login) is kept separate
  from the untrusted command-execution channel, so a prompt-injected sandbox agent
  can never reach it.
- **Text-only invocation (safe):** `--dangerously-skip-permissions` is **never**
  passed, so in headless mode any tool the model attempts is auto-denied — it can
  only return text. Common mutating tools are additionally `--disallowed-tools`,
  and it runs in a throwaway temp cwd. The whole invocation is overridable via
  `AIOS_CLAUDE_CLI_ARGS` so a CLI flag change is a config edit, not a code change.
- **Routing:** model id `claude-cli` → this provider (via `get_provider_for_model`
  and the Connections registry). Set an agent's model to `claude-cli` to make that
  agent the keyless Claude orchestrator.
- **Connections:** a new `cli`-kind provider "Claude Code（ローカルCLI・自動）";
  `connected` iff the `claude` binary is found on PATH; the UI card explains it
  runs the user's own login and must be started on a logged-in machine.
- **Config:** `AIOS_CLAUDE_CLI` (path), `AIOS_CLAUDE_CLI_MODEL`,
  `AIOS_CLAUDE_CLI_TIMEOUT`, `AIOS_CLAUDE_CLI_ARGS`,
  `AIOS_CLAUDE_CLI_FORCE_SUBSCRIPTION`.
- **Billing safety (subscription, not metered API):** the CLI provider spawns
  `claude` with `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` **stripped from its
  environment** (default). So even if the user has set an Anthropic API key for
  API workers, the orchestrator CLI uses the **subscription login** — it can never
  silently switch to metered API billing. Not logged in → the CLI fails cleanly
  (a visible error), never a surprise charge. `--bare` (which forces API-key auth)
  is never used. Opt out with `AIOS_CLAUDE_CLI_FORCE_SUBSCRIPTION=0`.

## Tests
- `pytest` green (71). New `test_claude_cli.py` (subprocess mocked, no real call):
  returns stdout; never passes a skip-permissions flag; runs in a throwaway cwd;
  masks secrets before spawning; surfaces CLI errors; clear error when the binary
  is missing; model→provider routing + `cli` connection status.
- `next build` type-checks with the `cli` connection card.

## Security Tests
- Prompt masked before it reaches the CLI (verified). No skip-permissions flag →
  host stays untouched. Runs outside the task sandbox; no new sandbox capability.

## Known Issues
- Requires the backend to run where the user is logged into Claude Code (their PC
  or a Claude Code managed env). This is the same "run locally" premise as the
  Docker sandbox.
- The CLI text output carries no token counts, so usage is reported as zero for
  CLI turns (never fabricated).
- Single-user personal use only. Fanning one login out to many users in a hosted
  service would be ToS-abusive and is out of scope.

## Next
- The orchestration entrypoint: `/orchestrate` (goal → composed orchestrator
  prompt → plan) + a plan parser + auto-dispatch to worker agents. With #5 the
  orchestrator step becomes fully automatic; the flow's stations become
  plan-driven (authored by the orchestrator) instead of fixed.
