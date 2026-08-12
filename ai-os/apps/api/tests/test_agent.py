"""Agent-loop tests — fake LLM provider + local sandbox, no network."""
import os

os.environ.setdefault("AIOS_ALLOW_UNSAFE_LOCAL", "1")

from app.agent_loop import AgentLoop, parse_agent_action  # noqa: E402
from app.core.llm.base import LLMResponse, LLMUsage  # noqa: E402
from app.core.sandbox.local_runtime import LocalSubprocessRuntime  # noqa: E402
from app.execution_manager import ExecutionManager  # noqa: E402


class FakeProvider:
    """Returns scripted replies in order; loops on the last one."""

    name = "fake"

    def __init__(self, replies):
        self._replies = list(replies)
        self._i = 0

    async def complete(self, messages, *, model, tools=None, max_tokens=1024):
        reply = self._replies[min(self._i, len(self._replies) - 1)]
        self._i += 1
        return LLMResponse(text=reply, usage=LLMUsage(input_tokens=5, output_tokens=5))


def _loop(replies):
    return AgentLoop(
        provider=FakeProvider(replies),
        manager=ExecutionManager(LocalSubprocessRuntime()),
        model="fake",
    )


async def _collect(loop, goal, **kw):
    out = []
    async for line in loop.run(goal, **kw):
        out.append((line.t, line.s))
    return out


# ---- parser ----

def test_parse_run_and_done():
    assert parse_agent_action("RUN: ls -la") == ("run", "ls -la")
    assert parse_agent_action("DONE: finished the task") == ("done", "finished the task")


def test_parse_strips_fences_and_falls_back_to_done():
    assert parse_agent_action("```\nRUN: echo hi\n```") == ("run", "echo hi")
    # no marker → treat whole text as the final report
    assert parse_agent_action("just some prose")[0] == "done"


# ---- loop behaviour ----

async def test_loop_runs_command_then_finishes():
    out = await _collect(_loop(["RUN: echo hello-agent", "DONE: all good"]), "say hello")
    joined = "\n".join(s for _, s in out)
    assert "hello-agent" in joined          # command actually executed in the sandbox
    assert "agent finished ✓" in joined
    assert "all good" in joined


async def test_high_risk_command_stops_the_loop_for_approval():
    out = await _collect(_loop(["RUN: git push origin main", "DONE: should not reach"]), "deploy")
    kinds = [t for t, _ in out]
    joined = "\n".join(s for _, s in out)
    assert "halt" in kinds
    assert "needs your approval" in joined
    assert "should not reach" not in joined  # loop stopped; second reply never used


async def test_blocked_command_lets_agent_adapt():
    out = await _collect(_loop(["RUN: rm -rf /", "DONE: chose a safer path"]), "clean up")
    joined = "\n".join(s for _, s in out)
    assert "blocked" in joined
    assert "agent finished ✓" in joined     # agent recovered and finished


async def test_max_iterations_stops():
    out = await _collect(_loop(["RUN: echo loop"]), "spin", max_iterations=2)
    joined = "\n".join(s for _, s in out)
    assert "reached max iterations (2)" in joined
