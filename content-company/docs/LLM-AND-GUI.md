# 実 LLM ランナー・Skill自己改善・GUI

ロードマップ §42（実行プレーン差し込み）・§20（自己改善）・§25/§3.3（人間は
経営判断と承認に集中）に対応する 3 機能。

## 1. 実 LLM ランナー（`ClaudeRunner`, §42）

`company/runner_claude.py`。`ai-os` で実証済みの**キーレス**方式を踏襲する。

- ユーザー自身のログイン済み `claude` バイナリに `-p`（ヘッドレス）で問い合わせ、
  **API キーを使わない**（サブスク・ログイン）。従量課金なし（§36）。
- API 課金 env（`ANTHROPIC_API_KEY` 等）はサブプロセスから除去。
- `--dangerously-skip-permissions` は渡さず、ツールは全禁止（テキスト生成のみ）。
  生成（頭脳）はホスト側で、ファイル実行（手）とは分離。
- 各 task_type に対し、担当 Agent の役割（§4）＋現行採用版 Skill（§19/§20）から
  プロンプトを組み、**厳密 JSON** で返させて `TemplateRunner` と同じ出力形へ整える。
- 失敗時（未検出/タイムアウト/JSON不正）は `TemplateRunner` に**フォールバック**し
  `_llm_error` を付与（正直に劣化）。

有効化:
```bash
python3 -m company plan --n 5 --llm      # CLI
python3 -m company gui --llm             # GUI
```
コードからは `Company().enable_llm()`（`True`=有効化成功 / `False`=CLI未検出）。

**設計上の注意（実測で判明）**
- LLM は `body_markdown` に生の改行を入れるので、JSON 解析は `strict=False`。
- 記事生成は完成品なので `is_skeleton` を付けない → Reviewer が通過させうる。
  雛形は `is_skeleton=True` を付け、Reviewer が差し戻す（§4）。
- Reviewer は実際に品質・景表法・特商法・著作権を点検し、抽象的すぎる/誇張が
  あれば `reject`。reject は `review` 状態で残り Writer/人間の再対応へ（自動再執筆は
  コスト配慮で既定オフ）。

## 2. Skill 自己改善ループ（`SkillLab`, §20）

`company/skill_improve.py`。**直接上書き禁止**。改善は必ず新 version として積む。

```
現行Skill → propose(改善案=新version) → evaluate(旧版比較) →
request_adoption(承認申請 kind=config) → 人間承認 → adopt(新versionを採用)
```

- 実体は `data/skills/<key>.json`（`current` と `versions[]`）。seed=v1。
- `adopt` は `ApprovalGateway.guard("config", ...)` で未承認なら例外。採用時、旧
  採用版は `retired`、決定ログ（§44-11）とメモリに履歴を残す（§44-12）。
- 評価器は差し込み可能（既定は完成度ヒューリスティック）。LLM 評価器を渡せば
  新旧 Skill の実出力比較もできる。
- 採用版のガイダンスは `SkillLab.text(key)` として `ClaudeRunner` のプロンプトに
  反映される（改善が実生成に効く）。

CLI: `python3 -m company skill list|versions|propose|evaluate|request-adoption|adopt`

## 3. ローカル Web GUI（`webgui.py`）

`python3 -m company gui`（既定 `http://127.0.0.1:8787/`）。標準ライブラリの
`http.server` のみ・**npm 不要**（§36）。人間の役割＝経営判断・承認（§3.3, §21）に
集中できるよう、**承認待ち**と**次アクション**を中心に据えたコックピット。

できること:
- 経営 KPI と実験進捗の一覧（§25）
- 「商品を企画」（`--llm` トグルで実 LLM）／「デモ投入」／「評価」
- **承認待ち**の承認・却下、承認からの note 公開（§21, §22）
- 公開商品の実績入力（§30-31, 付録A #2 の手動入力）
- Skill 改善案の提案・履歴（§20）
- レポート／メモリ検索／ダッシュボード埋め込み

セキュリティ: 既定で `127.0.0.1` 束縛（ローカル管理ツール）。外部公開しない。
