"""Orchestrator (Phase 4) — goal → 統括AI plans → workers auto-dispatch.

    ユーザーのゴール
       ↓
    統括AI（既定=Planner）… ゴールを分解して各ワーカーへ割当     ← 1回だけ
       ↓ 構造化された計画を解析して自動ディスパッチ
    Builder / Researcher / Reviewer …（各自のプロバイダで実行）  ← 全自動

This module now also does:
- **Report chaining** — each worker's DONE report is fed into the next step's
  context, so工程が繋がって成果物が積み上がる.
- **Re-plan loop** — if a worker fails to produce a result, the orchestrator is
  consulted again (bounded) for a revised remaining plan, instead of aborting.
- **Plan-first** — `make_plan()` returns the parsed plan so the UI can show an
  editable checklist; `run(..., steps=<edited>)` dispatches a pre-approved plan.

An L3/L4 approval halt still stops the run (a human decision, never re-planned).
Blocked commands never run — worker safety carries over from the agent loop.
"""
from __future__ import annotations

import re
from typing import AsyncIterator

from . import agents_store, deliverables
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


def _format_spec(names: list[str]) -> str:
    joined = " / ".join(names)
    return (
        "# 出力フォーマット（厳守）\n"
        "各行を「<エージェント名>: <その工程への具体的な指示>」の形式で、実行する順に"
        f"並べてください（エージェント名は {joined} のいずれか）。\n"
        "最後の行に「DONE」とだけ書いてください。前置き・説明・箇条書き記号は書かない。"
    )


def _roster_block(workers: list[dict]) -> str:
    lines = ["# 使えるエージェント"]
    for a in workers:
        role = (a.get("role") or "").strip().replace("\n", " ")
        lines.append(f"- {a['name']}: {role}")
    return "\n".join(lines)


def compose_orchestration_prompt(goal: str, workers: list[dict]) -> str:
    names = [a["name"] for a in workers]
    return (
        f"{_roster_block(workers)}\n\n{_format_spec(names)}\n\n"
        f"# ユーザーのゴール\n{goal}"
    )


def compose_replan_prompt(
    goal: str, workers: list[dict], done: list[tuple[str, str]],
    remaining: list[dict], reason: str,
) -> str:
    names = [a["name"] for a in workers]
    done_txt = "\n".join(f"- {a}: 完了" for a, _ in done) or "（なし）"
    rem_txt = "\n".join(f"- {s['agent']}: {s['task']}" for s in remaining) or "（なし）"
    return (
        f"{_roster_block(workers)}\n\n{_format_spec(names)}\n\n"
        "# 状況\n"
        f"ゴール: {goal}\n"
        f"完了した工程:\n{done_txt}\n"
        f"発生した問題: {reason}\n"
        f"元の残り工程:\n{rem_txt}\n\n"
        "この問題を踏まえ、ゴール達成のための『残りの工程』だけを更新して出力してください。"
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


def _with_context(task: str, reports: list[tuple[str, str]], goal: str) -> str:
    """Report chaining: prepend the last few workers' outputs to the next task."""
    if not reports:
        return task
    ctx = "\n\n".join(f"【{a} の成果】\n{r}" for a, r in reports[-3:])
    return f"これまでの成果:\n{ctx}\n\n今回のタスク: {task}\n\n元のゴール: {goal}"


class OrchestratorRunner:
    def __init__(self, loop: AgentLoop | None = None, provider=None) -> None:
        self._loop = loop or get_agent_loop()   # runs the workers
        self._provider = provider                # orchestrator provider (None = resolve)

    def _orch(self, orchestrator: str):
        orch = agents_store.get_by_name(orchestrator)
        model = (orch or {}).get("model") or settings.llm_model
        provider = self._provider or get_provider_for_model(model)
        return provider, model

    async def _ask(self, orchestrator: str, prompt: str) -> str:
        provider, model = self._orch(orchestrator)
        resp = await provider.complete(
            [LLMMessage(role="system", content=ORCH_SYSTEM),
             LLMMessage(role="user", content=prompt)],
            model=model, max_tokens=1024,
        )
        return (resp.text or "").strip()

    def _persist(self, goal, orchestrator, artifacts, status) -> LogLine | None:
        """Save the run's accumulated artifacts as a downloadable deliverable."""
        if not artifacts:
            return None
        try:
            item = deliverables.save(
                goal=goal, artifacts=artifacts, source="orchestrate",
                orchestrator=orchestrator, status=status,
            )
        except Exception as exc:  # noqa: BLE001 — persistence never breaks a run
            return LogLine("warn", f"成果物の保存に失敗しました: {exc}")
        log.append(AuditEvent("orchestrate.deliverable", orchestrator, item["id"]))
        return LogLine(
            "ok",
            f"📦 成果物を保存しました · {item['id']} · {len(artifacts)} 件 · Deliverables からダウンロードできます",
        )

    async def make_plan(self, goal: str, orchestrator: str = "Planner") -> dict:
        """Ask the orchestrator for a plan and return {text, plan}. Plan-first UI."""
        workers = worker_roster(orchestrator)
        text = await self._ask(orchestrator, compose_orchestration_prompt(goal, workers))
        return {"text": text, "plan": parse_plan(text, [w["name"] for w in workers])}

    async def run(
        self,
        goal: str,
        *,
        orchestrator: str = "Planner",
        steps: list[dict] | None = None,
        per_worker_iters: int = 6,
        max_workers: int = 12,
        max_replans: int = 2,
    ) -> AsyncIterator[LogLine]:
        yield LogLine("sys", f"統括AI『{orchestrator}』にゴールを渡します · {goal}")
        log.append(AuditEvent("orchestrate.start", "human", goal))

        workers = worker_roster(orchestrator)
        if not workers:
            yield LogLine("warn", "ディスパッチ先のワーカーがいません。")
            return
        worker_names = [w["name"] for w in workers]

        # --- 1) get a plan (skip if the UI pre-approved one) ---
        if steps is None:
            _, model = self._orch(orchestrator)
            yield LogLine("sys", f"統括AI 思考中… · model {model}")
            try:
                planned = await self.make_plan(goal, orchestrator)
            except Exception as exc:  # noqa: BLE001
                yield LogLine("err", f"統括AIエラー: {type(exc).__name__}: {exc}")
                return
            for ln in planned["text"].splitlines():
                yield LogLine("out", f"[統括] {ln}")
            steps = planned["plan"]
        if not steps:
            yield LogLine("warn", "計画を解析できませんでした（割当行が見つかりません）。")
            return
        yield LogLine("ok", f"計画を受領 · {len(steps)} 工程を自動実行します")
        log.append(AuditEvent("orchestrate.plan", orchestrator, f"{len(steps)} steps"))

        # --- 2) dispatch, chaining reports; re-plan on failure ---
        reports: list[tuple[str, str]] = []
        artifacts: list[dict] = []  # accumulated deliverable (agent/task/content)
        queue = list(steps)
        replans = 0
        runs = 0
        while queue and runs < max_workers:
            step = queue.pop(0)
            stage, task = step["agent"], step["task"]
            if stage not in worker_names:
                continue
            runs += 1
            yield LogLine("sys", f"▶ 工程 {runs}: {stage} — {task}")

            worker_goal = _with_context(task, reports, goal)
            system = compose_system(stage, agents_store.skills_for(stage))
            report_lines: list[str] = []
            capturing = halted = False
            async for line in self._loop.run(
                worker_goal, agent_name=stage, system=system, max_iterations=per_worker_iters
            ):
                if line.t == "ok" and line.s == "agent finished ✓":
                    capturing = True
                elif capturing and line.t == "out":
                    report_lines.append(line.s)
                if line.t == "halt":
                    halted = True
                yield LogLine(line.t, f"[{stage}] {line.s}")

            if halted:  # L3/L4 approval — a human decision, never re-planned
                yield LogLine("halt", f"工程 {stage} が承認待ちで停止。オーケストレーションを止めます。")
                log.append(AuditEvent("orchestrate.halt", stage, task))
                saved = self._persist(goal, orchestrator, artifacts, "partial")
                if saved:
                    yield saved
                return

            # Success is "the agent emitted a DONE report" — `report` is non-empty
            # only on the loop's DONE path. A non-zero shell exit mid-exploration
            # (an `err` line like `exited 1`) is normal and must NOT discard a
            # valid report; that false-positive used to trigger needless re-plans
            # and throw away the deliverable.
            report = "\n".join(report_lines).strip()
            if report:
                reports.append((stage, report))
                artifacts.append({"agent": stage, "task": task, "content": report})
                continue

            # failure → ask the orchestrator to re-plan the remainder (bounded)
            if replans >= max_replans:
                yield LogLine("warn", f"再計画の上限（{max_replans}）に達したため停止します。")
                log.append(AuditEvent("orchestrate.replan_limit", orchestrator, stage))
                saved = self._persist(goal, orchestrator, artifacts, "partial")
                if saved:
                    yield saved
                return
            replans += 1
            yield LogLine("warn", f"工程 {stage} が成果を出せませんでした。統括に再計画を依頼します（{replans}/{max_replans}）")
            try:
                revised = await self._ask(
                    orchestrator,
                    compose_replan_prompt(goal, workers, reports, queue, f"工程 {stage} が失敗"),
                )
            except Exception as exc:  # noqa: BLE001
                yield LogLine("err", f"再計画エラー: {exc}")
                return
            for ln in revised.splitlines():
                yield LogLine("out", f"[統括·再計画] {ln}")
            new_steps = parse_plan(revised, worker_names)
            if not new_steps:
                yield LogLine("warn", "再計画を解析できませんでした。停止します。")
                saved = self._persist(goal, orchestrator, artifacts, "partial")
                if saved:
                    yield saved
                return
            queue = new_steps  # replace the remaining plan with the revision
            log.append(AuditEvent("orchestrate.replan", orchestrator, f"{len(new_steps)} steps"))

        partial = bool(queue)
        if partial:
            yield LogLine("warn", f"最大工程数（{max_workers}）に達したため停止しました。")
        saved = self._persist(goal, orchestrator, artifacts, "partial" if partial else "complete")
        if saved:
            yield saved
        yield LogLine("ok", "オーケストレーション完了 ✓")
        log.append(AuditEvent("orchestrate.done", "human", goal))


_runner: OrchestratorRunner | None = None


def get_orchestrator() -> OrchestratorRunner:
    global _runner
    if _runner is None:
        _runner = OrchestratorRunner()
    return _runner
