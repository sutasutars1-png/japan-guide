# STATE — 引き継ぎ / 再開ガイド（まずここを読む）

> 記憶を持たない新しいセッションが、ここだけ読めば作業を続けられるための
> 単一の入口。**各作業セッションの最後に、この「現在地」と「次にやること」を
> 更新すること。**

## 現在地（最終更新: 2026-08-20）

- **ブランチ**: `claude/content-sales-company-build-n068kg`
- **場所**: すべて `content-company/` 配下（同リポジトリの `ai-os/` は別物＝汎用実行プレーン）
- **テスト**: `python3 -m unittest discover -s tests` が緑（**46件**）
- **依存**: Python 3.11+、**標準ライブラリのみ**（pip 不要, §36 Pro範囲）
- **ロードマップ対応**: Phase 0〜8 を一通り実装済み。詳細は
  [`ROADMAP-PHASES.md`](ROADMAP-PHASES.md)。元ロードマップは [`roadmap-source.md`](roadmap-source.md)。

### 実装済みの機能（コミット履歴と対応）

| 機能 | 主なファイル | ロードマップ |
|---|---|---|
| OS コア（Storage/Memory/Router/Cost/Approval/Task/KPI/Experiment） | `company/*.py` | §41 Step1 |
| MVP パイプライン（企画→執筆→レビュー→公開待ち）/ 分析・改善 | `company/company.py` | §39, §31 |
| 実 LLM ランナー（Claude Code CLI・キーレス） | `company/runner_claude.py` | §42 |
| Skill 自己改善ループ | `company/skill_improve.py` | §20 |
| 自動再執筆ループ（最大3回・実LLM時のみ） | `company/company.py:_write_and_review` | §4 |
| note 連携（公開用エクスポート / 売上・PV CSV取込） | `company/note_channel.py` | §22, 付録A#2 |
| X / TikTok 下書き（投稿は人間・外部通信なし） | `company/social.py` | §32-33 |
| 定期スケジューラ（安全ジョブのみ・既定オフ） | `company/scheduler.py` | §38 |
| ローカル Web GUI / GUI設定 | `company/webgui.py`, `company/config.py` | §25, §3.3, §23 |
| 品質ループ（体裁/価格連動/実績反映/重複） | `company/quality.py`, `company/company.py` | 付録A#4-5, §31 |

## 5分で再開する

```bash
cd content-company
python3 -m unittest discover -s tests      # まず緑を確認（46件）
python3 -m company demo                     # 架空データで全ループを実演
python3 -m company gui                      # GUI（http://127.0.0.1:8787/）
python3 -m company gui --llm                # 実 LLM 生成を有効化して起動
```

**ブランチが既にマージ済みだったら**（新規作業は積み増さない）:
```bash
git fetch origin main
git checkout -B claude/content-sales-company-build-n068kg origin/main
# 以降の作業は content-company/ に対して行い、テスト緑を保って push
```

## 触ってはいけない不変条件（セキュリティ / 設計。regress 厳禁）

1. **外部への自動送信・自動投稿・自動公開をしない**。X/TikTok は「下書き生成」
   のみで投稿は人間（§32）。アプリに外部ネットワーク送信経路を持たせない。
2. **重要操作は必ず Human Approval を通す**（`approval.py` の
   `SENSITIVE_OPERATIONS`: publish/sns_post/delete/payment/api_key/account/
   bulk_post/config）。`guard()` を外さない。
3. **定期スケジューラは `scheduler.SAFE_JOBS` の内部ジョブだけ**実行する。公開・
   投稿・承認・削除を絶対にジョブ化しない。**既定オフ**を維持。
4. **GUI は 127.0.0.1 束縛**・CSRF（Origin 検査）・ボディ1MB上限。設定変更は
   `config.EDITABLE_FIELDS` の許可制（`data_dir` 等のパスは変更不可）。
5. **LLM はキーレス**（サブスク）: `ANTHROPIC_API_KEY`/`_AUTH_TOKEN` を除去し、
   `--disallowed-tools` 指定・`--dangerously-skip-permissions` は付けない。
6. **モデル識別子（`claude-<family>-<ver>`）をコミット/コード/成果物に書かない**。
7. **Writer は単独公開しない**。必ず Reviewer→人間承認（§4, §21）。
8. KPI は「利益・学習・再現性」。記事数を目的化しない（§44-15）。

## ハマりどころ（同じ失敗を繰り返さない）

- **LLM の JSON に生の改行が入る** → `runner_claude._extract_json` は
  `json.loads(..., strict=False)`。これを外すと article_write が毎回解析失敗して
  雛形にフォールバックする。
- **`is_skeleton` フラグ**: `TemplateRunner` の記事は `is_skeleton=True` を付け、
  Reviewer が必ず reject（＝雛形は公開に回らない）。LLM/Demo の記事は付けない
  ので Reviewer を通過しうる。この規約を壊すと差し戻し判定が崩れる。
- **自動再執筆は `_llm` 記事のみ**作動（`article.get("_llm")`）。雛形で回すと
  無意味にループするため 1 回で打ち切る設計。
- **実 LLM は遅い/重い**: `claude -p` は 1 呼び出し ~1〜3 分。1 商品＝最大
  (2 + 2×3) = 8 タスク。`--llm` で n=5＋再執筆は `max_tasks_per_day`（既定40）に
  当たりうる。長時間実行は Bash の 2 分制限に注意（`timeout` 大きめ or 背景実行）。
- **Python 3.11 の f-string に `\` を直接書けない**（`tools/gen_defs.py` で一度踏んだ）。
- **設定/スケジュールの永続先**: `data/config.local.json`（GUI編集）と
  `data/schedule.json`。どちらも `data/**` として git 管理外。
- **台帳データはコミットしない**: `.gitignore` が `data/**/*.json(l)` を無視、
  構造は `.gitkeep` のみ追跡。デモ/実行後に `data/` が汚れても push 対象外。

## 次にやること（バックログ・優先度順）

1. 効果測定の可視化強化: SNS 下書き→投稿URL→note 流入→購入 のファネルを
   ダッシュボードに（`social.record_inflow` は器だけある）。
2. reject 続きの商品の扱い（再企画へ戻す導線 / 撤退連携）。
3. note 公開の半自動化は**公式手段の範囲でのみ**検討（§22）。非公式ブラウザ
   自動操作はしない。
4. SNS 自動投稿は §32「効果と安全性が確認できたら」= 現状は意図的に未実装。
   着手時は不変条件1・2を満たす設計（承認必須・監査）を先に固める。
5. SQLite 移行は「必要になった段階」で（§26）。今は JSON で十分。

## ドキュメント地図

| 目的 | ファイル |
|---|---|
| 開発ガイド（原則・コード地図） | [`../CLAUDE.md`](../CLAUDE.md) |
| 全体構成 | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| Phase 対応表・進捗 | [`ROADMAP-PHASES.md`](ROADMAP-PHASES.md) |
| 組織 / Skill / Task | [`AGENTS.md`](AGENTS.md) / [`SKILLS.md`](SKILLS.md) / [`TASKS.md`](TASKS.md) |
| 権限・承認・法規制・GUI安全 | [`SECURITY.md`](SECURITY.md) |
| コスト方針・Model Router | [`COST_CONTROL.md`](COST_CONTROL.md) |
| Company Memory・データ構造 | [`MEMORY.md`](MEMORY.md) |
| 実 LLM・GUI | [`LLM-AND-GUI.md`](LLM-AND-GUI.md) |
| note 連携・自動再執筆 | [`NOTE-INTEGRATION.md`](NOTE-INTEGRATION.md) |
| X/TikTok・スケジューラ・GUI設定 | [`SOCIAL-AND-SCHEDULER.md`](SOCIAL-AND-SCHEDULER.md) |
| 元ロードマップ（原文） | [`roadmap-source.md`](roadmap-source.md) |
