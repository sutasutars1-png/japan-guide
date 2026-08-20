"""KPI 集計 (§25 ダッシュボード, §39 MVP成功条件, §44-15)。

『記事数』ではなく『利益・学習・再現性』を KPI にする (§44-15)。
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from .config import Config
from .cost import CostController
from .storage import Storage


class KPI:
    def __init__(self, storage: Storage, config: Config, cost: CostController | None = None):
        self.storage = storage
        self.config = config
        self.cost = cost

    def products(self) -> list[dict[str, Any]]:
        return self.storage.all("products")

    # ---- 経営 KPI (§25) --------------------------------------------------

    def summary(self) -> dict[str, Any]:
        products = self.products()
        published = [p for p in products if p.get("status") == "published"]
        total_pv = sum(int(p.get("pv", 0)) for p in products)
        total_purchases = sum(int(p.get("purchases", 0)) for p in products)
        total_revenue = sum(int(p.get("revenue_jpy", 0)) for p in products)
        month = _dt.date.today().strftime("%Y-%m")
        month_revenue = sum(
            int(p.get("revenue_jpy", 0))
            for p in products
            if str(p.get("published_at") or "").startswith(month)
        )
        conv = (total_purchases / total_pv) if total_pv else 0.0
        out = {
            "total_revenue_jpy": total_revenue,
            "month_revenue_jpy": month_revenue,
            "product_count": len(products),
            "published_count": len(published),
            "purchases": total_purchases,
            "pv": total_pv,
            "conversion_rate": round(conv, 4),
            "target_conversion_rate": self.config.target_conversion_rate,
            "conversion_target_met": conv >= self.config.target_conversion_rate,
            "breakeven_product_count": self.config.breakeven_product_count,
        }
        if self.cost is not None:
            units = self.cost.total_units()
            out["ai_cost_units"] = round(units, 2)
            # 1商品あたりの AIコスト (付録A KPI強化案)
            out["ai_cost_per_product"] = (
                round(units / len(products), 2) if products else 0.0
            )
        return out

    # ---- 商品ランキング (§25) --------------------------------------------

    def ranking(self, by: str = "revenue_jpy", limit: int = 10) -> list[dict[str, Any]]:
        key_map = {
            "revenue": "revenue_jpy",
            "revenue_jpy": "revenue_jpy",
            "pv": "pv",
            "purchases": "purchases",
        }
        field = key_map.get(by, "revenue_jpy")

        def sort_key(p: dict[str, Any]) -> float:
            if by in ("conversion", "conversion_rate"):
                return float(p.get("conversion_rate", 0))
            return float(p.get(field, 0))

        rows = sorted(self.products(), key=sort_key, reverse=True)
        return rows[:limit]

    # ---- 分析パターン (§4 Data Analyst の重要分析) ----------------------

    def patterns(self) -> dict[str, list[dict[str, Any]]]:
        """PV高だが売れない / PV低いが購入率高い 等を抽出。"""
        products = [p for p in self.products() if int(p.get("pv", 0)) > 0]
        if not products:
            return {"high_pv_low_conv": [], "low_pv_high_conv": [], "winners": []}
        pvs = sorted(int(p.get("pv", 0)) for p in products)
        convs = sorted(float(p.get("conversion_rate", 0)) for p in products)
        pv_med = pvs[len(pvs) // 2]
        conv_med = convs[len(convs) // 2]

        def label(p: dict[str, Any]) -> dict[str, Any]:
            return {
                "id": p.get("id"),
                "title": p.get("title"),
                "pv": p.get("pv"),
                "conversion_rate": p.get("conversion_rate"),
            }

        high_pv_low = [
            label(p)
            for p in products
            if int(p.get("pv", 0)) >= pv_med
            and float(p.get("conversion_rate", 0)) < conv_med
        ]
        low_pv_high = [
            label(p)
            for p in products
            if int(p.get("pv", 0)) < pv_med
            and float(p.get("conversion_rate", 0)) >= conv_med
        ]
        winners = [
            label(p)
            for p in products
            if int(p.get("pv", 0)) >= pv_med
            and float(p.get("conversion_rate", 0)) >= conv_med
        ]
        return {
            "high_pv_low_conv": high_pv_low,  # タイトル/価格/ベネフィット改善
            "low_pv_high_conv": low_pv_high,  # テーマは強い → 集客増
            "winners": winners,  # 成功パターン → 横展開
        }
