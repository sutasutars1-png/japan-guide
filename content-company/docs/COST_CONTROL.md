# COST_CONTROL — コスト方針 (§14–17, §36–37)

## 重要条件（§36）

**「サブスクの Pro 範囲内のみ」**。初期システムは外部 AI API を必須にしない。
Claude Code / 利用可能な Pro モデル / ローカル DB / ローカルファイル /
必要最小限の Web アクセスで構築する。API 課金サービスは原則オプション扱い。

## モデルの使い分け（§14）と Router（§15）

「高性能モデルは必要な場所だけ使う」。3 Tier:

| Tier | 用途 | 例 |
|---|---|---|
| 1 軽量 | 分類・タグ付け・要約・重複判定・定型 | classify, summarize |
| 2 通常 | 市場分析・記事構成・記事作成・SNS・商品説明 | article_write, research |
| 3 高性能 | CEO判断・重要企画・複雑分析・最終レビュー・改善戦略 | ceo_decision, product_plan, review_final |

`company/router.py` が task_type ごとに難易度・重要度から Tier を機械的に選ぶ
（§15 の分岐: 簡単→1、難+重要度中→2、難+重要→3）。

## 予算レベル（§37）

Task ごとに LOW / MEDIUM / HIGH を割り当て、Tier に対応させる。

```
Research LOW / 分類 LOW / 要約 LOW / 記事構成 MEDIUM / 記事作成 MEDIUM /
CEO判断 HIGH / 最終レビュー HIGH
```

## コスト計上とスループット制御

`company/cost.py`:

- 実費（円）ではなく相対 **コストユニット**（Tier1=1, Tier2=4, Tier3=12）で管理。
- `metrics` ログに task 単位で計上。Agent別・Tier別に集計（§25 コスト画面）。
- **1日のタスク上限**（`Config.max_tasks_per_day`, 既定 40）を超えると
  `BudgetExceeded`。多エージェントの継続運用で Pro 上限に当たるのを防ぐ（付録A #3）。

## トークン最適化（§16）とキャッシュ（§17）

- AI に毎回全データを渡さない。コンテキストは階層化（現タスク → 関連過去 →
  成功/失敗パターン → 全体戦略）。必要な時だけ上位を足す。
- 調査・競合・商品情報・記事構成・レビュー結果・過去判断は保存し、ID 参照で
  必要分だけ取り出す（`Storage` + `CompanyMemory`）。

## KPI との接続（付録A KPI強化案）

`KPI.summary()` は `ai_cost_units` と **1商品あたり AIコスト**
（`ai_cost_per_product`）を返す。§36 の Pro 範囲運用と直結して管理する。
