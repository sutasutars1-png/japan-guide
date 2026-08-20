# ARCHITECTURE — AIコンテンツ販売会社 OS

ロードマップ §5 / §41 / §42 に対応する全体構成。

## レイヤー

```
┌──────────────────────────────────────────────────────────┐
│ 入口: CLI (company/cli.py) / Dashboard (dashboard.py)     │
│        └ 将来: Web UI / ai-os 連携                         │
├──────────────────────────────────────────────────────────┤
│ ファサード: Company (company/company.py)                  │
│   plan_products() / publish() / evaluate() / report()     │
├───────────┬───────────┬───────────┬──────────┬───────────┤
│ Memory    │ Task      │ Approval  │ KPI      │ Experiment │
│ (§7)      │ (§18)     │ (§21)     │ (§25/39) │ (§10-11)   │
├───────────┴─────┬─────┴─────┬─────┴──────────┴───────────┤
│ Router (§15)    │ Cost (§37)│ Runner=AgentRunner (§42)    │
├─────────────────┴───────────┴─────────────────────────────┤
│ Storage: ローカル JSON / JSONL (§26)                      │
└──────────────────────────────────────────────────────────┘
```

**設計上の要（load-bearing、外さない）**

1. **Agent / Skill / Task の分離**（§44-1〜4）。巨大プロンプト化を避ける。
2. **Runner 抽象**（`AgentRunner`）。LLM 実体を差し替え可能にし、既定は外部
   API 不要の `TemplateRunner`（§36）。→ note/X/TikTok も「後付けチャネル」（§42）。
3. **安全プリミティブ**。Approval Gateway と Permission（§21, §3.2）、判断根拠の
   保存（Decision, §44-11）、バックアップ（Storage.snapshot, 付録A #6）。

## 基本フロー（§5 の実装）

```
市場調査 → 需要分析 → 商品企画 → 記事作成 → AIレビュー
  → 公開承認(人間) → note公開 → 集客 → 販売 → データ収集
  → 販売分析 → 成功/失敗抽出 → 改善案 → CEO判断 → 次の商品企画 → 繰り返し
```

コードでの対応:
- 市場調査〜公開待ち: `Company.plan_products()`（`_plan_one` が Task を連鎖）
- 公開承認〜公開: `ApprovalGateway` → `Company.publish()`
- データ収集: `Company.record_metrics()`（当面は手動入力。付録A #2）
- 分析〜改善: `Company.evaluate()` / `KPI.patterns()`
- 次の企画: 次ラウンドの `plan_products()`（`ExperimentDesign.round_allocation`）

## データフロー（§26）

各エンティティは `data/<collection>/<id>.json`、時系列ログは
`data/<log>/log.jsonl`。上位は `Storage` API だけに依存し、後で SQLite へ
移行してもインターフェースは不変。

## 拡張ポイント

| やりたいこと | 触る場所 |
|---|---|
| 実 LLM で文章生成 | `AgentRunner` を実装し `Company(runner=...)` に渡す |
| note 連携（公開/データ取得） | `publish()` の後段 / `record_metrics()` の入力経路 |
| X・TikTok | `agents.py` の marketing 系 + 新 Runner タスク種別 |
| モデル方針変更 | `router.py` の `TASK_PROFILE` |
| コスト単価・上限 | `cost.py` / `config.py` |
