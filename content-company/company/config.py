"""会社 OS の設定。

数値方針 (公開ペース上限・撤退基準・1日タスク上限など) は付録A レビュー所見で
「数値化を推奨」とされた項目。ここに集約し、``company.json`` で上書きできる。
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
from typing import Any

# ---- パッケージ既定のパス -------------------------------------------------

PACKAGE_ROOT = pathlib.Path(__file__).resolve().parent.parent  # content-company/
DEFAULT_DATA_DIR = PACKAGE_ROOT / "data"


@dataclasses.dataclass
class Config:
    """会社全体の運用パラメータ。"""

    # データ保存先 (§26)
    data_dir: pathlib.Path = DEFAULT_DATA_DIR

    # 初期実験の設計 (§10, §11)
    categories: int = 5
    products_per_category: int = 4
    round_size: int = 5  # 1ラウンドあたりの新規商品数 (§11)

    # 価格階層 (§12)。初期は100円。
    initial_price_jpy: int = 100
    price_ladder_jpy: tuple[int, ...] = (0, 100, 300, 500, 1000, 3000)

    # コスト / スループット制御 (§36, §37, 付録A #3)
    max_tasks_per_day: int = 40
    # 予算レベル → 想定モデル Tier (§14, §37)
    budget_tier: dict[str, int] = dataclasses.field(
        default_factory=lambda: {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
    )

    # プラットフォーム保護 (§22, 付録A #1)。公開ペースの上限。
    max_publishes_per_day: int = 2

    # 自動再執筆 (§4 の差し戻し→Writer)。Reviewer が reject したとき、指摘を
    # 反映して書き直す最大回数。0 で自動再執筆オフ。実 LLM 生成時のみ作動する。
    max_rewrites: int = 3

    # 実験の撤退基準 (付録A 任意強化案)。
    # 「Nラウンド連続で購入0のカテゴリは打ち切り」
    retreat_zero_purchase_rounds: int = 2

    # MVP 成功条件の定量目標 (付録A 任意強化案 §39)
    target_conversion_rate: float = 0.03  # 目標購入率 3%
    breakeven_product_count: int = 20

    def tier_for_budget(self, budget_level: str) -> int:
        return self.budget_tier.get(budget_level.upper(), 2)

    # ---- 読み書き ---------------------------------------------------------

    @classmethod
    def load(cls, path: pathlib.Path | str | None = None) -> "Config":
        cfg = cls()
        if path is None:
            path = PACKAGE_ROOT / "company.json"
        path = pathlib.Path(path)
        if path.exists():
            raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
            for key, value in raw.items():
                if not hasattr(cfg, key):
                    continue
                if key == "data_dir":
                    value = pathlib.Path(value)
                setattr(cfg, key, value)
        return cfg


def load_config(path: pathlib.Path | str | None = None) -> Config:
    return Config.load(path)
