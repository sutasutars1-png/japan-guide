"""Task 管理 (§18)。

すべての AI 作業を Task として管理する。AI 同士が無秩序に会話する構造には
しない (§18)。各 Task は Router でモデル Tier を決め、CostController に計上し、
Runner で実行して成果物を保存する。
"""

from __future__ import annotations

from typing import Any

from . import ids
from .cost import CostController
from .models import Task
from .router import ModelRouter
from .runner import AgentRunner, TemplateRunner
from .storage import Storage


class TaskManager:
    def __init__(
        self,
        storage: Storage,
        router: ModelRouter,
        cost: CostController,
        runner: AgentRunner | None = None,
    ):
        self.storage = storage
        self.router = router
        self.cost = cost
        self.runner: AgentRunner = runner or TemplateRunner()

    # ---- 作成 -------------------------------------------------------------

    def create(
        self,
        title: str,
        agent: str,
        task_type: str,
        *,
        skill: str = "",
        input: dict[str, Any] | None = None,
        parent_id: str | None = None,
        depends_on: list[str] | None = None,
    ) -> Task:
        routed = self.router.route(task_type)
        task = Task(
            title=title,
            agent=agent,
            skill=skill,
            budget_level=routed.budget_level,
            model_tier=routed.tier,
            input={"task_type": task_type, **(input or {})},
            parent_id=parent_id,
            depends_on=depends_on or [],
        )
        self.storage.put("tasks", task.to_dict())
        return task

    # ---- 実行 (§18 のワークフロー) --------------------------------------

    def run(self, task_id: str) -> Task:
        raw = self.storage.get("tasks", task_id)
        if raw is None:
            raise KeyError(task_id)
        task = Task.from_dict(raw)

        self.cost.check_daily_budget()  # 付録A #3 スループット上限

        task.status = "doing"
        self.storage.put("tasks", task.to_dict())

        task_type = task.input.get("task_type", "")
        output = self.runner.run(task_type, task.input)

        units = self.cost.record(
            task_id=task.id, agent=task.agent, tier=task.model_tier or 2, task_type=task_type
        )
        task.est_cost_units = units
        task.output = output
        task.status = "review"
        self.storage.put("tasks", task.to_dict())
        return task

    # ---- レビュー / 完了 (§18: Reviewer → 承認 → 次Task) -----------------

    def review(self, task_id: str, passed: bool, notes: str = "") -> Task:
        raw = self.storage.get("tasks", task_id)
        if raw is None:
            raise KeyError(task_id)
        task = Task.from_dict(raw)
        task.review_status = "pass" if passed else "reject"
        task.review_notes = notes
        task.status = "done" if passed else "doing"
        if passed:
            task.completed_at = ids.now_iso()
        self.storage.put("tasks", task.to_dict())
        return task

    # ---- 参照 -------------------------------------------------------------

    def list(self, status: str | None = None) -> list[dict[str, Any]]:
        rows = self.storage.all("tasks")
        if status:
            rows = [r for r in rows if r.get("status") == status]
        return rows

    def get(self, task_id: str) -> Task | None:
        raw = self.storage.get("tasks", task_id)
        return Task.from_dict(raw) if raw else None
