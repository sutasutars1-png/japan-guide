"""システム改修提案 (§20 のメタ改善 / §31, §34)。

Skill やコンテンツの改善は「設計済みの仕組みの中」の最適化。これに対し本モジュール
は **システム自体を売れるように改修する提案**（機能追加・仕組みの変更）を生成する。

安全設計（不変条件）: AI は **提案を起票するだけ**。コードの自動改変はしない。
実装するかは人間が採否を決める（会社でいう CTO/Growth が起案 → 経営が承認 → 実装）。

* 決定論ヒューリスティック（`heuristic_proposals`）: KPI/実績/教訓/失敗から状況を
  検知して具体的な改修案を出す（標準ライブラリのみ・オフライン）。
* 実 LLM 時は別途 Growth エージェントの `system_improve` タスクでも提案を追加する。
"""

from __future__ import annotations

import re
from typing import Any

from . import ids

# 提案カテゴリ（売上ドライバ別）。
CATEGORIES = ("funnel", "pricing", "channel", "measurement", "ux", "quality", "retention")


def slug(title: str) -> str:
    s = re.sub(r"\s+", "-", title.strip())
    s = re.sub(r"[^0-9A-Za-z぀-ヿ一-鿿\-]", "", s)
    return "imp_" + (s[:48] or ids.new_id("x"))


def _p(title: str, problem: str, hypothesis: str, effect: str,
       category: str, effort: str) -> dict[str, Any]:
    return {"id": slug(title), "title": title, "problem": problem,
            "hypothesis": hypothesis, "expected_effect": effect,
            "category": category, "effort": effort, "source": "heuristic",
            "status": "new", "created_at": ids.now_iso()}


def heuristic_proposals(company) -> list[dict[str, Any]]:
    """現在のデータから、売上を上げるためのシステム改修案を生成する。"""
    kpi = company.kpi.summary()
    products = company.storage.all("products")
    published = [p for p in products if p.get("status") == "published"]
    awaiting = [p for p in products if p.get("status") == "awaiting_approval"]
    lessons = [r for r in company.storage.all("lessons") if r.get("active")]
    social = company.social.list() if hasattr(company, "social") else []
    posted = [s for s in social if s.get("status") == "posted"]
    out: list[dict[str, Any]] = []

    # 1) 転換ゼロ: 無料→見込み客→有料のファネルが無い
    if kpi.get("pv", 0) > 0 and kpi.get("purchases", 0) == 0:
        out.append(_p(
            "無料リードマグネット＋メール導線を追加",
            "PVはあるが購入0。無料で価値を配って信頼を作り、購入に橋渡しする仕組みが無い。",
            "無料記事（リード磁石）→ 登録導線 → 有料商品、の順に接触を増やせば購入率が上がる。",
            "購入率の底上げ（0→数%）。LTV向上。", "funnel", "M"))

    # 2) PVはあるのに目標購入率未達: タイトル/価格の A/B テスト
    if kpi.get("pv", 0) >= 50 and not kpi.get("conversion_target_met", False):
        out.append(_p(
            "タイトル・価格の A/B テスト機能",
            "PVはあるのに目標購入率に届かない。何が刺さるか当て推量で決めている。",
            "同一商品でタイトル/価格の2案を出し分けて計測し、勝ち筋をデータで決める。",
            "購入率・客単価の改善を再現可能に。", "experiment", "M"))

    # 3) 流入計測が使われていない（record_inflow が空）
    if not posted or all(not s.get("inflow") for s in social):
        out.append(_p(
            "SNS→note 流入→購入 のファネル計測を実装",
            "SNS下書きは作れるが、投稿→note流入→購入の効果が数値で追えない。",
            "投稿URLごとに流入と購入を紐づけ、どの発信が売れたかを可視化する。",
            "勝ちチャネル/勝ち投稿の特定 → 集客効率UP。", "measurement", "M"))

    # 4) 単発商品ばかり: バンドル/シリーズで客単価を上げる
    if len(products) >= 3:
        out.append(_p(
            "シリーズ/バンドル（まとめ買い）商品タイプを追加",
            "商品が単発の記事のみ。関連記事をまとめた高単価商品が作れない。",
            "関連する複数記事をシリーズ化・セット販売し、客単価と回遊を上げる。",
            "客単価UP・回遊増・ファン化。", "pricing", "M"))

    # 5) 公開待ちが滞留: 承認→公開→URL記録の一括フロー
    if len(awaiting) >= 3:
        out.append(_p(
            "承認→公開→URL記録の一括処理UIを追加",
            f"公開待ちが{len(awaiting)}件滞留。1件ずつの操作で公開が追いつかない。",
            "複数商品をまとめて承認・公開URL記録できるバッチUIで運用を軽くする。",
            "公開スループット向上 → 機会損失の削減。", "ux", "S"))

    # 6) 教訓が溜まっている: 企画段階の事前チェックリスト化
    if len(lessons) >= 2:
        out.append(_p(
            "頻出の差し戻しを企画段階で自動チェック",
            "同じ差し戻し（教訓）が繰り返されている。執筆後に気づくのは手戻りが大きい。",
            "獲得した教訓を企画・アウトライン段階のチェックに前倒しし、手戻りを減らす。",
            "生成コスト削減・品質の安定。", "quality", "S"))

    # 7) 公開実績があるのにリピート施策が無い
    if published:
        out.append(_p(
            "購入者向けのフォロー/次商品レコメンドを設計",
            "単発購入で終わり、リピート・アップセルの仕組みが無い。",
            "購入者に関連商品や続編を案内する導線で、2回目の購入を作る。",
            "リピート率・LTV向上。", "retention", "M"))

    # 常設の戦略提案（データが乏しくても最低限の示唆を出す）
    out.append(_p(
        "売上ダッシュボードに『次の一手』を自動提示",
        "数値は見えるが、次に何をすべきかの示唆が弱い。",
        "KPIから改善アクション（値下げ/タイトル改善/チャネル追加等）を自動提示する。",
        "意思決定の速度と質を上げる。", "measurement", "M"))
    return out
