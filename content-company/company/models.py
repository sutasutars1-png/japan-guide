"""ドメインモデル (§8 商品, §9 仮説・実験, §18 タスク, 他)。

dataclass をそのまま JSON に落とすため、値は JSON 化できる型だけを持つ。
"""

from __future__ import annotations

import dataclasses
from typing import Any, Optional

from . import ids


def _asdict(obj: Any) -> dict[str, Any]:
    return dataclasses.asdict(obj)


# ---- 商品 (§8) ------------------------------------------------------------


@dataclasses.dataclass
class Product:
    id: str = ""
    title: str = ""
    theme: str = ""
    category: str = ""  # 実験カテゴリー (A〜E)
    target: str = ""
    price_jpy: int = 100
    status: str = "draft"  # draft→writing→review→awaiting_approval→published→retired
    created_at: str = ""
    published_at: Optional[str] = None
    url: Optional[str] = None
    hypothesis_id: Optional[str] = None
    experiment_round: int = 0
    # 実績 (公開後に Analytics が更新)
    pv: int = 0
    likes: int = 0
    purchases: int = 0
    revenue_jpy: int = 0
    rating: Optional[float] = None
    source_breakdown: dict[str, int] = dataclasses.field(default_factory=dict)
    ai_cost_units: float = 0.0  # 1商品あたりの AIコスト (付録A KPI強化案)
    result: str = ""  # 実験結果メモ
    outcome: Optional[str] = None  # "success" / "fail" / None(未評価)
    improvement: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = ids.new_id("prod")
        if not self.created_at:
            self.created_at = ids.now_iso()

    @property
    def conversion_rate(self) -> float:
        return (self.purchases / self.pv) if self.pv else 0.0

    def to_dict(self) -> dict[str, Any]:
        d = _asdict(self)
        d["conversion_rate"] = round(self.conversion_rate, 4)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Product":
        return cls(**{k: v for k, v in d.items() if k in _field_names(cls)})


# ---- 仮説・実験 (§9) ------------------------------------------------------


@dataclasses.dataclass
class Hypothesis:
    id: str = ""
    statement: str = ""  # 仮説
    rationale: str = ""  # 根拠
    action: str = ""  # 実施内容
    kpi: str = ""  # 判定する KPI
    category: str = ""
    round: int = 0
    product_ids: list[str] = dataclasses.field(default_factory=list)
    outcome: Optional[str] = None  # success / fail / None
    cause: str = ""  # 原因
    learning: str = ""  # 次回への学習
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = ids.new_id("hyp")
        if not self.created_at:
            self.created_at = ids.now_iso()

    def to_dict(self) -> dict[str, Any]:
        return _asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Hypothesis":
        return cls(**{k: v for k, v in d.items() if k in _field_names(cls)})


# ---- タスク (§18) ---------------------------------------------------------


@dataclasses.dataclass
class Task:
    id: str = ""
    title: str = ""
    agent: str = ""  # 担当 Agent
    skill: str = ""  # 使用 Skill
    budget_level: str = "MEDIUM"  # LOW / MEDIUM / HIGH (§37)
    status: str = "todo"  # todo→doing→review→done / blocked
    input: dict[str, Any] = dataclasses.field(default_factory=dict)
    output: dict[str, Any] = dataclasses.field(default_factory=dict)
    review_status: Optional[str] = None  # None / pass / reject
    review_notes: str = ""
    model_tier: Optional[int] = None
    est_cost_units: float = 0.0
    parent_id: Optional[str] = None
    depends_on: list[str] = dataclasses.field(default_factory=list)
    created_at: str = ""
    completed_at: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.id:
            self.id = ids.new_id("task")
        if not self.created_at:
            self.created_at = ids.now_iso()

    def to_dict(self) -> dict[str, Any]:
        return _asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Task":
        return cls(**{k: v for k, v in d.items() if k in _field_names(cls)})


# ---- 意思決定ログ (§44-11 判断根拠の保存) --------------------------------


@dataclasses.dataclass
class Decision:
    id: str = ""
    actor: str = "CEO"  # 判断した Agent
    context: str = ""
    options: list[str] = dataclasses.field(default_factory=list)
    decision: str = ""
    rationale: str = ""  # 判断根拠 (§44)
    related: list[str] = dataclasses.field(default_factory=list)
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = ids.new_id("dec")
        if not self.created_at:
            self.created_at = ids.now_iso()

    def to_dict(self) -> dict[str, Any]:
        return _asdict(self)


# ---- 承認 (§21) -----------------------------------------------------------


@dataclasses.dataclass
class Approval:
    id: str = ""
    kind: str = ""  # publish / sns_post / delete / api_key / payment ...
    summary: str = ""
    payload: dict[str, Any] = dataclasses.field(default_factory=dict)
    status: str = "pending"  # pending / approved / rejected
    requested_by: str = ""
    created_at: str = ""
    decided_at: Optional[str] = None
    decided_by: Optional[str] = None
    note: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = ids.new_id("apr")
        if not self.created_at:
            self.created_at = ids.now_iso()

    def to_dict(self) -> dict[str, Any]:
        return _asdict(self)


def _field_names(cls: Any) -> set[str]:
    return {f.name for f in dataclasses.fields(cls)}
