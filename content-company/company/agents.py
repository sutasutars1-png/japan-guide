"""AI会社の組織 (§4)。

各 Agent を「社員」として定義する (§3.1): 役割 / 責任 / Skill / 判断基準 /
入力 / 出力 / 禁止事項 / 成功条件。ここではレジストリ (機械可読な定義) を持ち、
人間向けの詳しい定義書は ``agents/<name>.md`` に置く。
"""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class AgentSpec:
    key: str
    name: str
    role: str
    skills: tuple[str, ...]
    default_tier: int  # このAgentが主に使うモデルTier (§14)
    can_publish: bool = False  # 単独公開の可否 (Writerは不可: §4)


# §4 + §28(MVPは5Agent) + §35(最終形)。
# MVP: CEO / Researcher / Product(CPO) / Writer / Reviewer。
# Marketing / Analytics / Growth は初期は CEO 等が兼務 (§28) だが定義は持つ。
AGENTS: dict[str, AgentSpec] = {
    "ceo": AgentSpec(
        key="ceo",
        name="CEO / 経営AI",
        role="事業方針・KPI管理・優先順位・投資判断・実験継続/停止・人間への承認依頼",
        skills=("growth-strategy",),
        default_tier=3,
    ),
    "researcher": AgentSpec(
        key="researcher",
        name="Researcher / リサーチAI",
        role="Web/SNS/note/検索需要/競合/トレンド調査。『何が売れそうか』の観点で調べる",
        skills=("market-research", "competitor-analysis", "note-analysis", "seo"),
        default_tier=2,
    ),
    "cpo": AgentSpec(
        key="cpo",
        name="CPO / 商品企画AI (Product Manager)",
        role="市場調査の分析・読者ニーズ分析・商品候補作成・価格設定・ラインナップ設計",
        skills=("product-planning",),
        default_tier=3,
    ),
    "writer": AgentSpec(
        key="writer",
        name="Writer / 編集AI",
        role="無料/有料記事・商品説明・タイトル・導入文・CTA・SNS投稿案の作成",
        skills=("article-writing", "seo"),
        default_tier=2,
        can_publish=False,  # 単独公開禁止。必ず Reviewer を通す (§4)
    ),
    "reviewer": AgentSpec(
        key="reviewer",
        name="Reviewer / 品質管理AI",
        role="誤情報/古い情報/論理破綻/誇張/価値/重複/AIっぽさ/法的・規約問題の点検",
        skills=("quality-review",),
        default_tier=3,
    ),
    "marketing": AgentSpec(
        key="marketing",
        name="Marketing AI",
        role="X/TikTok/無料記事企画・SNS→noteの導線設計・CTA改善・投稿時間分析",
        skills=("x-marketing", "tiktok-marketing"),
        default_tier=2,
    ),
    "analyst": AgentSpec(
        key="analyst",
        name="Data Analyst / 分析AI",
        role="PV/購入/売上/購入率/流入の分析、売れる/売れないパターンの抽出",
        skills=("data-analysis", "sales-analysis"),
        default_tier=2,
    ),
    "growth": AgentSpec(
        key="growth",
        name="Growth AI / 改善AI",
        role="分析結果から『次に何をすべきか』を決定 (改善/横展開/集客増)",
        skills=("growth-strategy",),
        default_tier=3,
    ),
}

# MVP で最初に起動する 5 Agent (§28)。
MVP_AGENTS = ("ceo", "researcher", "cpo", "writer", "reviewer")


def get(key: str) -> AgentSpec:
    return AGENTS[key]
