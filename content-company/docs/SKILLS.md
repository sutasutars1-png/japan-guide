# SKILLS — Agent Skill システム (§19, §20)

Skill は再利用可能な単位（§44-3）。各 Skill は 8 項目を定義する:
**目的 / 手順 / 判断基準 / 入力 / 出力 / 禁止事項 / 成功条件**（＋別称）。

- 機械可読なレジストリ: `company/skills.py`（`SKILLS` 辞書）
- 詳細な手順書: `skills/<key>/SKILL.md`

## 一覧（§19）

| key | 目的（要約） |
|---|---|
| `market-research` | 「何が売れそうか」の観点で需要・競合を調べる |
| `product-planning` | §13 の企画フォーマットを埋め、実験として設計 |
| `article-writing` | 無料/有料記事・タイトル・CTA を読者価値中心に |
| `seo` | 検索需要に沿った構成 |
| `competitor-analysis` | 競合把握と差別化ポイント抽出 |
| `note-analysis` | note の売れ筋・反応分析 |
| `x-marketing` | 無料記事→X→note 導線と投稿案 |
| `tiktok-marketing` | 売れた記事のショート動画台本 |
| `data-analysis` | PV/購入/売上/流入の集計 |
| `quality-review` | §4 観点 + 法的チェック（特商法・景表法・著作権, 付録A #4） |
| `sales-analysis` | 成功/失敗パターン抽出 |
| `growth-strategy` | 次アクション（改善/横展開/集客/撤退）決定 |

## 自己改善（§20）— 直接上書き禁止

```
現行Skill → 改善案 → テスト → 旧版との比較 → 改善効果確認 → 承認 → 新Skillとして採用
```

`SkillSpec.version` を上げ、**新バージョンとして採用**する。変更履歴と評価
（効果測定）を必須にする（§44-12）。承認は `ApprovalGateway`（kind=`config`）を通す。

## Skill と Agent の対応

`company/agents.py` の `AgentSpec.skills` が担当 Skill を宣言する。Task 生成時
（`TaskManager.create(..., skill=...)`）に使用 Skill を記録し、成果物と一緒に残す。
