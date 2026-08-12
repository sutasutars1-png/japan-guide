# Phase 4 · Stage 2 — Agent Loop (PLAN → EXECUTE → OBSERVE)

*Report format per roadmap §2.2 / §48. Second slice of the Phase 4 design: a
single-agent loop that thinks, acts in the sandbox, observes, and iterates.*

## Implementation
- `app/agent_loop.py` — `AgentLoop`. Each turn:
  1. **PLAN**: ask the LLM (`provider.complete`) for the next step, given the
     goal + history + a small system-injected protocol.
  2. Parse the reply: `RUN: <cmd>` or `DONE: <report>` (`parse_agent_action`,
     robust to code fences; falls back to DONE so a malformed reply never spins).
  3. **EXECUTE**: run the command through the Execution Manager (Phase 2 sandbox
     + Phase 3 policy), streaming its log lines.
  4. **OBSERVE**: feed the (tail of the) output back into the conversation.
  - Bounded by `max_iterations` **and** a token budget (`LLM_TOKEN_BUDGET`).
  - Provider + manager are injected → fully testable offline.
- **Safety posture inside the loop:**
  - *blocked* commands (rm -rf /, mkfs, …) never run; the agent is told and adapts.
  - *high-risk* (L3/L4) commands are **not** auto-executed — the loop stops and
    asks the human to run them deliberately. No autonomous destruction.
  - Every step is audited (`agent.start`/`agent.done`/`policy.block`/`agent.halt`/
    `agent.budget`/`agent.max_iterations`).
- `routers/agent.py` — `WS /agent/stream` (give a goal, watch live) and
  `POST /agent/run`.
- UI: the command bar now has a **✨ AIにゴールを渡す / › コマンドを直接実行**
  toggle. Goal mode streams the loop; command mode is the Phase 2 direct run.

## Tests
- `pytest` green (36 tests). New `test_agent.py` (fake provider + local sandbox):
  parser (RUN/DONE/fence/fallback); loop runs a command then finishes; high-risk
  command halts the loop for approval (second reply never used); blocked command
  lets the agent adapt and finish; max-iterations stop.
- `next build` compiles and type-checks.
- End-to-end demo (fake LLM → real local sandbox): think → run (`23 9`) →
  observe → iterate → DONE with a report.

## Security Tests
- Autonomous execution is limited to allowed, non-high-risk commands; blocked
  and L3/L4 commands cannot be auto-run by the agent.
- All LLM messages pass through secret masking (provider layer); loop output fed
  back to the LLM is the same masked sandbox log.

## Known Issues
- Live LLM not exercised in CI (no key). On a real machine with a Gemini key, the
  loop uses Gemini; verify with a small goal.
- Single agent only. Multi-agent flows, the handoff-protocol *between* agents,
  the skills library, and the manual-paste provider are later stages
  (see `phase-4-design.md`).
- On a high-risk halt the loop stops; resuming after approval (continuing the
  loop) is a future enhancement — for now the human runs that command manually.

## Next Phase
- Skills (base preset + overlay), reconfigurable multi-agent flows with the
  handoff protocol, and the `ManualPasteProvider`.

## DoD (roadmap Phase 4)
- ✅ 「このデータを分析して」→ AI がサンドボックス内でコードを実行し結果を報告。
- ✅ 反復上限・トークン予算・危険実行の承認停止が効く(暴走しない)。
