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
#
# 方針: **どの価格でも「読者が1つの悩みをこの記事だけで完全に解決できる完結物」**。
# 特に 100円 は入口動線として最重要。teaser（予告・要約）で終わらせず、
# 無料部分で価値を実感 → 有料部分でその悩みを最後まで解決しきる。価格が上がるほど
# 扱う課題の広さ・具体例・テンプレ/ワークシートの厚みを増す（完結性は全段で必須）。
_PRICE_TIERS: list[tuple[int, dict[str, Any]]] = [
    (100, {"label": "入口(〜100円)", "min_chars": 1800, "min_lists": 2,
           "min_examples": 2, "needs_checklist": False}),
    (300, {"label": "基本(〜300円)", "min_chars": 2800, "min_lists": 2,
           "min_examples": 3, "needs_checklist": False}),
    (500, {"label": "しっかり(〜500円)", "min_chars": 3800, "min_lists": 3,
           "min_examples": 3, "needs_checklist": True}),
    (1000, {"label": "実践(〜1000円)", "min_chars": 5000, "min_lists": 3,
            "min_examples": 4, "needs_checklist": True}),
    (3000, {"label": "上級(〜3000円)", "min_chars": 8000, "min_lists": 4,
            "min_examples": 5, "needs_checklist": True}),
]
_TOP_TIER = {"label": "プレミアム(3000円超)", "min_chars": 12000, "min_lists": 5,
             "min_examples": 6, "needs_checklist": True}

# 未完・予告で終わっている疑いのある表現（完結性チェック用）。
_TEASER_PHRASES = ("続きは", "お楽しみに", "詳細は別記事", "詳しくは別",
                   "後日公開", "次回に続く", "また次回", "追って解説")

# 有料エリア境界（note_channel と一致）。
_PAID_MARK = "―― ここから有料 ――"


def price_tier_spec(price: int) -> dict[str, Any]:
    for cap, spec in _PRICE_TIERS:
        if price <= cap:
            return spec
    return _TOP_TIER


def price_requirement_text(price: int) -> str:
    """執筆 LLM に渡す、価格に見合う中身の要件（自然文）。完結性を最優先。"""
    s = price_tier_spec(price)
    parts = [
        f"価格帯は{s['label']}",
        "【最重要】読者が1つの具体的な悩みを、この記事だけで完全に解決できる"
        "完結した内容にする。すぐ実践できる手順と具体例を必ず入れ、"
        "『続きは別記事/次回』のような予告・要約で終わらせない",
        "無料部分で価値と信頼を実感させ、有料部分でその悩みを最後まで解決しきる",
        f"本文は概ね{s['min_chars']}文字以上",
        f"箇条書き/手順リストを{s['min_lists']}個以上",
        f"再現できる具体例を{s['min_examples']}件以上入れる",
    ]
    if s["needs_checklist"]:
        parts.append("そのまま使えるチェックリストかテンプレート/ワークシートを1つ以上含める")
    if price <= 100:
        parts.append(
            "100円は集客ファネルの入口として最重要。『安いのに、ちゃんと1つ得られた』"
            "と感じる完結した実用価値を必ず届け、次の商品への信頼をつくる")
    return "。".join(parts) + "。価格に見合う密度・具体性・実用性・完結性を担保する。"


def completeness_issues(article: dict) -> list[str]:
    """完結していない（予告・尻切れ）疑いを検出。"""
    body = str(article.get("body_markdown", ""))
    issues: list[str] = []
    for ph in _TEASER_PHRASES:
        if ph in body:
            issues.append(
                f"未完・予告の表現『{ph}』がある。この記事だけで完結させる。")
            break
    # 有料部分が実質的に存在し、薄すぎないか（境界がある場合）。
    if _PAID_MARK in body:
        paid = body.split(_PAID_MARK, 1)[1]
        if len(paid.strip()) < 300:
            issues.append("有料部分が薄い（完結していない）。核心の解決を有料側に置く。")
    return issues


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
    """体裁(C) + 価格連動(A) + 完結性 をまとめて返す。空なら合格。"""
    return format_issues(article) + tier_issues(article, price) \
        + completeness_issues(article)
