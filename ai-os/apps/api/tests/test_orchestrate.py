"""Orchestrator tests — fake orchestrator + fake workers, no network."""
import os

os.environ.setdefault("AIOS_ALLOW_UNSAFE_LOCAL", "1")

from app.agent_loop import AgentLoop  # noqa: E402
from app.core.llm.base import LLMResponse, LLMUsage  # noqa: E402
from app.core.sandbox.local_runtime import LocalSubprocessRuntime  # noqa: E402
from app.execution_manager import ExecutionManager, LogLine  # noqa: E402
from app.orchestrator import OrchestratorRunner, compose_orchestration_prompt, parse_plan  # noqa: E402


class FakeProvider:
    """Returns a fixed reply, or successive replies from a list (one per call)."""
    name = "fake"

    def __init__(self, reply):
        self._replies = list(reply) if isinstance(reply, list) else None
        self._reply = reply
        self._i = 0

    async def complete(self, messages, *, model, tools=None, max_tokens=1024):
        if self._replies is not None:
            text = self._replies[min(self._i, len(self._replies) - 1)]
            self._i += 1
        else:
            text = self._reply
        return LLMResponse(text=text, usage=LLMUsage(input_tokens=3, output_tokens=3))


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


def test_orchestration_prompt_carries_env_constraints():
    # plans must be told the sandbox is offline, prefer text-first + SVG images
    p = compose_orchestration_prompt("画像付き記事を作って", [{"name": "Builder", "role": "code"}])
    assert "SVG" in p
    assert "テキスト成果物" in p
    assert "ネット遮断" in p


# ---- full run ----

async def test_orchestrate_dispatches_all_steps():
    plan = "Builder: ステップA\nReviewer: ステップB\nDONE"
    out = await _collect(_runner(plan, "DONE: 完了"), "ゴール", orchestrator="Planner")
    joined = "\n".join(s for _, s in out)
    assert "計画を受領" in joined
    assert "工程 1: Builder" in joined
    assert "工程 2: Reviewer" in joined
    assert "オーケストレーション完了 ✓" in joined


async def test_orchestrate_stops_when_plan_unparseable():
    out = await _collect(_runner("よくわからない返答", "DONE: x"), "ゴール")
    joined = "\n".join(s for _, s in out)
    assert "解析できませんでした" in joined
    assert "オーケストレーション完了" not in joined


async def test_make_plan_returns_parsed_steps():
    r = _runner("Builder: やる\nDONE", "DONE: ok")
    planned = await r.make_plan("ゴール", orchestrator="Planner")
    assert planned["plan"] == [{"agent": "Builder", "task": "やる"}]


async def test_preapproved_steps_skip_planning():
    # orchestrator provider would return junk, but steps are supplied → not used
    r = _runner("この計画は使われないはず", "DONE: できた")
    steps = [{"agent": "Builder", "task": "手動で決めた作業"}]
    out = await _collect(r, "ゴール", steps=steps)
    joined = "\n".join(s for _, s in out)
    assert "工程 1: Builder — 手動で決めた作業" in joined
    assert "オーケストレーション完了 ✓" in joined
    assert "[統括]" not in joined  # planning was skipped


async def test_report_chaining_feeds_prior_output():
    seen = []  # the goal each worker step actually received

    class SpyLoop:
        async def run(self, goal, *, agent_name, system=None, max_iterations=6, **_kw):
            seen.append(goal)
            yield LogLine("ok", "agent finished ✓")
            yield LogLine("out", f"{agent_name} の成果物")

    r = OrchestratorRunner(loop=SpyLoop(), provider=FakeProvider("Builder: A\nReviewer: B\nDONE"))
    await _collect(r, "ゴール")
    # 2nd worker's goal carries the 1st worker's report
    assert "これまでの成果" in seen[1]
    assert "Builder の成果物" in seen[1]


async def test_nonzero_exit_does_not_discard_a_valid_report():
    # A worker whose shell command exited non-zero (an `err` line) but still
    # produced a DONE report must count as SUCCESS — not trigger a re-plan.
    class ExitOneThenDoneLoop:
        async def run(self, goal, *, agent_name, system=None, max_iterations=6, **_kw):
            yield LogLine("cmd", f"{agent_name} → RUN: ls /missing")
            yield LogLine("err", "exited 1 · 0.1s")   # normal during exploration
            yield LogLine("ok", "agent finished ✓")
            yield LogLine("out", f"{agent_name} の成果物レポート")

    r = OrchestratorRunner(loop=ExitOneThenDoneLoop(), provider=FakeProvider("Builder: A\nDONE"))
    out = await _collect(r, "ゴール")
    joined = "\n".join(s for _, s in out)
    assert "成果を出せませんでした" not in joined  # not treated as a failure
    assert "再計画" not in joined
    assert "オーケストレーション完了 ✓" in joined


async def test_orchestrator_hands_files_to_next_worker():
    import json
    seen_seeds = []

    class Loop:
        async def run(self, goal, *, agent_name, system=None, max_iterations=6, seed_files=None, **_kw):
            seen_seeds.append(list(seed_files or []))
            yield LogLine("ok", "agent finished ✓")
            if agent_name == "Builder":
                yield LogLine("file", json.dumps({"path": "out.md", "size": 6, "content": "本文"}))
            yield LogLine("out", f"{agent_name} done")

    r = OrchestratorRunner(loop=Loop(), provider=FakeProvider("Builder: 作る\nReviewer: 見る\nDONE"))
    await _collect(r, "ゴール")
    assert seen_seeds[0] == []  # first worker gets nothing
    # the second worker receives the Builder's generated file under seed_files
    assert any(f["path"] == "out.md" and f["content"] == "本文" for f in seen_seeds[1])


async def test_replan_on_worker_failure():
    # worker always fails (never emits 'agent finished ✓' → no report). The
    # orchestrator replans once, the revision also fails → stops at the limit.
    plans = ["Builder: 最初", "Reviewer: 立て直し"]

    class FailLoop:
        async def run(self, goal, *, agent_name, system=None, max_iterations=6, **_kw):
            yield LogLine("warn", "reached max iterations")

    r = OrchestratorRunner(loop=FailLoop(), provider=FakeProvider(plans))
    out = await _collect(r, "ゴール", max_replans=1)
    joined = "\n".join(s for _, s in out)
    assert "再計画を依頼します（1/1）" in joined
    assert "[統括·再計画]" in joined
    assert "再計画の上限" in joined
