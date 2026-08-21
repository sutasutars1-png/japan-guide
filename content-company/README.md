# AIコンテンツ販売会社 OS (`content-company`)

ロードマップ *「AI自律型note運営会社」* を実装するプロジェクト。単なる「記事
自動生成システム」ではなく、役割・責任・Skill・判断基準を持つ複数の AI
エージェントを配置した**小さな会社の OS** を作る (ロードマップ §1, §42)。

> 🧭 **開発を引き継ぐ人（AI含む）は [`docs/STATE.md`](docs/STATE.md) から**：
> 現在地・再開手順・触ってはいけない不変条件・ハマりどころ・次にやること。

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

- **実 LLM 生成**（§42）: Claude Code CLI を使うキーレス・ランナー
  （`ClaudeRunner`）。`--llm` で有効化。未検出時は雛形にフォールバック。
  Reviewer が reject したら指摘を反映して**自動再執筆**（既定 最大3回, §4）。
- **note 連携**（§22, 付録A #2）: 公開用 Markdown エクスポート（貼り付け用、
  自動投稿はしない）＋ note 売上/PV **CSV 取り込み**。
- **X / TikTok**（§32-33）: 投稿/台本の**下書き生成**（投稿は人間・自動投稿なし）。
- **定期スケジューラ**（既定オフ・GUIオンオフ）: 安全な内部ジョブのみ。
- **GUI 設定**: チャネル有効化・運用パラメータを画面から変更（許可項目のみ）。
- **Skill 自己改善ループ**（§20）: 改善案→評価→承認→新バージョン採用。直接
  上書き禁止・履歴保存。
- **ローカル Web GUI**: `python3 -m company gui`（標準ライブラリのみ、npm不要）。

実際の文章生成 LLM は `AgentRunner` の差し込みで接続する構造（既定は決定論的な
雛形 `TemplateRunner`、`--llm` で `ClaudeRunner`）。→ [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

## クイックスタート

```bash
cd content-company

# ★ いちばん簡単: GUI を起動（ブラウザで操作）
python3 -m company gui                    # http://127.0.0.1:8787/
python3 -m company gui --llm              # 実 LLM 生成を有効化して起動

# 1) 架空データで全ループを実演（企画→承認→公開→実績→評価）
python3 -m company demo

# 2) ダッシュボードを生成して開く
python3 -m company dashboard --out dashboard.html

# 3) 実運用の入口: N商品を公開待ちまで企画
python3 -m company plan --n 5            # 雛形で骨格生成（外部API不要）
python3 -m company plan --n 5 --llm      # Claude Code CLI で実文章生成 (§42)
python3 -m company approvals            # 承認待ち一覧 (§21)
python3 -m company approve <approval_id>
python3 -m company publish <product_id> --url https://note.com/... --approval <id>
python3 -m company metrics <product_id> --pv 1200 --purchases 30 --revenue 3000
python3 -m company evaluate             # 成功/失敗の評価と次アクション (§31)
python3 -m company report --period 2026-08

# note 連携 (§22, 付録A #2)
python3 -m company note export <product_id>        # 公開用 Markdown を書き出し（貼り付け用）
python3 -m company note import note_sales.csv      # note 管理画面の CSV で実績を取り込み
python3 -m company note import note_sales.csv --dry-run
python3 -m company note template                   # 取り込み CSV のサンプル列

# X / TikTok 下書き (§32-33, 投稿は人間)
python3 -m company social draft x <product_id>      # or: tiktok
python3 -m company social list
python3 -m company social posted <social_id> --url https://x.com/...   # 要承認

# 定期スケジュール（既定オフ・安全ジョブのみ）
python3 -m company schedule status
python3 -m company schedule job note_import --on --interval 1440
python3 -m company schedule master on            # マスター有効化
python3 -m company schedule run evaluate         # 今すぐ実行

# 設定（チャネル有効化・運用パラメータ）
python3 -m company config show
python3 -m company config set x_enabled true

# Skill 自己改善 (§20)
python3 -m company skill list
python3 -m company skill propose article-writing --guidance "冒頭200字で悩みを言語化"
python3 -m company skill request-adoption article-writing 2   # 承認申請
python3 -m company approve <approval_id>
python3 -m company skill adopt article-writing 2 --approval <approval_id>

# テスト
python3 -m unittest discover -s tests
```

> **`--llm` の前提**: この環境で `claude`（Claude Code CLI）が PATH にあり、
> サブスクリプションでログイン済みであること。API キーは使わず従量課金は発生
> しません（§36）。1商品あたり4回の LLM 呼び出し（調査/企画/執筆/レビュー）を
> 順次行うため数分かかります。未ログイン/未検出時は自動で雛形にフォールバック。

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
