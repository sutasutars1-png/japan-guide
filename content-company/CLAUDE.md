# CLAUDE.md — AIコンテンツ販売会社 OS

AI コーディングエージェント向けの開発ガイド。対象は `content-company/` 配下。

## これは何か

ロードマップ *「AI自律型note運営会社」* を実装するプロジェクト。役割分担した
AI エージェント群で **noteを中心としたデジタルコンテンツ販売事業**を運営する
「会社の OS」を作る。同リポジトリの `ai-os/` は汎用実行プレーンで別物。

## 最重要原則（§44 の写し。開発中つねに守る）

1. AI を一体化した巨大プロンプトにしない → **Agent を役割分担**（`company/agents.py`, `agents/`）
2. **Skill は再利用可能な単位**（`company/skills.py`, `skills/`）
3. **Task 中心のワークフロー**（`company/tasks.py`）。AI 同士が無秩序に会話しない
4. **Company Memory に経験を蓄積**、成功・失敗を必ず記録（`company/memory.py`）
5. **高性能モデルは必要な場所だけ**（`company/router.py`）／ トークン最小化
6. 外部操作には**権限管理**、重要操作には**Human Approval**（`company/approval.py`）
7. AI の**判断根拠を保存**（`Decision`）。自己改善は変更履歴と評価を必須に（§20）
8. いきなり完全自動化しない。**KPI は「利益・学習・再現性」**（記事数ではない）

## いまの状態（新しいセッションはここから）

**実装済み（ロードマップ §41 Step 1〜2 ＋ 実 LLM / 自己改善 / GUI）**
- OS コア: Storage / Memory / Router / Cost / Approval / Task / KPI / Experiment
- MVP パイプライン: `Company.plan_products()`（§39）→ 調査→企画→執筆→レビュー→公開待ち
- 分析・改善: `Company.evaluate()` / `Company.report()`（§31, §39）
- **実 LLM ランナー**（§42, `runner_claude.ClaudeRunner`）: Claude Code CLI で
  キーレス生成。`Company.enable_llm()` / `--llm`。未検出時は雛形にフォールバック。
- **Skill 自己改善ループ**（§20, `skill_improve.SkillLab`）: 改善案→評価→承認→
  新版採用。直接上書き禁止・履歴保存。
- **ローカル Web GUI**（`webgui.py`）: `python3 -m company gui`。標準ライブラリのみ。
- **自動再執筆ループ**（§4, `Company._write_and_review`）: reject 時に指摘を反映して
  書き直す。上限 `config.max_rewrites`（既定 3）、実 LLM 時のみ作動。
- **note 連携**（§22, 付録A #2, `note_channel.py`）: 公開用 Markdown エクスポート
  （自動投稿なし）+ 売上/PV **CSV 取り込み**。
- **X / TikTok**（§32-33, `social.py`）: 下書き生成のみ。投稿は人間、外部通信なし。
- **定期スケジューラ**（`scheduler.py`）: `SAFE_JOBS` の内部ジョブのみ、既定オフ、
  GUI/CLI でオンオフ。公開・投稿・承認はしない。
- **GUI 設定**（`config.py` の `EDITABLE_FIELDS`）: 許可フィールドのみ変更、
  `data/config.local.json` に永続化。GUI は 127.0.0.1 束縛・CSRF/ボディ上限あり。
- ダッシュボード生成（§25）、デモシード（架空データで全ループ実演）
- **標準ライブラリのみ・外部 API 不要**（§36）。`python3 -m unittest discover -s tests` が緑（37件）

**未実装 / 次にやること**
- SNS 自動投稿（§32「効果と安全性が確認できたら」）は意図的に未実装（安全側）
- note 公開の半自動化（公式手段の範囲で）／ 効果測定（流入→購入）の可視化強化

## 開発ワークフロー

- ブランチ: **`claude/content-sales-company-build-n068kg`**
- コミットは小さく、意味のある単位で。テストを緑に保つ
- 変更したら `python3 -m unittest discover -s tests` を必ず実行
- 設計判断は本ファイルか `docs/` に追記して次セッションへ引き継ぐ

## コードの地図

| 関心事 | ファイル | ロードマップ |
|---|---|---|
| 設定・運用パラメータ | `company/config.py` | §36, 付録A |
| 永続化（JSON/JSONL） | `company/storage.py` | §26 |
| ドメインモデル | `company/models.py` | §8, §9, §18 |
| Company Memory | `company/memory.py` | §7 |
| Model Router | `company/router.py` | §14, §15 |
| Cost Controller | `company/cost.py` | §16, §36, §37 |
| Approval / Permission | `company/approval.py` | §3.2, §21 |
| Task 管理 | `company/tasks.py` | §18 |
| Agent 実行の差し込み | `company/runner.py` | §42 |
| 実 LLM ランナー(Claude CLI) | `company/runner_claude.py` | §42 |
| Skill 自己改善 | `company/skill_improve.py` | §20 |
| ローカル Web GUI | `company/webgui.py` | §25, §3.3 |
| note 連携（出力/CSV取込） | `company/note_channel.py` | §22, 付録A #2 |
| X / TikTok 下書き | `company/social.py` | §32, §33 |
| 定期スケジューラ | `company/scheduler.py` | §38, 付録A #2 |
| 自動再執筆ループ | `company/company.py:_write_and_review` | §4 |
| 組織（Agent 定義） | `company/agents.py` | §4, §28, §35 |
| Skill 定義 | `company/skills.py` | §19 |
| 実験設計・撤退基準 | `company/experiments.py` | §10, §11, 付録A |
| KPI 集計 | `company/kpi.py` | §25, §39 |
| ファサード / パイプライン | `company/company.py` | §5, §39 |
| ダッシュボード | `company/dashboard.py` | §25 |
| CLI | `company/cli.py` | — |
| デモシード（架空データ） | `company/seed.py` | — |

## 環境メモ

- Python 3.11+。依存パッケージなし（標準ライブラリのみ）
- モデル識別子（`claude-<family>-<ver>`）をコミット/コード/成果物に書かない
