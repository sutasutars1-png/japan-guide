"""デモ用シード (説明・動作確認用のダミーデータ)。

ai-os と同じ「まず fake data で全体像を見せる」思想。実運用データとは別物で、
``DemoRunner`` は Reviewer を通過する完成本文を返す (TemplateRunner は雛形を
返して差し戻される)。これにより 承認→公開→実績→評価 の全ループを LLM 無しで
体験できる。**中身は架空のサンプルであり、実際の市場データではない。**
"""

from __future__ import annotations

import random
from typing import Any

from .company import Company
from .runner import TemplateRunner


class DemoRunner(TemplateRunner):
    """レビューを通過する完成コンテンツを返すデモ専用ランナー。"""

    def _product_plan(self, p: dict[str, Any]) -> dict[str, Any]:
        d = super()._product_plan(p)
        theme = p.get("theme", "")
        d.update({
            "target": f"{theme}を始めたい20〜30代の初心者",
            "reader_pain": f"{theme}に興味はあるが何から手をつければ良いか分からない",
            "purchase_reason": "最短の手順が1本にまとまっている",
            "problem_solved": "最初の一歩で迷って手が止まる問題",
            "free_part": f"{theme}の全体像と、つまずきやすい3つのポイント",
            "paid_part": "今日から使えるステップ別チェックリストとテンプレ",
            "competitors": "無料記事は多いが体系化された入門は少ない",
            "differentiation": "初心者の最初の30分に絞って手順化",
            "why_sells": f"{theme}は検索需要が安定し、入門ニーズが継続的にある",
            "success_probability": "中",
            "risk": "内容の薄さに注意（カテゴリ内で重複させない）",
        })
        return d

    def _article_write(self, p: dict[str, Any]) -> dict[str, Any]:
        plan = p.get("plan", {})
        title = plan.get("product_name", "無題")
        theme = plan.get("theme", "")
        body = (
            f"# {title}\n\n"
            f"{theme}を始めたいけれど、情報が多すぎて最初の一歩で止まっていませんか。\n"
            "この記事では、最初の30分でやることだけに絞って手順を示します。\n\n"
            "## まず全体像\n"
            f"{theme}は3つの段階に分けると迷いません。準備・実行・振り返りです。\n\n"
            "## つまずきやすい3点\n"
            "1. 完璧を目指して準備が長すぎる\n"
            "2. 情報を集めるだけで手を動かさない\n"
            "3. 記録を取らず改善できない\n\n"
            "―― ここから有料 ――\n\n"
            "## ステップ別チェックリスト\n"
            "- [ ] 今日のゴールを1つだけ決める\n"
            "- [ ] 15分だけ着手する\n"
            "- [ ] 終わったら1行だけ記録する\n\n"
            "## まとめ\n"
            "最初の30分の設計が続くかどうかを決めます。まず1つだけ始めましょう。\n"
        )
        return {
            "title": title,
            "outline": ["導入", "全体像", "つまずき3点", "有料: チェックリスト", "まとめ"],
            "body_markdown": body,
            "cta": "続きが役立ったらスキ・フォローで応援してください。",
        }


# デモ商品ごとの想定実績（架空）。
_DEMO_STATS = [
    dict(pv=1800, purchases=72, revenue_jpy=7200, likes=140, rating=4.6),  # winner
    dict(pv=2400, purchases=18, revenue_jpy=1800, likes=90, rating=3.9),   # 高PV低転換
    dict(pv=300, purchases=21, revenue_jpy=2100, likes=40, rating=4.7),    # 低PV高転換
    dict(pv=900, purchases=0, revenue_jpy=0, likes=8, rating=None),        # 未購入
    dict(pv=1200, purchases=36, revenue_jpy=3600, likes=70, rating=4.4),   # 好調
]


def seed_demo(company: Company | None = None) -> dict[str, Any]:
    """企画→承認→公開→実績→評価 の全ループを実行して台帳を埋める。"""
    rng = random.Random(42)
    c = company or Company(runner=DemoRunner())
    # DemoRunner に差し替え（呼び出し側が既定ランナーで来ても上書き）
    c.tasks.runner = DemoRunner()

    planned = c.plan_products(5)
    for i, r in enumerate(planned):
        if r.get("approval_id"):
            c.approvals.approve(r["approval_id"], note="デモ自動承認")
            stats = _DEMO_STATS[i % len(_DEMO_STATS)]
            url = f"https://note.com/example/n/demo{i+1}"
            c.publish(r["product_id"], url, r["approval_id"])
            c.record_metrics(
                r["product_id"],
                pv=stats["pv"], purchases=stats["purchases"],
                revenue_jpy=stats["revenue_jpy"], likes=stats["likes"],
                rating=stats["rating"],
                source={"search": rng.randint(20, 60), "sns": rng.randint(10, 40),
                        "direct": rng.randint(5, 20)},
            )
    evaluation = c.evaluate()
    return {"planned": planned, "evaluation": evaluation, "summary": c.kpi.summary()}
