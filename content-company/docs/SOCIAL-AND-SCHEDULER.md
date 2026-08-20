# X / TikTok チャネル・定期スケジュール・GUI設定

ロードマップ §32（X）・§33（TikTok）・§23（チャネル段階導入）・付録A #2
（CSV取込の定期化）に対応。**セキュリティを最優先**に設計している。

## X / TikTok（§32-33） — 下書きのみ・投稿は人間

`company/social.py`。ロードマップの初期フェーズ「AI作成 → 人間確認 → 人間投稿」
（§32）に忠実。**外部ネットワークに一切アクセスしない**。

```
draft(channel, product_id)   Marketing が投稿/台本の下書きを生成 → sns_post 承認を要求(§21)
  ↓ 人間が承認（内容の人間確認, §32）
  ↓ 人間が X / TikTok に投稿
mark_posted(social_id, url)  投稿URLを記録（承認済みでなければ拒否）
record_inflow(social_id, n)  note への流入を記録（§24 効果測定）
```

- X: 無料記事→note へ誘導する投稿案（`x_post`）。TikTok: 売れた記事の台本
  （`tiktok_script`）。実 LLM 有効時は Marketing×x/tiktok-marketing Skill で生成。
- 自動投稿・API連携は**しない**。「効果と安全性が確認できたら段階的に検討」（§32）。
- CLI: `python3 -m company social draft x|tiktok <product_id>` / `list` / `posted`。
  GUI: 公開商品の行の「X下書き / TikTok下書き」、SNS下書きパネル。

## 定期スケジュール（既定オフ）

`company/scheduler.py`。GUI プロセスが動く間だけ動く軽量スレッド。

**セキュリティ設計**
- 実行できるのは `SAFE_JOBS` に**ハードコードされた3ジョブだけ**。外部から任意
  処理を差し込めない。
  - `evaluate` … 成功/失敗の評価（内部集計）
  - `note_import` … `data/inbox/note.csv` があれば取込（固定の内部パスのみ）
  - `social_draft` … 有効チャネルの売れ筋に下書きを1件生成（**投稿はしない**）
- **公開・SNS投稿・承認・削除などの重要操作は一切しない**（§21）。
- マスタースイッチと各ジョブは**既定オフ**。設定は `data/schedule.json` に保存。
- 間隔は 1分〜30日にクランプ。未登録ジョブ名は実行不可。
- CLI: `schedule status|master on/off|job <name> --on/--off --interval N|run <name>`。
  GUI: 「定期スケジュール」パネル（マスター＋ジョブ別トグル＋今すぐ実行）。

## GUI 設定（§23, §36）

`Config.EDITABLE_FIELDS` に列挙した**安全なフィールドだけ**を GUI/CLI から変更。
`data_dir` 等のパスや未知キーは無視（改ざん防止）。値は型変換＋範囲クランプ。
保存先は `data/config.local.json`（git 管理外）で、再起動後も反映。

- 変更可能: 初期価格 / 1日タスク上限 / 1日公開上限 / 自動再執筆上限 /
  目標購入率 / 損益分岐商品数 / 撤退ラウンド / X有効 / TikTok有効。
- CLI: `config show` / `config set <key> <value>`。GUI:「設定」パネル。

## GUI のセキュリティ

- 既定で **127.0.0.1 束縛**（ローカル専用）。非ループバックで待ち受ける場合は
  起動時に警告。認証は持たない前提のローカル管理ツール。
- **CSRF 対策**: `Origin` が付くリクエストはループバック/待ち受けホスト以外を 403。
  → 悪意あるサイトからのブラウザ経由 POST を遮断（curl 等の同一マシン操作は許可）。
- リクエストボディは 1MB 上限（メモリ濫用防止）。
- アプリ全体で**外部への送信・自動投稿・自動公開はしない**。重要操作は必ず
  人間承認（§21）を通す。
