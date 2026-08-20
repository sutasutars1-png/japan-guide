# MEMORY — Company Memory とデータ保存 (§7, §26)

## Company Memory (§7)

AI 会社に「記憶」を持たせ、「前に何を試した?」に答えられる状態を作る。
`company/memory.py` の `CompanyMemory`。実体は `data/memory/log.jsonl`。

**保存する種別（kind）**: decision（経営判断）/ hypothesis（仮説）/
experiment（実験）/ result（成果）/ failure / success / customer（顧客反応）/
improvement（改善）/ product / research / competitor / review / kpi /
pattern_success / pattern_failure / note。

API:
- `add(kind, title, body, tags=, related=)`
- `query(text=, kind=, tag=)` — 「副業テーマ、前に試した?」のような検索
- `recent(n, kind=)` / `patterns(success=True|False)`

パイプラインの各段（企画・レビュー・公開・評価）で自動的に記憶を積む。
`evaluate()` は成功/失敗を pattern_success / pattern_failure として抽出する（§6）。

## データ保存構造 (§26)

初期は複雑な DB を作りすぎない。`data/` 直下に用途別ディレクトリ:

```
data/
  products/     商品台帳 (§8)         <id>.json
  articles/     記事本文               <id>.json
  research/     市場・競合調査         <id>.json
  analytics/    実績スナップショット    <id>.json
  experiments/  実験メタ               <id>.json
  hypotheses/   仮説・実験データ (§9)  <id>.json
  tasks/        Task 台帳 (§18)        <id>.json
  approvals/    承認申請 (§21)         <id>.json
  skills/       Skill 改版履歴 (§20)   <id>.json
  memory/       Company Memory (§7)    log.jsonl
  decisions/    意思決定ログ (§44-11)  log.jsonl
  metrics/      コスト・KPI ログ (§37) log.jsonl
```

- **1レコード1ファイル**の台帳（コレクション）と、**追記のみ**の時系列ログ
  （memory / decisions / metrics）の 2 形式だけ。
- 上位コードは `Storage` API のみに依存。必要になった段階で SQLite 等へ移行しても
  インターフェースは不変（§26）。

## 商品データ (§8) と 仮説・実験データ (§9)

各商品を単なる「記事」ではなく「実験」として管理する（§9）。`models.Product`
は実績（PV/購入/売上/購入率/評価/流入元）と実験メタ（hypothesis_id /
experiment_round / outcome / improvement）を持ち、`models.Hypothesis` が
仮説・根拠・KPI・結果・原因・学習を保持する。これにより会社は「記事を書く会社」
ではなく「市場を学習する会社」になる（§9）。

## バックアップ（付録A #6）

`Storage.snapshot(dest)` / `python3 -m company backup` で data/ 全体を zip 化。
定期実行を運用に組み込み、喪失＝事業の記憶喪失を防ぐ。
