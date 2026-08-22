"""初期20商品の実験設計 (§10, §11) と撤退基準 (付録A)。

* 5カテゴリー × 4商品 = 20 (§10)
* 一気に作らず 5商品ずつ 4ラウンド (§11)
* 各ラウンドの結果を見て次のカテゴリー配分を決める
* 撤退基準: Nラウンド連続で購入0のカテゴリーは打ち切り (付録A)
"""

from __future__ import annotations

from .config import Config
from .storage import Storage

# 既定のカテゴリー雛形 (運営者が差し替える前提の例)。
DEFAULT_CATEGORIES = {
    "A": "副業・お金",
    "B": "AI活用・効率化",
    "C": "学習・スキル",
    "D": "健康・習慣",
    "E": "人間関係・メンタル",
}


class ExperimentDesign:
    def __init__(self, storage: Storage, config: Config):
        self.storage = storage
        self.config = config

    # ---- ラウンド配分 (§11) ----------------------------------------------

    def round_allocation(self, round_no: int) -> list[str]:
        """このラウンドで作る商品のカテゴリー配分を返す。

        Round 1 は各カテゴリーを広く試し、以降は成績上位カテゴリーへ寄せる
        (§11: 成功カテゴリーを重点的に)。撤退済みカテゴリーは除外。
        """
        cats = [c for c in DEFAULT_CATEGORIES if not self.is_retreated(c)]
        size = self.config.round_size
        if round_no <= 1:
            # 均等割り当て (最大 size 個)
            return (cats * ((size // max(len(cats), 1)) + 1))[:size]
        # 2巡目以降は成績順に重み付け
        ranking = self.category_ranking()
        ordered = [c for c, _ in ranking if c in cats] or cats
        alloc: list[str] = []
        i = 0
        while len(alloc) < size and ordered:
            alloc.append(ordered[i % len(ordered)])
            i += 1
        return alloc

    def next_categories(self, n: int) -> list[str]:
        """次に作る n 商品のカテゴリーを、既存の作成数を見て分散配分する。

        - 実績（購入）が無い探索期は、**作成数が少ないカテゴリーを優先**して
          A〜E をまんべんなく回す（n=1 ずつ企画しても A に偏らない）。
        - 実績が出たら、成績上位（上位3カテゴリー）に寄せつつ、その中で
          作成数の少ないものから埋める（§11 の重点配分を維持）。
        撤退済みカテゴリーは除外。
        """
        cats = [c for c in DEFAULT_CATEGORIES if not self.is_retreated(c)] \
            or list(DEFAULT_CATEGORIES)
        counts: dict[str, int] = {c: 0 for c in cats}
        for p in self.storage.all("products"):
            c = p.get("category")
            if c in counts:
                counts[c] += 1
        ranking = self.category_ranking()
        has_sales = any(v > 0 for _, v in ranking)
        if has_sales:
            pool = [c for c, _ in ranking if c in cats][:3] or cats
        else:
            pool = cats
        alloc: list[str] = []
        for _ in range(max(n, 0)):
            best = min(pool, key=lambda c: (counts[c], pool.index(c)))
            alloc.append(best)
            counts[best] += 1
        return alloc

    # ---- カテゴリー成績 --------------------------------------------------

    def category_ranking(self) -> list[tuple[str, int]]:
        """カテゴリー別 購入数合計の降順。"""
        totals: dict[str, int] = {c: 0 for c in DEFAULT_CATEGORIES}
        for p in self.storage.all("products"):
            c = p.get("category")
            if c in totals:
                totals[c] += int(p.get("purchases", 0))
        return sorted(totals.items(), key=lambda kv: kv[1], reverse=True)

    def category_rounds_zero(self, category: str) -> int:
        """そのカテゴリーが「購入0」で終えた連続ラウンド数。"""
        by_round: dict[int, int] = {}
        for p in self.storage.all("products"):
            if p.get("category") != category:
                continue
            r = int(p.get("experiment_round", 0))
            by_round[r] = by_round.get(r, 0) + int(p.get("purchases", 0))
        # 実施済みラウンドを新しい順に見て、連続0を数える
        streak = 0
        for r in sorted(by_round, reverse=True):
            if by_round[r] == 0:
                streak += 1
            else:
                break
        return streak

    def is_retreated(self, category: str) -> bool:
        return (
            self.category_rounds_zero(category)
            >= self.config.retreat_zero_purchase_rounds
        )

    def retreated_categories(self) -> list[str]:
        return [c for c in DEFAULT_CATEGORIES if self.is_retreated(c)]

    # ---- 進捗 -------------------------------------------------------------

    def progress(self) -> dict[str, object]:
        products = self.storage.all("products")
        target = self.config.categories * self.config.products_per_category
        return {
            "target_products": target,
            "created": len(products),
            "published": sum(1 for p in products if p.get("status") == "published"),
            "category_ranking": self.category_ranking(),
            "retreated": self.retreated_categories(),
        }
