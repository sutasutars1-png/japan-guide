"""Orchestrator (Phase 4) — goal → 統括AI plans → workers auto-dispatch.

This is the entrypoint the whole design was aiming at:

    ユーザーのゴール
       ↓
    統括AI（Planner）… ゴールを分解して各ワーカーへ割当     ← 1回だけ
       ↓ 構造化された計画を解析して自動ディスパッチ
    Builder / Researcher / Reviewer …（各自のプロバイダで実行）  ← 全自動

The orchestrator is a **single-shot** call (one completion → the whole plan), so a
manual/CLI orchestrator means at most one human touch (or none, with the CLI).
Its provider is resolved from its model like any agent: `claude-cli` → automatic
keyless Claude, `claude-web` → one paste, `gemini-*` → API. The app owns
composition + parsing + dispatch; the orchestrator only authors the plan.

Safety carries over: each worker runs the ordinary PLAN→EXECUTE→OBSERVE loop, so
blocked commands never run and an L3/L4 command halts that worker (and the run).
"""
from __future__ import annotations

import re
from typing import AsyncIterator

from . import agents_store
from .agent_loop import AgentLoop, get_agent_loop
from .config import settings
from .core.audit import AuditEvent, log
from .core.llm import LLMMessage, get_provider_for_model
from .execution_manager import LogLine
from .skills import compose_system

ORCH_SYSTEM = (
    "あなたはオーケストレーター（統括AI）です。ユーザーのゴールを、指定された実行"
    "エージェントに割り当てる具体的なタスクへ分解します。出力は指定フォーマットのみ。"
)


def worker_roster(exclude: str) -> list[dict]:
    """Agents the orchestrator may dispatch to (everyone but itself)."""
    return [a for a in agents_store.list_agents() if a["name"] != exclude]


def compose_orchestration_prompt(goal: str, workers: list[dict]) -> str:
    lines = ["# 使えるエージェント"]
    for a in workers:
        role = (a.get("role") or "").strip().replace("\n", " ")
        lines.append(f"- {a['name']}: {role}")
    roster = "\n".join(lines)
    names = " / ".join(a["name"] for a in workers)
    return (
        f"{roster}\n\n"
        "# 出力フォーマット（厳守）\n"
        "各行を「<エージェント名>: <その工程への具体的な指示>」の形式で、実行する順に"
        f"並べてください（エージェント名は {names} のいずれか）。\n"
        "最後の行に「DONE」とだけ書いてください。前置き・説明・箇条書き記号は書かない。\n\n"
        f"# ユーザーのゴール\n{goal}"
    )


def parse_plan(text: str, worker_names: list[str]) -> list[dict]:
    """Extract `<agent>: <task>` steps from the orchestrator's reply.

    Tolerant of bullets/fences/prose: only lines whose prefix (before ':') is a
    known agent name become steps; everything else is ignored; `DONE` ends it.
    """
    by_lower = {n.lower(): n for n in worker_names}
    steps: list[dict] = []
    for raw in text.splitlines():
        line = raw.strip().lstrip("-•*　 ").strip()
        if not line:
            continue
        if line.upper().rstrip("。.") == "DONE":
            break
        m = re.match(r"^([^:：]+)[:：]\s*(.+)$", line)
        if not m:
            continue
        name = by_lower.get(m.group(1).strip().lower())
        task = m.group(2).strip()
        if name and task:
            steps.append({"agent": name, "task": task})
    return steps


class OrchestratorRunner:
    def __init__(self, loop: AgentLoop | None = None, provider=None) -> None:
        self._loop = loop or get_agent_loop()   # runs the workers
        self._provider = provider                # orchestrator provider (None = resolve)

    async def run(
        self,
        goal: str,
        *,
        orchestrator: str = "Planner",
        per_worker_iters: int = 6,
        max_workers: int = 12,
    ) -> AsyncIterator[LogLine]:
        yield LogLine("sys", f"統括AI『{orchestrator}』にゴールを渡します · {goal}")
        log.append(AuditEvent("orchestrate.start", "human", goal))

        workers = worker_roster(orchestrator)
        if not workers:
            yield LogLine("warn", "ディスパッチ先のワーカーがいません。")
            return

        # --- 1) ask the orchestrator for a plan (single shot) ---
        orch = agents_store.get_by_name(orchestrator)
        model = (orch or {}).get("model") or settings.llm_model
        provider = self._provider or get_provider_for_model(model)
        prompt = compose_orchestration_prompt(goal, workers)
        yield LogLine("sys", f"統括AI 思考中… · model {model}")
        try:
            resp = await provider.complete(
                [LLMMessage(role="system", content=ORCH_SYSTEM),
                 LLMMessage(role="user", content=prompt)],
                model=model, max_tokens=1024,
            )
        except Exception as exc:  # noqa: BLE001 — surface provider/CLI/bridge errors
            yield LogLine("err", f"統括AIエラー: {exc}")
            return

        plan_text = (resp.text or "").strip()
        for ln in plan_text.splitlines():
            yield LogLine("out", f"[統括] {ln}")

        steps = parse_plan(plan_text, [w["name"] for w in workers])
        if not steps:
            yield LogLine("warn", "計画を解析できませんでした（割当行が見つかりません）。")
            return
        yield LogLine("ok", f"計画を受領 · {len(steps)} 工程を自動実行します")
        log.append(AuditEvent("orchestrate.plan", orchestrator, f"{len(steps)} steps"))

        # --- 2) dispatch each step to its worker (automatic) ---
        for i, step in enumerate(steps[:max_workers]):
            stage, task = step["agent"], step["task"]
            yield LogLine("sys", f"▶ 工程 {i + 1}/{min(len(steps), max_workers)}: {stage} — {task}")
            system = compose_system(stage, agents_store.skills_for(stage))
            halted = False
            async for line in self._loop.run(
                task, agent_name=stage, system=system, max_iterations=per_worker_iters
            ):
                if line.t == "halt":
                    halted = True
                yield LogLine(line.t, f"[{stage}] {line.s}")
            if halted:
                yield LogLine("halt", f"工程 {stage} が承認待ちで停止。オーケストレーションを止めます。")
                log.append(AuditEvent("orchestrate.halt", stage, task))
                return

        yield LogLine("ok", "オーケストレーション完了 ✓")
        log.append(AuditEvent("orchestrate.done", "human", goal))


_runner: OrchestratorRunner | None = None


def get_orchestrator() -> OrchestratorRunner:
    global _runner
    if _runner is None:
        _runner = OrchestratorRunner()
    return _runner
