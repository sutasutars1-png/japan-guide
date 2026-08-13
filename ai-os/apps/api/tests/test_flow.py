"""Multi-agent flow tests — fake LLM + local sandbox, no network."""
import os

os.environ.setdefault("AIOS_ALLOW_UNSAFE_LOCAL", "1")

from app.agent_loop import AgentLoop  # noqa: E402
from app.core.llm.base import LLMResponse, LLMUsage  # noqa: E402
from app.core.sandbox.local_runtime import LocalSubprocessRuntime  # noqa: E402
from app.execution_manager import ExecutionManager  # noqa: E402
from app.flow import FlowRunner, get_flow, parse_next  # noqa: E402


class FakeProvider:
    name = "fake"

    def __init__(self, reply):
        self._reply = reply

    async def complete(self, messages, *, model, tools=None, max_tokens=1024):
        # Each station finishes in one turn with a DONE report.
        return LLMResponse(text=self._reply, usage=LLMUsage(input_tokens=3, output_tokens=3))


def _runner(reply):
    loop = AgentLoop(provider=FakeProvider(reply),
                     manager=ExecutionManager(LocalSubprocessRuntime()), model="fake")
    return FlowRunner(loop=loop)


async def _collect(runner, goal, flow):
    out = []
    async for line in runner.run(goal, flow):
        out.append((line.t, line.s))
    return out


# ---- routing parser ----

def test_parse_next():
    stages = ["Planner", "Builder", "Reviewer"]
    assert parse_next("done\n→NEXT: Builder", stages) == "Builder"
    assert parse_next("all set\nNEXT: done", stages) == "DONE"
    assert parse_next("no directive here", stages) is None
    assert parse_next("→NEXT: Nobody", stages) == "DONE"  # unknown → end


# ---- flow behaviour ----

async def test_linear_flow_visits_all_stages_and_completes():
    flow = get_flow("flow.default")   # Planner → Builder → Reviewer → DONE
    out = await _collect(_runner("DONE: 工程完了"), "簡単なゴール", flow)
    joined = "\n".join(s for _, s in out)
    assert "▶ 工程 1: Planner" in joined
    assert "▶ 工程 2: Builder" in joined
    assert "▶ 工程 3: Reviewer" in joined
    assert "フロー完了 ✓" in joined


async def test_next_override_loops_back_and_is_bounded():
    flow = get_flow("flow.default")
    # every station demands going back to Builder → would loop forever, but the
    # flow is bounded by max_iterations and stops cleanly.
    out = await _collect(_runner("DONE: やり直し\n→NEXT: Builder"), "ループ", flow)
    joined = "\n".join(s for _, s in out)
    assert "最大反復" in joined
    assert "フロー完了 ✓" not in joined


async def test_solo_flow_one_stage():
    out = await _collect(_runner("DONE: できました"), "単独タスク", get_flow("flow.solo"))
    joined = "\n".join(s for _, s in out)
    assert "▶ 工程 1: Builder" in joined
    assert "フロー完了 ✓" in joined
