# AIコンテンツ販売会社 OS (`content-company`)

ロードマップ *「AI自律型note運営会社」* を実装するプロジェクト。単なる「記事
自動生成システム」ではなく、役割・責任・Skill・判断基準を持つ複数の AI
エージェントを配置した**小さな会社の OS** を作る (ロードマップ §1, §42)。

> **設計の起点（§41–§42）**: 最初から「note記事を自動生成するプログラム」を
> 作らない。まず **AI会社を運営する OS**（Agent / Skill / Task / Memory /
> Model Router / Permission / Approval / KPI）を構築する。note・X・TikTok は
> 外部チャネルとして後から接続する。

## いま何ができるか（実装済み）

- **AI会社 OS コア**（ロードマップ §41 Step 1）
  - Company Memory（§7）／ Model Router（§15）／ Cost Controller（§36–37）
  - Human Approval Gateway & Permission（§21, §3.2）／ Task 管理（§18）
  - KPI 集計（§25, §39）／ 20商品の実験設計・撤退基準（§10–11, 付録A）
- **MVP パイプライン**（§39 の成功条件）
  - 「N商品を企画して」→ 調査→企画→執筆→レビュー→**公開待ち** まで自律実行
  - 「先月どうだった?」→ 売上/PV/購入率/成功/失敗/原因/次回改善案 を回答
- **ダッシュボード**（§25）静的 HTML 生成
- **外部 API 不要**。標準ライブラリのみ・ローカルファイル保存（§36, §26）

実際の文章生成 LLM は `AgentRunner` の差し込みで後から接続する構造
（既定は決定論的な雛形 `TemplateRunner`）。→ [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

## クイックスタート

```bash
cd content-company

# 1) 架空データで全ループを実演（企画→承認→公開→実績→評価）
python3 -m company demo

# 2) ダッシュボードを生成して開く
python3 -m company dashboard --out dashboard.html

# 3) 実運用の入口: N商品を公開待ちまで企画
python3 -m company plan --n 5
python3 -m company approvals            # 承認待ち一覧 (§21)
python3 -m company approve <approval_id>
python3 -m company publish <product_id> --url https://note.com/... --approval <id>
python3 -m company metrics <product_id> --pv 1200 --purchases 30 --revenue 3000
python3 -m company evaluate             # 成功/失敗の評価と次アクション (§31)
python3 -m company report --period 2026-08

# テスト
python3 -m unittest discover -s tests
```

> `demo` は説明用の**架空データ**を書き込みます。実運用データと混ぜたくない
> 場合は `data_dir` を分けてください（`company.json` の `data_dir`）。

## ディレクトリ

```
content-company/
├── company/            # AI会社 OS（Pythonパッケージ, 標準ライブラリのみ）
├── agents/             # 各AI「社員」の定義書 (§4, §3.1)
├── skills/             # 再利用可能な Skill 定義 (§19)
├── data/               # ローカル台帳 (§26)。構造だけ git 管理
├── docs/               # Phase 0 設計成果物 (§27)
└── tests/              # unittest
```

## ドキュメント

| ファイル | 内容 | ロードマップ |
|---|---|---|
| [`CLAUDE.md`](CLAUDE.md) | 開発ガイド / 再開手順 | §42, §44 |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 全体構成 | §5, §41 |
| [`docs/AGENTS.md`](docs/AGENTS.md) | 組織と役割 | §4, §28, §35 |
| [`docs/SKILLS.md`](docs/SKILLS.md) | Skill システム | §19, §20 |
| [`docs/TASKS.md`](docs/TASKS.md) | Task ワークフロー | §18 |
| [`docs/SECURITY.md`](docs/SECURITY.md) | 権限・承認・法規制 | §21, §3.2, 付録A |
| [`docs/COST_CONTROL.md`](docs/COST_CONTROL.md) | コスト方針 | §14–17, §36–37 |
| [`docs/MEMORY.md`](docs/MEMORY.md) | Company Memory と保存構造 | §7, §26 |
| [`docs/ROADMAP-PHASES.md`](docs/ROADMAP-PHASES.md) | Phase 対応表と進捗 | §27–34, §41 |

## 関連

同リポジトリの `ai-os/` は汎用の AI 実行プレーン。将来、本 OS の
`AgentRunner` をそこに接続すれば、note 以外の事業にも同じ会社 OS を再利用できる
（§42）。
