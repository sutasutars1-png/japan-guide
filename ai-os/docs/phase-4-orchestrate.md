# Phase 4 · Orchestrate — goal → 統括AI plan → workers auto-dispatch

*Report format per roadmap §2.2. The entrypoint the whole design aimed at: a user
goal goes to the orchestrator (統括AI), which authors a plan; the app parses it and
dispatches each step to a worker agent automatically.*

## Flow

```
ユーザーのゴール
   ↓  POST /orchestrate  (or WS /orchestrate/stream)
統括AI（既定=Planner）… 1回のcompletionでゴールを工程に分解      ← 人の手はここだけ（CLIなら0）
   ↓  parse_plan → [{agent, task}, …]
Builder / Researcher / Reviewer …（各自のモデル→プロバイダで実行）   ← 全自動
   ↓
オーケストレーション完了 ✓
```

## Implementation

- **`app/orchestrator.py`**
  - `compose_orchestration_prompt(goal, workers)` — wraps the raw goal into the
    orchestration prompt: available worker agents (name + role), a strict output
    format (`<agent>: <task>` lines, then `DONE`), and the goal.
  - `parse_plan(text, worker_names)` — tolerant parser: only lines whose prefix is
    a known agent become steps (bullets/fences/prose ignored), `DONE` ends it.
  - `OrchestratorRunner.run(goal, orchestrator="Planner")` — **single-shot** call
    to the orchestrator's provider (resolved from its model: `claude-cli`→auto,
    `claude-web`→one paste, `gemini-*`→API), then dispatches each step to the
    worker's ordinary agent loop, streaming `[stage]`-tagged lines. Stops if a
    worker halts (L3/L4 approval) or the plan can't be parsed. Bounded by
    `max_workers`.
- **`app/routers/orchestrate.py`** — `POST /orchestrate`, `WS /orchestrate/stream`.
- **UI** — a new 「🧭 統括AIに任せる」 mode in the command bar (now the default),
  alongside 単体AI / フロー / コマンド. `streamOrchestrate()` in `lib/api.ts`.

## Why single-shot orchestrator
Making the orchestrator one call (plan the whole thing) — not a RUN/DONE loop —
means a manual/CLI orchestrator costs **at most one human touch per goal** (zero
with the CLI). "手間を感じさせない" = rare touch, not zero: one orchestration →
many automatic worker steps.

## Tests
- `pytest` green (76). New `test_orchestrate.py`: `parse_plan` extracts known
  agents / ignores unknowns / stops at DONE; `compose_orchestration_prompt` lists
  workers + goal; a full run dispatches every step and completes; an unparseable
  plan stops cleanly. Fake orchestrator + fake workers + local runtime — no
  network.
- `next build` type-checks with the orchestrate mode.

## Security Tests
- Workers run the ordinary loop, so blocked commands never run and an L3/L4 command
  halts the worker and the whole run. The orchestrator prompt is masked by the
  provider before it leaves. All transitions audited (`orchestrate.start/plan/
  halt/done`).

## Report chaining, re-plan, and plan review (all implemented)
- **Report chaining** — each worker's DONE report is captured and prepended (last
  few) to the next step's context via `_with_context(...)`, so工程が積み上がる.
- **Re-plan loop** — if a worker produces no result (error / no DONE report), the
  orchestrator is consulted again with `compose_replan_prompt(...)` for a revised
  *remaining* plan; bounded by `max_replans` (default 2). An L3/L4 approval **halt**
  still stops the run (a human decision, never re-planned).
- **Plan-first / editable checklist** — `make_plan()` returns the parsed plan
  without running; `POST /orchestrate/plan` serves it. `run(..., steps=<edited>)`
  (and the WS/POST `steps` field) dispatch a pre-approved plan, skipping planning.
  UI: a 「計画を確認してから実行」 toggle shows a `PlanReview` panel (edit agent/task,
  reorder, add/remove) before dispatch.

## Known Issues
- `per_worker_iters` / `max_workers` / `max_replans` are fixed defaults (not yet
  surfaced in the UI).
- Re-plan replaces the *remaining* queue wholesale; it does not diff against
  already-done work beyond passing a completed-steps summary.

## Next
- Surface iteration/worker/re-plan budgets in the UI.
- Optional `→NEXT:`-style conditional routing inside a single plan.
