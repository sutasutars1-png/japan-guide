"""Company Memory (§7) — AI会社の「記憶」。

経営判断・仮説・実験・成果・失敗・成功・顧客反応・改善・成功/失敗パターンを
時系列ログに積み、「前に何を試した?」に答えられる状態を作る (§7)。
"""

from __future__ import annotations

from typing import Any, Optional

from . import ids
from .storage import Storage

# §7 の保存対象を種別 (kind) として列挙。
KINDS = {
    "decision",  # 経営判断
    "hypothesis",  # 仮説
    "experiment",  # 実験
    "result",  # 成果
    "failure",  # 失敗
    "success",  # 成功
    "customer",  # 顧客反応
    "improvement",  # 改善内容
    "product",  # 商品データ
    "research",  # 市場調査
    "competitor",  # 競合調査
    "review",  # レビュー結果
    "kpi",  # KPI
    "pattern_success",  # 成功パターン
    "pattern_failure",  # 失敗パターン
    "note",  # その他メモ
}


class CompanyMemory:
    def __init__(self, storage: Storage):
        self.storage = storage

    def add(
        self,
        kind: str,
        title: str,
        body: str = "",
        *,
        tags: Optional[list[str]] = None,
        related: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        entry = {
            "id": ids.new_id("mem"),
            "kind": kind,
            "title": title,
            "body": body,
            "tags": tags or [],
            "related": related or [],
            "created_at": ids.now_iso(),
        }
        return self.storage.append("memory", entry)

    def all(self) -> list[dict[str, Any]]:
        return list(self.storage.read_log("memory"))

    def recent(self, n: int = 20, kind: str | None = None) -> list[dict[str, Any]]:
        rows = self.all()
        if kind:
            rows = [r for r in rows if r.get("kind") == kind]
        return rows[-n:][::-1]

    def query(
        self,
        *,
        text: str | None = None,
        kind: str | None = None,
        tag: str | None = None,
    ) -> list[dict[str, Any]]:
        """「前に何を試した?」系の検索 (§7)。全文は単純な部分一致。"""
        out = []
        for r in self.all():
            if kind and r.get("kind") != kind:
                continue
            if tag and tag not in r.get("tags", []):
                continue
            if text:
                hay = (r.get("title", "") + " " + r.get("body", "")).lower()
                if text.lower() not in hay:
                    continue
            out.append(r)
        return out[::-1]  # 新しい順

    # ---- パターン抽出の入り口 (§6, §31) ----------------------------------

    def patterns(self, success: bool = True) -> list[dict[str, Any]]:
        kind = "pattern_success" if success else "pattern_failure"
        return [r for r in self.all() if r.get("kind") == kind]
