# SECURITY — 権限・承認・法規制 (§3.2, §21, 付録A)

## Human Approval Gateway (§21)

AI が重要な外部操作を勝手に実行しない。人間は「記事を書く」のではなく
「公開してよいか」を判断する。

**人間承認が必須の操作**（`company/approval.py` の `SENSITIVE_OPERATIONS`）:

| kind | 内容 |
|---|---|
| `publish` | 外部公開（note 等） |
| `account` | アカウント操作 |
| `api_key` | APIキー |
| `payment` | 支払い |
| `delete` | 削除 |
| `bulk_post` | 大量投稿 |
| `config` | 重要な設定変更（Skill 改版の採用など） |

フロー: `request()` → 人間が `approve()` / `reject()` → 実行直前に `guard()`。
未承認で `guard()` を呼ぶと `PermissionError_` を送出する（`Company.publish` が実装例）。

安全性が確認できた操作は段階的に自動化する（§38）。ただし自動化の判断自体も
データと ROI に基づき、いきなり 100% にしない（§44-13）。

## プラットフォームリスク（付録A #1）

- note の利用規約（自動投稿・大量投稿・AI生成物の扱い）を着手前に確認する。
- 公開ペースに上限を設ける: `Config.max_publishes_per_day`（既定 2）。
- 短期の大量公開はスパム判定・アカウント停止リスク。§22 の方針を数値化。

## 法規制（付録A #4）

`quality-review` Skill の必須チェックに含める:

- **特定商取引法**: デジタル商品販売での表記義務。
- **景品表示法（優良誤認）**: 「必ず稼げる」「成功確率」等の断定を避ける。
  `product-planning` / `article-writing` の禁止事項に明記済み。
- **著作権**: 引用・素材の権利確認。

## コンテンツの薄さ・重複（付録A #5）

短期に類似 20 商品を出すリスク。`quality-review` の重複チェックを
「カテゴリ内の類似度」まで踏み込ませる。実験は撤退基準（付録A）で早期に畳む。

## バックアップ / 復旧（付録A #6）

Company Memory・実験データの喪失は事業の記憶喪失に等しい。

- `Storage.snapshot()` / `python3 -m company backup` で data/ を zip 化。
- 書き込みは一時ファイル経由の原子的置換（`Storage._atomic_write`）で
  途中破損を防ぐ。定期バックアップを運用に組み込む。

## SNS（X/TikTok）と自動化の安全設計（§32-33, §38）

- **自動投稿しない**。AI は下書きを作るだけで、投稿は人間（§32）。外部
  ネットワークにアクセスする経路をアプリに持たせない。
- SNS 投稿の記録（`mark_posted`）は `sns_post` 承認を通していないと拒否。
- **定期スケジューラ**は `SAFE_JOBS` にハードコードした内部ジョブのみ実行し、
  公開・投稿・承認・削除を一切行わない。既定オフ。→ [`SOCIAL-AND-SCHEDULER.md`](SOCIAL-AND-SCHEDULER.md)

## GUI の安全設計

- 既定 127.0.0.1 束縛のローカル専用ツール（認証なし前提）。非ループバック時は警告。
- **CSRF**: クロスオリジンの POST を `Origin` 検査で 403 拒否。
- リクエストボディ 1MB 上限。
- 設定変更は許可フィールドのみ（`data_dir` 等のパスは変更不可）。

## 秘密情報

- 外部 API を必須にしない（§36）。API キーを使う場合も台帳（`data/`）や
  コミットに書かない。`company.local.json` は `.gitignore` 済み。
- モデル識別子（`claude-<family>-<ver>`）を成果物・コミットに書かない。
