# Phase 4 · Stage 3c — Multi-agent flows (Planner→Builder→Reviewer auto-chaining)

*Report format per roadmap §2.2. Implements the フロー / ハンドオフ規約 part of the
Phase 4 design: several agents auto-chained into one pipeline, using the
system-owned handoff protocol as the seam between stations.*

## Concept

A **Flow** is an ordered list of **stations** (工程), each bound to an agent
(Planner, Builder, Reviewer…). The runner drives them in order:

```
goal → [Planner loop] → DONE報告 → [Builder loop] → DONE報告 → [Reviewer loop] → フロー完了
```

Each station runs its **own** PLAN→EXECUTE→OBSERVE agent loop (Stage 2), composed
from its live skills (Stage 3a/3b: presets + overlays). When a station finishes,
its DONE report becomes the next station's context — the "手動コピペの手間を感じさ
せない" handoff the design calls for, done automatically.

## Handoff protocol (system-owned)

Routing between stations is decided two ways, in priority order:

1. **Agent override** — an agent may end its DONE report with a line
   `→NEXT: <工程名>` (or `→NEXT: DONE`). This is injected by
   `flow_handoff_note()` as a *system-owned* instruction, kept separate from and
   authoritative over user skills — the same posture as the RUN:/DONE: protocol.
   It lets a Reviewer bounce work back to the Builder, or declare the whole goal
   done early.
2. **Station default** — if the agent gives no directive, the flow follows the
   station's configured `next`.

`parse_next()` reads the override defensively: it only matches `NEXT:` at the
start of a line (so prose mentioning "next" never mis-routes), and an unknown
target falls back to `DONE` rather than crashing the pipeline.

Because a multi-line DONE report is now needed to carry the trailing `→NEXT:`
line, `parse_agent_action()` was fixed to capture the **whole** report from the
`DONE:` line to the end (previously it kept only the first line).

## Implementation

- **`app/flow.py`** — `FlowRunner.run(goal, flow)` async-generates log lines:
  for each station it composes `system = compose_system(stage, skills_for(stage))
  + flow_handoff_note(...)`, runs the inner `AgentLoop`, captures that station's
  DONE report, yields every line prefixed `[stage]`, then routes to the next
  station. Bounded by the flow's `max_iterations` (total station runs) so a
  Reviewer→Builder bounce loop can never run forever.
- **Seed flows (`FLOWS`)** — `flow.default` (Planner→Builder→Reviewer, max 10),
  `flow.solo` (Builder only, max 6), `flow.research` (Researcher→Builder, max 8).
- **Router (`app/routers/flow.py`)** — `GET /flows`, `POST /flow/run` (full log;
  404 on unknown flow), `WS /flow/stream` (live; always sends `stream closed`).
- **UI (`CommandBar`)** — a third mode 「🔀 フローで実行」 next to
  「AIにゴールを渡す」/「コマンドを直接実行」, with a pipeline selector populated
  from `GET /flows`. `streamFlow()` opens the WS; each station's lines land in the
  same sandbox log, tagged by stage.

## Safety

Safety carries over unchanged from the inner loop — the flow adds orchestration
only, never a bypass:

- Blocked commands (`rm -rf /`, `mkfs`, …) still never run, in any station.
- A high-risk (L3/L4) command **halts** the station; the runner stops the whole
  flow rather than auto-continuing — no autonomous destruction across stations.
- The handoff note is system-owned and cannot widen capabilities (Default Deny is
  separate). Skills only shape guidance.
- All station transitions are audited (`flow.start` / `flow.done` / `flow.max`).

## Tests

- `pytest` green (59 tests). New `test_flow.py`: `parse_next` routing (override,
  DONE, none, unknown→DONE); a linear flow visits all three stages and reports
  「フロー完了 ✓」; a `→NEXT: Builder` bounce loop is bounded and stops at
  「最大反復」 without completing; the solo flow runs one station. All use a fake
  provider + the local runtime — no network, no real LLM.
- `next build` compiles and type-checks with the new flow mode.

## Known Issues

- Flows are seeded in-memory; a user-editable flow builder (drag stations) is a
  later slice behind the same `list_flows()`/`get_flow()` functions.
- Report capture keys off the inner loop's "agent finished ✓" marker; if a
  provider streams a partial DONE the last-report heuristic takes the final block.
- `per_agent_iters` is a fixed default (6); per-station iteration budgets are not
  yet surfaced in the flow definition.

## Next

- Optional: persist flows/presets to Postgres or JSON so config survives restart.
- Optional: a visual flow builder in the Flow view, wired to the same endpoints.
