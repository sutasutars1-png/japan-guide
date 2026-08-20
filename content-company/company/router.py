"""Model Router (§15) — タスクごとに最適なモデル Tier を選ぶ。

「高性能モデルは必要な場所だけ使う」(§14) を機械的に強制するためのもの。
実際にどの物理モデルを割り当てるかは実行環境 (Claude Code / ai-os) 側の
責務で、ここは **Tier (1=軽量 / 2=通常 / 3=高性能)** の判定だけを行う。

§15 の分岐を素直に写している:

    簡単?  --YES--> Tier 1 (軽量)
      |NO
    重要?  --NO---> Tier 2 (通常)
      |YES
    ------------->  Tier 3 (高性能)
"""

from __future__ import annotations

import dataclasses

# タスク種別ごとの既定難易度・重要度・予算 (§37 の予算レベル表を反映)。
# difficulty / importance は 1〜3。
TASK_PROFILE: dict[str, dict[str, object]] = {
    "classify": {"difficulty": 1, "importance": 1, "budget": "LOW"},
    "tagging": {"difficulty": 1, "importance": 1, "budget": "LOW"},
    "summarize": {"difficulty": 1, "importance": 1, "budget": "LOW"},
    "dedupe": {"difficulty": 1, "importance": 2, "budget": "LOW"},
    "research": {"difficulty": 2, "importance": 2, "budget": "LOW"},
    "market_analysis": {"difficulty": 3, "importance": 3, "budget": "HIGH"},
    "article_outline": {"difficulty": 2, "importance": 2, "budget": "MEDIUM"},
    "article_write": {"difficulty": 2, "importance": 2, "budget": "MEDIUM"},
    "sns_post": {"difficulty": 2, "importance": 2, "budget": "MEDIUM"},
    "product_desc": {"difficulty": 2, "importance": 2, "budget": "MEDIUM"},
    "product_plan": {"difficulty": 3, "importance": 3, "budget": "HIGH"},
    "review_final": {"difficulty": 3, "importance": 3, "budget": "HIGH"},
    "ceo_decision": {"difficulty": 3, "importance": 3, "budget": "HIGH"},
    "growth_strategy": {"difficulty": 3, "importance": 3, "budget": "HIGH"},
}


@dataclasses.dataclass
class Routed:
    tier: int
    budget_level: str
    rationale: str


class ModelRouter:
    def __init__(self, profiles: dict | None = None):
        self.profiles = profiles or TASK_PROFILE

    def profile(self, task_type: str) -> dict[str, object]:
        return self.profiles.get(
            task_type, {"difficulty": 2, "importance": 2, "budget": "MEDIUM"}
        )

    def route(
        self,
        task_type: str,
        *,
        difficulty: int | None = None,
        importance: int | None = None,
    ) -> Routed:
        prof = self.profile(task_type)
        d = difficulty if difficulty is not None else int(prof["difficulty"])  # type: ignore[arg-type]
        i = importance if importance is not None else int(prof["importance"])  # type: ignore[arg-type]

        # §15 の分岐
        if d <= 1:
            tier, why = 1, "簡単なタスク → 軽量モデル"
        elif i <= 2:
            tier, why = 2, "難しいが重要度は中 → 通常モデル"
        else:
            tier, why = 3, "難しく かつ 重要 → 高性能モデル"

        budget = {1: "LOW", 2: "MEDIUM", 3: "HIGH"}[tier]
        return Routed(
            tier=tier,
            budget_level=budget,
            rationale=f"{why} (difficulty={d}, importance={i})",
        )
