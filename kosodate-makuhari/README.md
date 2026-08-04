# 子連れ海浜幕張 — MVPサイト雛形（Astro + Cloudflare Pages）

確かめた事実（出典・確認日つき）だけで子連れスポットを見せ、AIで一日を組むサイトの最小雛形。
無料・商用可のCloudflare Pages/Functionsで動く。全データは千葉市OD(CC BY 4.0)とOpenStreetMap(ODbL)由来。

## 構成
- `src/pages/` … トップ / スポット一覧(`/spots`) / スポット詳細(`/spots/[slug]`, SSG・schema.org) / 一日を組む(`/plan`) / 出典ポリシー(`/about`)
- `functions/api/plan.js` … AI旅程生成（Claude APIをサーバ側で呼ぶ）
- `functions/api/claim.js` … 店舗自己申告の受付（突合後に昇格）
- `ingest/ingest.py` … 実データ取込（千葉市OD＋OSM）→ `data/spots.json`
- `data/spots.json` … 生成済みの実データ（海浜幕張157件）

## 必要なもの
Node 18+ / npm、Cloudflareアカウント（無料）、Gemini APIキー（Google AI Studio）、Python3（取込用・標準ライブラリのみ）

## ローカル開発
```
npm install
npm run dev            # http://localhost:4321
```

## データ更新（取込）
```
python ingest/ingest.py    # data/spots.json を再生成（千葉市OD＋OSM、無料・鍵不要）
npm run build              # 静的ページを再ビルド
```
※ 地域を増やす時は BBOX を変え、アダプタを足すだけ（Normalizer/Validatorは不変）。

## Cloudflare Pages へデプロイ
### A. Git連携（推奨）
1. このリポジトリをGitHub等へpush
2. Cloudflareダッシュボード → Pages → Git連携。ビルドコマンド `npm run build`、出力ディレクトリ `dist`
3. APIキーを設定：Settings → 環境変数/シークレットに `GEMINI_API_KEY`（任意で `GEMINI_MODEL`）
### B. CLI
```
npm run build
npx wrangler pages deploy dist
npx wrangler pages secret put GEMINI_API_KEY
```

## 旅程生成API（Gemini・無料枠）
`functions/api/plan.js` は Google の **Gemini API（無料枠）** を使用。既定モデルは `gemini-2.5-flash`。
- キー取得：https://aistudio.google.com → Get API key（`AIza...` の文字列）。
- 設定：`npx wrangler pages secret put GEMINI_API_KEY`。モデルを変える場合は `GEMINI_MODEL` を設定（RPDを増やしたい場合は `gemini-2.5-flash-lite`）。
- 無料枠はレート制限あり（2.5 Flashで概ね10 RPM／数百RPD）。MVP規模なら十分。上限に達したらGCPで課金を有効化。

## owner_claim を保存する場合（任意）
`wrangler.toml` のKV設定を有効化し、`wrangler kv namespace create CLAIMS` で作成したIDを記入。一般ユーザー投稿は受け付けない設計です。

## 公開の運用ルール（必須）
- 出典表示を全ページに（千葉市 CC BY 4.0 ／ © OpenStreetMap contributors ODbL）。
- 安全事項（アレルギー等）は開示有無のみ・対応可否は非保証・「店舗へ確認を」。
- precision > recall（迷ったら出さない・未確認と正直に）。薄いページ/結果5件未満のファセットは noindex に。
- 面展開は各クラスタが公開ゲートL2（公開20件＋飲食5件）を満たすまで非公開。
