"""Orchestrator tests — fake orchestrator + fake workers, no network."""
import os

os.environ.setdefault("AIOS_ALLOW_UNSAFE_LOCAL", "1")

from app.agent_loop import AgentLoop  # noqa: E402
from app.core.llm.base import LLMResponse, LLMUsage  # noqa: E402
from app.core.sandbox.local_runtime import LocalSubprocessRuntime  # noqa: E402
from app.execution_manager import ExecutionManager  # noqa: E402
from app.orchestrator import OrchestratorRunner, compose_orchestration_prompt, parse_plan  # noqa: E402


class FakeProvider:
    name = "fake"

    def __init__(self, reply):
        self._reply = reply

    async def complete(self, messages, *, model, tools=None, max_tokens=1024):
        return LLMResponse(text=self._reply, usage=LLMUsage(input_tokens=3, output_tokens=3))


def _runner(plan_text, worker_reply):
    worker_loop = AgentLoop(provider=FakeProvider(worker_reply),
                            manager=ExecutionManager(LocalSubprocessRuntime()), model="fake")
    return OrchestratorRunner(loop=worker_loop, provider=FakeProvider(plan_text))


async def _collect(runner, goal, **kw):
    return [(l.t, l.s) async for l in runner.run(goal, **kw)]


# ---- plan parsing ----

def test_parse_plan_extracts_known_agents():
    names = ["Researcher", "Builder", "Reviewer"]
    text = "前置き\n- Builder: 実装して\nResearcher: 調べて\nおまけ\nDONE\nBuilder: 無視される"
    plan = parse_plan(text, names)
    assert plan == [
        {"agent": "Builder", "task": "実装して"},
        {"agent": "Researcher", "task": "調べて"},
    ]


def test_parse_plan_ignores_unknown_agents():
    assert parse_plan("Nobody: x\nDONE", ["Builder"]) == []


def test_compose_prompt_lists_workers_and_goal():
    p = compose_orchestration_prompt("集計して", [{"name": "Builder", "role": "code"}])
    assert "Builder: code" in p
    assert "集計して" in p
    assert "DONE" in p


# ---- full run ----

async def test_orchestrate_dispatches_all_steps():
    plan = "Builder: ステップA\nReviewer: ステップB\nDONE"
    out = await _collect(_runner(plan, "DONE: 完了"), "ゴール", orchestrator="Planner")
    joined = "\n".join(s for _, s in out)
    assert "計画を受領" in joined
    assert "工程 1/2: Builder" in joined
    assert "工程 2/2: Reviewer" in joined
    assert "オーケストレーション完了 ✓" in joined


async def test_orchestrate_stops_when_plan_unparseable():
    out = await _collect(_runner("よくわからない返答", "DONE: x"), "ゴール")
    joined = "\n".join(s for _, s in out)
    assert "解析できませんでした" in joined
    assert "オーケストレーション完了" not in joined
