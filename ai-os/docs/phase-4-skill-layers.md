# Phase 4 設計補遺 — 層構造スキルDB(Layered Skill Database)

> ステータス: **設計のみ(未実装)**。`phase-4-design.md` のスキルモデルを拡張・更新する。
> 出典: ユーザー提供の3ドキュメント(Master Data / Token Optimization Overlays /
> System Architecture Guidelines)を正式に取り込む。既存のフラットな Skill 概念を、
> 直交する層の合成モデルへ置き換える。

## 0. 確定した方針(ユーザー決定)

1. **層構造へ作り替える**。既存の実行スキル(build.small_steps 等)は「実行層」として残す。
2. **職種レンズ25は全部ライブラリに入れる**(汎用重視)。ただし**トークン肥大化を避ける
   ため、常時使用 / 呼び出し方の工夫 / 選択、のどれにするかは別途検討(下記 §5 で保留)**。
3. **合成表示はユーザーのわかりやすさ最優先**。生XMLではなく、日本語の見出し付き
   セクションで組み立てる(コードIDは管理・書き出し用に保持)。

## 1. 層モデル(直交する軸の合成)

エージェントの system プロンプトは、少数の部品の掛け合わせで作る。軸は独立(直交):

| 層 | 由来 | 意味 | 選ぶ数 | ID接頭 |
|---|---|---|---|---|
| **工程 (stage)** | 我々 | フローのどの位置か(Planner→Builder→Reviewer…) | 1 | — |
| **思考モード (thinking)** | 提供Layer1 | どう考えるか(分析/構想/設計/評価/意思決定) | 1 | `BASE-` |
| **専門レンズ (domain)** | 提供Layer2 | どの専門視点か(SW/データ/法務/PM…25種) | 0〜n | `DOM-` |
| **実行 (execution)** | 我々 | サンドボックスでの振る舞い(小さく実行/完了前テスト…) | 0〜n | `exec.` |
| **オーバーレイ (overlay)** | 提供Layer3 | 手法/規約/出力形式/トークン最適化 | 0〜n | `OVR-` |
| **応答ルール (protocol)** | 我々(システム所有) | RUN:/DONE: の封筒・ハンドオフ規約 | 固定 | — |

> **用語の衝突を解消**: 提供資料の「職種(role)」= **専門レンズ(domain)**、
> 我々の「役割」= **工程(stage)**。別軸なので併存する(例: Builder × DOM-DATA × BASE-SYS)。

## 2. 取り込む内容(提供DB → ライブラリ)

- **思考モード(5)**: `BASE-ANA` 分析 / `BASE-GEN` 構想 / `BASE-SYS` 設計 /
  `BASE-EVAL` 評価 / `BASE-DEC` 意思決定。
- **専門レンズ(25)**: `DOM-SW` `DOM-INF` `DOM-DATA` … `DOM-ESG`(提供資料の全25種を収録)。
- **オーバーレイ(手法/規約/形式)**: `OVR-METH-*`(アジャイル/3C/RICE)、`OVR-GOV-*`
  (OWASP/GDPR/WCAG)、`OVR-BIZ-*`、`OVR-FMT-*`(Execサマリ/JIRA/JSON/批判)。
- **トークン最適化オーバーレイ**: `OVR-OPT-MIN`(前置き禁止・最小出力) /
  `OVR-OPT-DATA`(純データ) / `OVR-OPT-SUM`(履歴要約)。
- **実行層(我々の既存)**: `exec.small_steps` `exec.test_before_done` `exec.inspect_first`
  … (現 `app/skills.py` の内容を execution 層として維持)。
- **コードID体系を採用**(`BASE-/DOM-/OVR-/exec.`)。管理・エクスポート・参照に使う。

## 3. 合成(ユーザーにわかりやすい日本語セクション)

LLMへ渡す system プロンプトは、生タグではなく**見出し付きセクション**で組む。
コードIDは編集画面での管理に使い、合成結果は読みやすさ優先:

```
# 役割（工程）
<stage の役割テキスト>

# 思考モード — 設計・構造化
<BASE-SYS の内容>

# 専門レンズ — データ/AI
<DOM-DATA の内容>

# 実行の手順
<exec.small_steps / exec.test_before_done …>

# 追加の方針
<OVR-FMT-EXEC / OVR-OPT-MIN …>

──────── 以下はシステムが管理（変更不可）────────
# 応答ルール
<RUN:/DONE: ループ規約 ＝ 最後・最優先・不可侵>
```

- **protocol は最後・最優先で固定**。オーバーレイは"内容の形"を変えるが、"封筒(RUN:/DONE:)"は
  変えさせない。`OVR-OPT-MIN`(前置き禁止)を使っても DONE 報告の封筒は残す、と規約側に一行明記。
- **既定は最小構成**(思考1・レンズ0〜2・overlay少数)。層の盛りすぎ=トークン肥大に注意。

## 4. preset / 副スキルへの接続

- **主スキル(preset)** = 各層の選択の束(工程・思考1・レンズ群・実行群・overlay群・権限)。
  **複数プリセット切替**＋「**プリセットに戻す**」。
- **副スキル(overlay)** = その都度の追加(project / run スコープ)。土台を汚さない。
- **権限(capability)は別レイヤ**(Default Deny)。スキルは"やり方"のみで権限を広げない。

## 5. 【保留・要検討】専門レンズ25の使い方(トークン肥大対策)

全25をライブラリに入れる一方、**プロンプトに毎回全部載せない**ための呼び出し方を後で決める。
候補:

| 方式 | 概要 | 長所 | 短所 |
|---|---|---|---|
| A. 常時使用 | 選択したレンズを常にプロンプトへ | 単純 | 数が増えると肥大 |
| B. 手動選択 | エージェント/ゴールごとに人が選ぶ(=preset/副) | 予測可能・軽量 | 人手 |
| C. 動的呼び出し | ゴールから関連レンズを自動選定(分類/検索) | 25+でも軽量 | 選定ステップが要る |
| D. ハイブリッド | 既定は最小＋関連候補を自動提案→人が確認 | 軽量＋精度 | 実装やや複雑 |

**暫定推奨**: MVPは **B(手動選択)** で軽く始め、将来 **D(ハイブリッド)** へ。
(C/D の"自動選定"は安価モデルやキーワード一致で実現可能=Doc3のルーティングと接続)

## 6. Doc3(システム側の最適化)= プロンプトでなく実装

提供資料 Doc3 は**プロンプト文でなくシステム/APIの実装要件**。我々の「システム層 vs
プロンプト層」の分離を裏付ける。最適化バックログとして段階投入:

| 項目 | 現状 | 時期 |
|---|---|---|
| max_tokens 上限 | ✅ 実装済み | 済 |
| 出力の足切り(直近N行) | ✅ ループで実装(40行) | 済 |
| スライディングウィンドウ(履歴窓化) | 部分 | 近 |
| 中間推論/ツール履歴の非表示(context editing) | 未 | 中 |
| `OVR-OPT-SUM` による履歴要約チェックポイント | 未 | 中 |
| モデルルーティング(安価↔高性能) | agent毎modelは可 | 中(自動化は将来) |
| プロンプトキャッシュ(provider依存) | 未 | 後 |
| stop_sequences(JSON打切り) | 未 | 小さく可 |

> 注: Doc3 のモデル例(Claude3.5/GPT-4o)は古い。採用するのは**ルーティングの概念**で、
> モデル名は現行(Gemini無料/Opus等)に置換する。

## 7. データモデル素案(シリアライズ可能・エクスポート前提)

```jsonc
// Skill（層で型付け）
{ "id": "DOM-DATA", "layer": "domain", "name": "データ・AI",
  "description": "統計的妥当性/バイアス/再現性/予測精度のレンズ",
  "content": "…", "roles": ["Researcher","Builder"] }   // roles=推奨工程(絞込用・任意)

{ "id": "BASE-SYS",  "layer": "thinking", "name": "設計・構造化", "content": "…" }
{ "id": "OVR-OPT-MIN","layer": "overlay",  "name": "最小出力",   "content": "…" }
{ "id": "exec.small_steps","layer": "execution","name": "小さく実行して検証","content": "…" }

// Preset（主スキル・複数・戻せる）
{ "id": "preset_builder_data", "name": "Builder / データ分析", "stage": "Builder",
  "thinking": "BASE-SYS", "domains": ["DOM-DATA"],
  "execution": ["exec.small_steps","exec.test_before_done","exec.inspect_first"],
  "overlays": ["OVR-OPT-MIN"], "capabilities": ["shell.execute","filesystem.write"] }

// Agent（Presetを選び、副overlayを重ねる）
{ "id":"a_builder","name":"Builder","provider":"gemini",
  "active_preset":"preset_builder_data",
  "base_working_copy": { /* 編集中。プリセットに戻せる */ },
  "overlay_skills":[ {"skill_id":"OVR-FMT-JSON","scope":"run"} ] }
```

全体は Template/Export に含めて書き出し → 別PCで復元(= 環境コピー商品の中身)。

## 8. 実装ステージング(この補遺に沿って)

1. **スキルDBを層構造へ再構成**(`layer` 付与、`BASE-/DOM-/OVR-/exec.` 収録、`/skills?layer=` 追加)。
2. **compose_system を層合成へ**(§3 の日本語セクション、protocol は最後・不可侵)。
3. **preset(複数・戻せる)＋副スキル(project/run)**、Agents/Skills 画面の編集UI。
4. **専門レンズの使い方(§5)を決めて実装**(まず B、将来 D)。
5. Doc3 の最適化(§6)を優先度順に。

各ステージ完了時に `docs/phase-4-*.md` を Implementation/Tests/Security/Known/Next 形式で記録。

## 9. ガードレール(不変の原則)

- **応答ルール(protocol)はシステム所有・最後・最優先**。overlayに侵させない。
- **権限(Default Deny)はスキルと別**。スキルは権限を広げない。
- **既定は最小構成**でトークンを抑える(§5 の方式で肥大を制御)。
- スキルは**データ**。編集は次回実行から反映、テンプレートで書き出せる。
