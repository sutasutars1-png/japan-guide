# TABIJI — インバウンド観光アフィリエイトサイト 完全パッケージ

英語・韓国語・繁体字中国語の3言語で日本の観光地を紹介し、アフィリエイトで収益化する静的サイトです。**運営コストは0円**(有料APIなし・無料ホスティング)で回るように設計されています。

## なぜこの構成か(調査に基づく設計根拠)

- **言語**: 2025年の訪日客は韓国945万・中国909万・台湾676万・米国330万・香港251万人(JNTO)。英語(欧米豪+東南アジア)・韓国語・繁体字(台湾+香港)で上位市場の大半をカバーします。簡体字圏はGoogle検索が使えずSEO効率が悪いため後回しにしています。
- **ページ構成**: japan-guide.com 等の高アクセスサイトで最も読まれるのは「都市別ガイド」「モデルコース」「交通(JRパス)ガイド」です。本パッケージは主要10地域(東京・京都・大阪・奈良・箱根富士・広島宮島・金沢・札幌北海道・福岡・沖縄)+ 2大定番記事(7日間モデルコース/交通完全ガイド)を初期搭載済みです。
- **AI検索対策**: 海外旅行者の約22%がChatGPT等で旅行情報を探すという調査があるため、AI向けサイトマップ `llms.txt` も自動生成します。

## フォルダ構成

```
tabiji/
├── TABIJI_GUI.bat            ← ★管理画面(GUI)。基本これだけでOK
├── 1_build.bat               ← サイト再生成(コマンド版)
├── 2_new_page_ai.bat         ← 新しい観光地ページを追加(AI)
├── 3_import_ai.bat           ← AIの返答を取り込んで自動でページ化
├── 4_publish.bat             ← 変更をネットに公開(git push)
├── run.sh                    ← Mac/Linux用 (./run.sh / new / import / publish)
├── config.json               ← ★最初に編集: サイトURL・アフィリエイトID
├── data/destinations.json    ← 観光地データ(3言語) ここが記事の本体
├── data/guides.json          ← ガイド記事データ(3言語)
├── build.py / ai_new_page.py / ai_import.py / tools/
├── assets/                   ← デザイン(CSS/JS)
└── docs/                     ← ★完成したサイト(これが公開される)
```

## GUI管理ツール(いちばん簡単な使い方)

`TABIJI_GUI.bat` をダブルクリック(またはコマンドで `py gui.py`)すると管理画面が開きます。以後の操作はすべてボタンで完結します:

- **① サイトを生成 / ② ブラウザでプレビュー / ③ ネットに公開(git push)**
- **📷 写真を自動取得** — Wikimedia(無料・出典自動表記)から各地の写真を最大3枚ずつ取得し、トップのカードと各ページのギャラリーに反映します。初回に一度押してください。
- **AIで新ページ作成** — 地名を入れて「A」→ 開いたAIチャットに貼り付け → 返答をコピーして「B」。四季の楽しみ方タブまで含んだ3言語ページが自動生成されます。
- config.json編集・各フォルダを開くボタンも用意しています。

従来どおり番号付き.batやコマンドでも操作できます。

## 四季タブについて

各観光地ページに「🌸春 / 🌻夏 / 🍁秋 / ❄️冬」のタブがあり、その土地ならではの季節の楽しみ方を3言語で表示します。閲覧時の季節が自動で初期選択されます(JavaScript不使用・CSSのみなので高速&SEOにも安全)。既存10地域分は収録済み、新規ページはAIプロンプトに組み込み済みです。

## セットアップ(初回のみ・約20分)

1. **Python を入れる** — https://python.org から3.8以降をインストール(Windowsは「Add python.exe to PATH」に必ずチェック)。追加ライブラリ不要、pip install も不要です。
2. **動作確認** — `1_build.bat` をダブルクリック →「OK: 39 pages」と出れば成功。`docs/index.html` をブラウザで開くとサイトが見られます。
3. **無料公開(GitHub Pages)**
   1. https://github.com で無料アカウント作成 → 「New repository」(名前は例: `japan-guide`、Public)
   2. Git をインストール(https://git-scm.com)し、このフォルダで:
      ```
      git init
      git remote add origin https://github.com/あなたのID/japan-guide.git
      git add -A && git commit -m "first" && git branch -M main && git push -u origin main
      ```
   3. GitHubのリポジトリ画面 → Settings → Pages → Branch を `main`、フォルダを `/docs` にして Save。
   4. 数分後 `https://あなたのID.github.io/japan-guide/` で公開されます。
4. **config.json を編集** — `base_url` を上記URLに変更 → `1_build.bat` → `4_publish.bat`。
   - 代替: Cloudflare Pages も無料で高速(独自ドメイン無料SSL対応)。GitHub連携で `docs` を公開フォルダに指定するだけです。

## アフィリエイト登録(すべて無料・審査は数日)

インバウンド旅行と相性が良く、直接またはASP経由で無料登録できるものを厳選しています。承認されたらIDを `config.json` の `affiliates` に貼るだけで、全ページのボタンに自動反映されます。

| プログラム | 収益源 | 登録先 | config のキー |
|---|---|---|---|
| Klook アフィリエイト | 体験・チケット・JRパス(料率高め、訪日客利用率大) | affiliate.klook.com | `klook_aid` |
| GetYourGuide Partner | 欧米客に強いツアー予約 | partner.getyourguide.com | `gyg_partner_id` |
| Agoda Partners | ホテル(韓国・台湾客の利用率が非常に高い) | partners.agoda.com | `agoda_cid` |
| Booking.com | ホテル(欧米客)※Awin経由 | awin.com | `booking_aid` |
| Airalo 等 eSIM | 渡航前に必ず買うもの=成約率高 | Impact等のASPで「Airalo」検索 | `airalo_url`(リンク丸ごと貼る) |

IDが空欄でもリンク自体は機能する(報酬が付かないだけ)ので、審査待ちの間もサイトは完成状態です。フッターの広告表示(disclosure)は3言語で自動挿入済みです。

## 運用サイクル(週1回・費用0円・約15分)

**新しい観光地ページの追加 = ボタン3回:**

1. `2_new_page_ai.bat` をダブルクリック(またはGUIで) → 地名を英語で入力(例: `Nikko`)
   - Wikipedia / Wikivoyage(無料API・キー不要)から素材を自動収集し、3言語記事生成用のプロンプトを**クリップボードに自動コピー**、ブラウザで claude.ai を開きます。
2. AIチャットに **貼り付けて送信**(無料プランでOK) → 返答のJSONを**全部コピー**。
3. `3_import_ai.bat` をダブルクリック → 自動で検証・3言語×1ページ生成・サイトマップ更新。
4. `4_publish.bat` で公開。以上です。

うまく取り込めない場合はAIの返答を `inbox/` フォルダに `.json` として保存して再実行してください。既存ページの更新も同じ手順(同じidなら上書き)です。ガイド記事は `data/guides.json` を直接編集(またはAIに同形式のJSONを書かせて貼り付け)で追加できます。

## アクセスを増やす仕組み(実装済み+やること)

**実装済み(自動):** 3言語 hreflang / canonical / sitemap.xml / robots.txt / 構造化データ(TouristDestination・Article・FAQPage=検索結果にQ&A表示) / OGP / RSS / llms.txt(AI検索対策) / 内部リンク(関連地域) / 高速静的ページ(Core Web Vitals対策) / ライブ天気・円換算ウィジェット(無料API、滞在時間・再訪率向上)。

**公開後にやること(すべて無料):**

1. **Google Search Console** に登録し sitemap.xml を送信(最重要)。
2. **Bing Webmaster Tools** に登録(GSCからインポート可。ChatGPT検索はBing系)。
3. **Naver Search Advisor**(searchadvisor.naver.com)に登録 — 韓国人旅行者はNaver検索が主流。韓国語ページを持つ本サイトの大きな武器になります。
4. **Pinterest** に無料ビジネスアカウントを作り、各ページのピンを作成 — 旅行系は Pinterest→サイト流入が長期的に効きます。
5. **Reddit**(r/JapanTravel等)で質問に回答し、役立つ時だけ自分の記事を添える。宣伝のみの投稿は逆効果。
6. 記事は「ロングテール」を狙う: 「Nikko day trip from Tokyo」「Kanazawa 2 day itinerary」のような具体的な検索語をタイトルに。AIへのプロンプトで地名の代わりにテーマを指定してもOKです。
7. アクセス解析は **GoatCounter**(無料・広告なし) — goatcounter.com でコード取得 → `config.json` の `goatcounter_code` に入れて再生成。

## 費用まとめ

| 項目 | 費用 |
|---|---|
| ホスティング(GitHub Pages / Cloudflare Pages) | 0円 |
| データ収集(Wikipedia・Wikivoyage・Open-Meteo・為替API) | 0円(キー不要) |
| 記事生成(claude.ai / ChatGPT 無料プランに手動貼り付け) | 0円 |
| 解析(GoatCounter) | 0円 |
| 独自ドメイン(任意。 .com 年1,500円前後) | 任意 |

## 注意事項

- Wikipedia/Wikimedia由来の画像はほとんどがCCライセンスですが、**公開前に各写真のクレジットリンク先(ファイルページ)でライセンスを確認**してください(出典クレジットとリンクは自動で入ります)。差し替えたい場合は data/destinations.json の photos の url を自分の写真のURLに変えるだけです。
- 写真の自動取得は、この開発環境では通信制限のため実行できませんでしたが、通常のPC・ネット環境では動作します。GUIの「📷 写真を自動取得」を一度押してから「① サイトを生成」してください。
- 収集した文章はそのまま掲載せず、AIが書き直した独自記事として掲載する設計です(コピーコンテンツはSEOで不利&権利面でも安全)。
- アフィリエイト各社の規約(リンクの rel 属性、広告表記)は実装済みですが、登録時に各社の最新規約をご確認ください。
