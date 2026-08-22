"""Cost Controller (§36, §37, 付録A #3)。

Pro サブスク範囲内で回すため、実費(円)ではなく相対的な **コストユニット**
で管理する。Tier 1/2/3 に重みを与え、1日あたりのタスク数に上限を設ける。

将来 API 課金モデルを混ぜる場合も、この層に単価表を足すだけで済む。
"""

from __future__ import annotations

import datetime as _dt

from .config import Config
from .storage import Storage

# Tier ごとの相対コスト重み (高性能ほど高い)。
TIER_COST_UNITS: dict[int, float] = {1: 1.0, 2: 4.0, 3: 12.0}


class BudgetExceeded(RuntimeError):
    """1日のタスク上限を超えた場合に送出。"""


class CostController:
    def __init__(self, storage: Storage, config: Config):
        self.storage = storage
        self.config = config

    # ---- 記録 -------------------------------------------------------------

    def record(self, *, task_id: str, agent: str, tier: int, task_type: str) -> float:
        units = TIER_COST_UNITS.get(tier, 4.0)
        self.storage.append(
            "metrics",
            {
                "ts": _now(),
                "name": "task_cost",
                "value": units,
                "task_id": task_id,
                "agent": agent,
                "tier": tier,
                "task_type": task_type,
            },
        )
        return units

    # ---- スループット制御 (付録A #3) -------------------------------------

    def tasks_today(self) -> int:
        today = _dt.date.today().isoformat()
        return sum(
            1
            for m in self.storage.read_log("metrics")
            if m.get("name") == "task_cost" and str(m.get("ts", "")).startswith(today)
        )

    def check_daily_budget(self) -> None:
        # 0 以下は「無制限」（テスト用）。既定は上限あり (§36 Pro範囲保護)。
        if self.config.max_tasks_per_day <= 0:
            return
        if self.tasks_today() >= self.config.max_tasks_per_day:
            raise BudgetExceeded(
                f"本日のタスク上限 {self.config.max_tasks_per_day} 件に到達しました"
                " (§36 Pro範囲保護)。翌日に持ち越すか上限を見直してください。"
            )

    # ---- 集計 (§25 コスト, 付録A KPI強化案) ------------------------------

    def total_units(self) -> float:
        return sum(
            float(m.get("value", 0))
            for m in self.storage.read_log("metrics")
            if m.get("name") == "task_cost"
        )

    def units_by_agent(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for m in self.storage.read_log("metrics"):
            if m.get("name") == "task_cost":
                out[m.get("agent", "?")] = out.get(m.get("agent", "?"), 0.0) + float(
                    m.get("value", 0)
                )
        return out

    def units_by_tier(self) -> dict[int, float]:
        out: dict[int, float] = {}
        for m in self.storage.read_log("metrics"):
            if m.get("name") == "task_cost":
                t = int(m.get("tier", 2))
                out[t] = out.get(t, 0.0) + float(m.get("value", 0))
        return out


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()
