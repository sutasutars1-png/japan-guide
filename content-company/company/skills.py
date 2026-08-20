"""Agent Skill システム (§19)。

Skill は再利用可能な単位 (§44-3)。各 Skill は 8 項目を定義する:
目的 / 手順 / 判断基準 / 入力 / 出力 / 禁止事項 / 成功条件 (+ 別称)。

ここでは機械可読なレジストリを持ち、詳細な手順書は ``skills/<name>/SKILL.md``
に置く。自己改善 (§20) は直接上書きを禁止し、新バージョンとして採用する。
"""

from __future__ import annotations

import dataclasses

# §19 の想定 Skill 一覧。
SKILL_KEYS = (
    "market-research",
    "product-planning",
    "article-writing",
    "seo",
    "competitor-analysis",
    "note-analysis",
    "x-marketing",
    "tiktok-marketing",
    "data-analysis",
    "quality-review",
    "sales-analysis",
    "growth-strategy",
)


@dataclasses.dataclass(frozen=True)
class SkillSpec:
    key: str
    purpose: str  # 目的
    success: str  # 成功条件
    forbidden: tuple[str, ...] = ()  # 禁止事項
    version: int = 1


SKILLS: dict[str, SkillSpec] = {
    "market-research": SkillSpec(
        "market-research",
        "『何が売れそうか』の観点で需要・トレンド・競合を調べ、企画の根拠を作る",
        "商品企画の根拠として使える需要仮説が3件以上出る",
        ("未検証の数値を断定しない", "出典のない主張をしない"),
    ),
    "product-planning": SkillSpec(
        "product-planning",
        "調査結果から §13 の商品企画フォーマットを埋め、実験として設計する",
        "§13 の全項目が埋まり、売れる根拠と実験目的が明確",
        ("景表法上の優良誤認となる断定 (『必ず稼げる』等) をしない",),
    ),
    "article-writing": SkillSpec(
        "article-writing",
        "無料/有料記事・タイトル・導入・CTA を読者価値中心に書く",
        "無料部分で価値を示し有料部分の購入理由が明確",
        ("Reviewer を通さず公開しない (§4)", "誇張・誤情報を書かない"),
    ),
    "seo": SkillSpec(
        "seo", "検索需要に沿ったタイトル・見出し・キーワード設計", "検索意図と一致した構成になる"
    ),
    "competitor-analysis": SkillSpec(
        "competitor-analysis", "類似商品・競合の把握と差別化ポイントの抽出", "差別化ポイントが1つ以上言語化される"
    ),
    "note-analysis": SkillSpec(
        "note-analysis", "note上の売れ筋・反応の分析", "反応の良いテーマ/タイトル傾向が要約される"
    ),
    "x-marketing": SkillSpec(
        "x-marketing", "無料記事→X→noteの導線と投稿案の設計", "noteへの導線を含む投稿案が出る"
    ),
    "tiktok-marketing": SkillSpec(
        "tiktok-marketing", "売れた記事のショート動画化の台本設計", "台本と字幕案が出る"
    ),
    "data-analysis": SkillSpec(
        "data-analysis", "PV/購入/売上/流入の集計と可視化", "商品別・テーマ別の成績が数値で出る"
    ),
    "quality-review": SkillSpec(
        "quality-review",
        "§4 の観点 + 法的チェック (特商法・景表法・著作権) で品質を点検 (付録A #4)",
        "重大な問題ゼロ、または差し戻し理由が具体的",
        ("問題を見逃して公開に回さない",),
    ),
    "sales-analysis": SkillSpec(
        "sales-analysis", "販売データから成功/失敗パターンを抽出", "成功/失敗の要因仮説が言語化される"
    ),
    "growth-strategy": SkillSpec(
        "growth-strategy",
        "分析から次アクション (改善/横展開/集客/撤退) を決める",
        "次の仮説と具体アクションが決まる",
    ),
}


def get(key: str) -> SkillSpec:
    return SKILLS[key]
