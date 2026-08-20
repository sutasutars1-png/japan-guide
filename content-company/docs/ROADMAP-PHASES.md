# ROADMAP-PHASES — Phase 対応表と進捗 (§27–§34, §41)

ロードマップの各 Phase / 開発 Step と、本実装の対応・進捗。

## 開発順序（§41）

| Step | 内容 | 状態 |
|---|---|---|
| 1 | AI会社の OS（Agent/Skill/Task/Memory/Router/Permission/Approval/KPI） | ✅ 実装 |
| 2 | 20商品の市場実験システム | ✅ 骨格（実験設計・ラウンド・撤退・台帳） |
| 3 | note 運用の接続 | ◻️ 未（公開は承認ゲートまで。実連携は付録A #2 の設計待ち） |
| 4 | 販売・アクセスデータの取り込み | ◻️ 手動入力 `metrics` のみ実装。自動取得は未 |
| 5 | 自律改善ループの完成 | ◻️ 評価/改善は実装、実文章生成 LLM 接続が残る |
| 6 | X 追加 | ◻️ 未（agent 定義のみ） |
| 7 | TikTok 追加 | ◻️ 未（agent 定義のみ） |
| 8 | 自動化範囲の拡大 | ◻️ 未 |

## Phase 対応（§27–§34）

- **Phase 0 設計（§27）**: 成果物 CLAUDE / ARCHITECTURE / AGENTS / SKILLS /
  TASKS / SECURITY / COST_CONTROL / MEMORY を作成 → ✅（本 docs 群）。
- **Phase 1 MVP（§28）**: 5 Agent が自律的に Task を進める → ✅
  `Company.plan_products()` が research→plan→write→review を連鎖。
- **Phase 2 20商品実験（§29）**: 5商品×4ラウンドの設計 → ✅ `ExperimentDesign`
  （均等探索→上位集中→撤退）。正確な経験データ蓄積を優先。
- **Phase 3 note運用自動化（§30）**: 企画→…→公開待ち→人間承認→公開→URL保存→
  Marketing → ◻️ 公開までの骨格はあり、note 実連携は未。
- **Phase 4 分析自動化（§31）**: データ収集→ランキング→成功/失敗→改善案→CEO→
  次実験 → ✅ `evaluate()` / `report()` / `KPI.patterns()`。
- **Phase 5 X（§32）/ Phase 6 TikTok（§33）**: ◻️ 未。
- **Phase 7 完全な Growth Loop（§34）**: ◻️ ループ骨格はあるが LLM/チャネル接続待ち。

## MVP 成功条件（§39）の充足状況

- 「今月 note で売れる商品を 5 つ企画して」→ 調査→需要分析→商品候補→優先順位→
  企画→記事構成→記事作成→レビュー→**公開待ち** まで自動 → ✅（文章の中身は
  実 LLM 接続で仕上げる。骨格・台帳・実験化は完了）。
- 「先月の商品はどうだった?」→ 売上/PV/購入率/成功商品/失敗商品/原因/次回改善案
  → ✅ `Company.report(period)`。
- 定量目標（付録A）: 目標購入率 `target_conversion_rate`、損益分岐商品数
  `breakeven_product_count` を `Config` に設定し KPI で判定。

## 次にやること（優先度順）

1. 実 LLM ランナー（`AgentRunner` 実装、Claude Code / `ai-os` 接続）で雛形を実文章に。
2. note データ取り込み経路の確定（付録A #2。CSV エクスポート等）。
3. Skill 自己改善ループ（§20）の実行系。
4. X → TikTok チャネル（§32–33）。
