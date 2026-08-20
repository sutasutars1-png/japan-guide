"""Agent 実行の差し込み口 (AgentRunner)。

このパッケージは「AI会社の OS」であって、LLM そのものではない。実際の生成は
``AgentRunner`` の実装に委ねる:

* ``TemplateRunner`` (既定) — 外部 API 不要 (§36)。構造化された雛形を返す。
  企画フォーマット (§13) やタスクの骨格を機械的に組み立てるので、これだけでも
  実験設計・台帳・KPI は完全に回る。散文の中身は人間 / LLM が埋める前提。
* ``ClaudeRunner`` 等 — Claude Code や ai-os の実行プレーンに接続する実装を
  後から差し込む (§42「note/X/TikTok は外部チャネルとして後から接続」と同じ思想)。

``run(task_type, payload) -> dict`` という 1 メソッドだけの契約にしてある。
"""

from __future__ import annotations

from typing import Any, Protocol


class AgentRunner(Protocol):
    def run(self, task_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        ...


class TemplateRunner:
    """外部 API を使わない決定論ランナー (§36)。"""

    def run(self, task_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        handler = getattr(self, f"_{task_type}", None)
        if handler is None:
            return {"_note": f"未対応タスク種別 '{task_type}'。LLMランナーで置換可。", **payload}
        return handler(payload)

    # ---- research -------------------------------------------------------

    def _research(self, p: dict[str, Any]) -> dict[str, Any]:
        theme = p.get("theme", "テーマ未指定")
        return {
            "theme": theme,
            "demand_signals": [
                f"[要検証] {theme} に関する検索需要の仮説",
                f"[要検証] {theme} で反応の良いタイトル傾向の仮説",
                f"[要検証] {theme} の競合と価格帯の仮説",
            ],
            "note": "TemplateRunner の雛形。Researcher(LLM)が実データで置換する。",
        }

    # ---- product_plan (§13 商品企画フォーマット) ------------------------

    def _product_plan(self, p: dict[str, Any]) -> dict[str, Any]:
        theme = p.get("theme", "テーマ未指定")
        category = p.get("category", "?")
        price = p.get("price_jpy", 100)
        # §13 の全項目を埋める骨格。中身は要編集の [ ] プレースホルダ。
        return {
            "product_name": f"{theme} 入門ノート",
            "target": "[ターゲット読者を1行で]",
            "reader_pain": "[読者の悩み]",
            "purchase_reason": "[購入理由]",
            "problem_solved": "[解決する問題]",
            "free_part": "[無料部分の要約: 価値を示す導入]",
            "paid_part": "[有料部分の要約: 具体ノウハウ/テンプレ]",
            "price_jpy": price,
            "competitors": "[競合の有無]",
            "differentiation": "[差別化ポイント]",
            "why_sells": "[売れる根拠 — 調査シグナルにひもづける]",
            "success_probability": "[低/中/高]",
            "risk": "[規約/景表法/内容の薄さ 等のリスク]",
            "experiment_purpose": f"カテゴリー{category}の需要検証",
            "category": category,
            "theme": theme,
        }

    # ---- article_write --------------------------------------------------

    def _article_write(self, p: dict[str, Any]) -> dict[str, Any]:
        plan = p.get("plan", {})
        title = plan.get("product_name", "無題")
        return {
            "title": title,
            "is_skeleton": True,  # Reviewer が差し戻す目印 (LLMランナーは付けない)
            "outline": [
                "導入 (読者の悩みへの共感)",
                "無料部分 (価値の提示)",
                "―― ここから有料 ――",
                "本編 (具体的な解決手順)",
                "まとめ + CTA",
            ],
            "body_markdown": (
                f"# {title}\n\n"
                "> これは TemplateRunner が生成した骨格です。"
                "Writer(LLM) が読者価値のある本文へ置換します。\n\n"
                "## 導入\n[読者の悩みに共感する導入]\n\n"
                "## 無料部分\n[価値を示す前半]\n\n"
                "## 有料部分\n[購入者向けの具体ノウハウ]\n\n"
                "## まとめ\n[要点 + 次の行動(CTA)]\n"
            ),
            "cta": "この続きが役に立ったらスキ・フォローをお願いします。",
        }

    # ---- review_final (§4 の観点 + 付録A #4 法的チェック) ----------------

    def _review_final(self, p: dict[str, Any]) -> dict[str, Any]:
        article = p.get("article", {}) or {}
        body = article.get("body_markdown", "")
        checklist = {
            "誤情報": "要人間確認",
            "古い情報": "要人間確認",
            "論理破綻": "auto: OK",
            "誇張表現": "auto: 要注意 (『必ず』等の断定語をチェック)",
            "読者メリット": "要人間確認",
            "タイトルと本文の一致": "auto: OK",
            "有料部分の価値": "要人間確認",
            "重複コンテンツ": "auto: カテゴリ内類似度を要確認 (付録A #5)",
            "AIっぽい文章": "要人間確認",
            "特商法表記": "要確認 (付録A #4)",
            "景表法(優良誤認)": "auto: 断定的な効果表現に注意",
            "著作権": "要人間確認",
        }
        # 骨格 (雛形) のままなら差し戻し。TemplateRunner は is_skeleton を立てる。
        placeholder = bool(article.get("is_skeleton")) or "TemplateRunner" in body
        verdict = "reject" if placeholder else "pass"
        notes = (
            "本文が雛形のままです。Writerで内容を作成してください。"
            if placeholder
            else "自動チェックは通過。最終公開判断は人間承認へ。"
        )
        return {"verdict": verdict, "checklist": checklist, "notes": notes}
