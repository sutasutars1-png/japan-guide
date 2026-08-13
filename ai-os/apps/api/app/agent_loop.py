"""Agent loop (roadmap Phase 4) — PLAN → EXECUTE → OBSERVE, bounded.

A single agent works toward a goal: on each turn it asks the LLM for the next
step, runs any proposed shell command through the sandbox (Phase 2 + Phase 3
safety), feeds the output back, and repeats — until the LLM says DONE, or the
iteration / token budget is spent.

Safety posture:
  - blocked commands (rm -rf /, mkfs, …) never run; the agent is told and adapts.
  - high-risk commands (L3/L4) are NOT auto-executed — the loop stops and asks
    the human to run them deliberately (never autonomous destruction).

Provider and manager are injected so the loop is fully testable offline with a
fake provider + the local runtime.
"""
from __future__ import annotations

from typing import AsyncIterator

from .config import settings
from .core.audit import AuditEvent, log
from .core.llm import LLMMessage, get_llm_provider
from .core.policy import evaluate
from .execution_manager import LogLine, get_execution_manager

DEFAULT_ROLE = (
    "You are a careful autonomous engineer working toward the user's goal inside "
    "a secure, network-restricted Linux sandbox."
)

LOOP_PROTOCOL = (
    "Work in small steps. On EACH turn reply with EXACTLY ONE line, in one of "
    "these two forms, and nothing else:\n"
    "\n"
    "RUN: <one shell command to execute in the sandbox>\n"
    "DONE: <your final answer / report to the user>\n"
    "\n"
    "You will see each command's output before your next turn. Use RUN to inspect "
    "and act; use DONE only when the goal is achieved or truly blocked. Do not add "
    "commentary outside the RUN:/DONE: line, and do not use code fences."
)


def parse_agent_action(text: str) -> tuple[str, str]:
    """Return ("run", command) | ("done", report) from an LLM reply.

    Robust to code fences and leading prose; falls back to DONE (treat the whole
    reply as the report) so a mis-formatted answer never spins the loop forever.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # drop surrounding fences
        lines = [ln for ln in cleaned.splitlines() if not ln.strip().startswith("```")]
        cleaned = "\n".join(lines).strip()

    lines = cleaned.splitlines()
    for idx, line in enumerate(lines):
        s = line.strip()
        if s.upper().startswith("RUN:"):
            return "run", s[4:].strip()
        if s.upper().startswith("DONE:"):
            # A DONE report may span multiple lines (e.g. a trailing `→NEXT:`
            # handoff line): keep everything from here to the end.
            first = s[5:].strip()
            rest = lines[idx + 1:]
            return "done", "\n".join([first, *rest]).strip()
    return "done", cleaned


def _wrap(text: str) -> list[str]:
    return [ln for ln in text.splitlines()] or [text]


class AgentLoop:
    def __init__(self, provider=None, manager=None, model: str | None = None) -> None:
        self._provider = provider or get_llm_provider()
        self._manager = manager or get_execution_manager()
        self._model = model or settings.llm_model

    async def run(
        self,
        goal: str,
        *,
        agent_name: str = "Builder",
        system: str | None = None,
        max_iterations: int = 8,
        token_budget: int | None = None,
    ) -> AsyncIterator[LogLine]:
        budget = token_budget if token_budget is not None else settings.llm_token_budget
        history: list[LLMMessage] = [
            LLMMessage(role="system", content=(system or DEFAULT_ROLE) + "\n\n" + LOOP_PROTOCOL),
            LLMMessage(role="user", content=f"Goal: {goal}"),
        ]
        used_tokens = 0
        yield LogLine("sys", f"agent '{agent_name}' · model {self._model} · goal: {goal}")
        log.append(AuditEvent("agent.start", agent_name, goal))

        for i in range(max_iterations):
            yield LogLine("sys", f"— iteration {i + 1}/{max_iterations} · thinking… —")
            try:
                resp = await self._provider.complete(history, model=self._model, max_tokens=1024)
            except Exception as exc:  # noqa: BLE001 — surface LLM/transport errors
                yield LogLine("err", f"LLM error: {exc}")
                return

            used_tokens += resp.usage.total
            text = (resp.text or "").strip()
            history.append(LLMMessage(role="assistant", content=text))
            kind, payload = parse_agent_action(text)

            if kind == "done":
                yield LogLine("ok", "agent finished ✓")
                for ln in _wrap(payload):
                    yield LogLine("out", ln)
                log.append(AuditEvent("agent.done", agent_name, payload[:200]))
                return

            command = payload
            if not command:
                history.append(LLMMessage(role="user", content="Empty command. Reply with RUN: <cmd> or DONE: <report>."))
                continue

            decision = evaluate(command)
            if not decision.allowed:
                yield LogLine("err", f"blocked: {decision.reason} → {command}")
                log.append(AuditEvent("policy.block", agent_name, decision.reason, int(decision.risk)))
                history.append(LLMMessage(role="user", content=f"That command was blocked by policy ({decision.reason}). Choose a safer approach."))
                continue
            if decision.requires_approval:
                yield LogLine("halt", f"agent stopped for safety — high-risk command (L{int(decision.risk)}) needs your approval: {command}")
                log.append(AuditEvent("agent.halt", agent_name, command, int(decision.risk)))
                return

            yield LogLine("sys", f"{agent_name} → RUN: {command}")
            observed: list[str] = []
            async for line in self._manager.run(command, actor=agent_name):
                yield line
                observed.append(f"[{line.t}] {line.s}")

            # OBSERVE: feed the (tail of the) output back to the agent.
            tail = "\n".join(observed[-40:]) or "(no output)"
            history.append(LLMMessage(role="user", content=f"Command output:\n{tail}"))

            if used_tokens > budget:
                yield LogLine("warn", f"token budget reached (~{used_tokens}/{budget}) — stopping")
                log.append(AuditEvent("agent.budget", agent_name, f"~{used_tokens} tokens"))
                return

        yield LogLine("warn", f"reached max iterations ({max_iterations}) — stopping")
        log.append(AuditEvent("agent.max_iterations", agent_name, goal))


_loop: AgentLoop | None = None


def get_agent_loop() -> AgentLoop:
    global _loop
    if _loop is None:
        _loop = AgentLoop()
    return _loop
