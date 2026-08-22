"""記事品質の決定論チェック (付録A #4, #5, §31)。

LLM 生成の記事に対して、コードで検査できる品質基準を持つ:

* **体裁チェック** (C): プレースホルダ残り・見出し欠落・空リンク・雛形残り。
* **価格連動要件** (A): 価格帯ごとに必要な分量・具体例・チェックリストを要求。

いずれも「reject の根拠」を日本語で返し、自動再執筆(§4)の feedback に使う。
標準ライブラリのみ。
"""

from __future__ import annotations

import re
from typing import Any

# 価格帯 → 必要要件。cap 以下の最初の段に該当。
_PRICE_TIERS: list[tuple[int, dict[str, Any]]] = [
    (100, {"label": "入門(〜100円)", "min_chars": 700, "min_lists": 1,
           "min_examples": 1, "needs_checklist": False}),
    (300, {"label": "基本(〜300円)", "min_chars": 1500, "min_lists": 1,
           "min_examples": 2, "needs_checklist": False}),
    (1000, {"label": "実践(〜1000円)", "min_chars": 3000, "min_lists": 2,
            "min_examples": 3, "needs_checklist": True}),
    (3000, {"label": "上級(〜3000円)", "min_chars": 6000, "min_lists": 3,
            "min_examples": 4, "needs_checklist": True}),
]
_TOP_TIER = {"label": "プレミアム(3000円超)", "min_chars": 9000, "min_lists": 4,
             "min_examples": 5, "needs_checklist": True}


def price_tier_spec(price: int) -> dict[str, Any]:
    for cap, spec in _PRICE_TIERS:
        if price <= cap:
            return spec
    return _TOP_TIER


def price_requirement_text(price: int) -> str:
    """執筆 LLM に渡す、価格に見合う中身の要件（自然文）。"""
    s = price_tier_spec(price)
    parts = [
        f"価格帯は{s['label']}",
        f"本文は概ね{s['min_chars']}文字以上",
        f"箇条書き/手順リストを{s['min_lists']}個以上",
        f"具体例を{s['min_examples']}件以上入れる",
    ]
    if s["needs_checklist"]:
        parts.append("チェックリストかテンプレート/ワークシートを1つ以上含める")
    return "。".join(parts) + "。価格に見合う密度・具体性・実用性を担保する。"


def format_issues(article: dict) -> list[str]:
    """体裁の崩れ・未完成を検出（C）。"""
    body = str(article.get("body_markdown", ""))
    issues: list[str] = []
    if not body.strip():
        return ["本文が空です。"]
    if "TemplateRunner" in body:
        issues.append("雛形テキストが残っています。")
    if re.search(r"\[[^\]]*(記入|入力|ここに|○○|●●|XX|TODO|未定|プレースホルダ)[^\]]*\]", body) \
            or "[]" in body:
        issues.append("プレースホルダ（[ ]）が残っています。")
    if not re.search(r"(?m)^#{1,6}\s+\S", body):
        issues.append("見出し（#）がありません。")
    if re.search(r"\[[^\]]*\]\(\s*\)", body):
        issues.append("空のリンクがあります。")
    return issues


def _count_examples(body: str) -> int:
    return len(re.findall(r"例え?ば|具体例|ケース|事例|たとえば", body))


def tier_issues(article: dict, price: int) -> list[str]:
    """価格帯に対する中身の不足を検出（A）。"""
    s = price_tier_spec(price)
    body = str(article.get("body_markdown", ""))
    issues: list[str] = []
    n = len(body)
    if n < s["min_chars"]:
        issues.append(
            f"本文が価格({s['label']})に対して短い（{n}字 < 目安{s['min_chars']}字）。"
            "事例・手順・背景を増やす。")
    lists = len(re.findall(r"(?m)^\s*([-*・]|\d+[.)])\s+\S", body))
    if lists < s["min_lists"]:
        issues.append(f"箇条書き/手順が不足（{lists}個 < 必要{s['min_lists']}個）。")
    if _count_examples(body) < s["min_examples"]:
        issues.append(f"具体例が不足（必要{s['min_examples']}件以上）。")
    if s["needs_checklist"] and not re.search(
            r"チェック|テンプレ|ワークシート|□|- \[ \]", body):
        issues.append("この価格帯はチェックリスト/テンプレート/ワークシートが必要。")
    return issues


def quality_issues(article: dict, price: int) -> list[str]:
    """体裁(C) + 価格連動(A) をまとめて返す。空なら合格。"""
    return format_issues(article) + tier_issues(article, price)
