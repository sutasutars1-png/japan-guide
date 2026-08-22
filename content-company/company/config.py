"""会社 OS の設定。

数値方針 (公開ペース上限・撤退基準・1日タスク上限など) は付録A レビュー所見で
「数値化を推奨」とされた項目。ここに集約し、``company.json`` で上書きできる。
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import typing
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

    # チャネル有効化 (§23 の段階導入)。既定はすべてオフ（noteのみで検証）。
    x_enabled: bool = False
    tiktok_enabled: bool = False

    # GUI から編集できる安全なフィールド（型と上限つき）。data_dir 等は含めない。
    EDITABLE_FIELDS: typing.ClassVar[dict] = {
        "initial_price_jpy": (int, 0, 1_000_000),
        "max_tasks_per_day": (int, 0, 100000),  # 0 = 無制限（テスト用）
        "max_publishes_per_day": (int, 0, 100),
        "max_rewrites": (int, 0, 5),
        "target_conversion_rate": (float, 0.0, 1.0),
        "breakeven_product_count": (int, 1, 1000),
        "retreat_zero_purchase_rounds": (int, 1, 20),
        "x_enabled": (bool, None, None),
        "tiktok_enabled": (bool, None, None),
    }

    def tier_for_budget(self, budget_level: str) -> int:
        return self.budget_tier.get(budget_level.upper(), 2)

    # ---- 読み書き ---------------------------------------------------------

    @classmethod
    def load(cls, path: pathlib.Path | str | None = None) -> "Config":
        cfg = cls()
        if path is None:
            path = PACKAGE_ROOT / "company.json"
        path = pathlib.Path(path)
        # base（company.json）→ overlay（company.local.json, git 管理外）の順で適用。
        if path.exists():
            cfg._apply(json.loads(path.read_text(encoding="utf-8")))
        # data_dir 内の GUI 編集オーバーレイを最後に重ねる。
        overlay = cfg.data_dir / "config.local.json"
        if overlay.exists():
            cfg._apply(json.loads(overlay.read_text(encoding="utf-8")))
        return cfg

    def load_overlay(self) -> None:
        """data_dir/config.local.json を（存在すれば）self に適用する。"""
        overlay = self.data_dir / "config.local.json"
        if overlay.exists():
            self._apply(json.loads(overlay.read_text(encoding="utf-8")))

    def _apply(self, raw: dict[str, Any]) -> None:
        for key, value in raw.items():
            if not hasattr(self, key) or key == "EDITABLE_FIELDS":
                continue
            if key == "data_dir":
                value = pathlib.Path(value)
            setattr(self, key, value)

    # ---- GUI からの安全な設定変更 ----------------------------------------

    def update(self, changes: dict[str, Any]) -> dict[str, Any]:
        """許可されたフィールドだけを型・範囲チェックして更新する。"""
        applied: dict[str, Any] = {}
        for key, raw in changes.items():
            spec = self.EDITABLE_FIELDS.get(key)
            if spec is None:
                continue  # 許可外は黙って無視（data_dir 等を守る）
            typ, lo, hi = spec
            try:
                if typ is bool:
                    val: Any = bool(raw) if not isinstance(raw, str) else raw.lower() in ("1", "true", "on", "yes")
                elif typ is int:
                    val = int(raw)
                else:
                    val = float(raw)
            except (TypeError, ValueError):
                continue
            if lo is not None:
                val = max(lo, min(hi, val))
            setattr(self, key, val)
            applied[key] = val
        return applied

    def persist(self) -> pathlib.Path:
        """編集可能フィールドの現在値を data_dir/config.local.json に書き出す。"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        overlay = self.data_dir / "config.local.json"
        data = {k: getattr(self, k) for k in self.EDITABLE_FIELDS}
        overlay.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return overlay

    def editable_snapshot(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.EDITABLE_FIELDS}


def load_config(path: pathlib.Path | str | None = None) -> Config:
    return Config.load(path)
