# trading-bot — 自己改善型・暗号資産トレードbot(ペーパートレード)

**⚠️ 重要な注意事項(必ずお読みください)**

- **本ソフトウェアは現時点でペーパートレード専用です。** どのコマンドを実行しても、
  実際の取引所に注文を発注するコードパスは一切存在しません(`PaperTrader` /
  `Portfolio` は仮想の現金・ポジションを管理するのみで、`ccxt` は
  `fetch_ohlcv`(公開の相場データ取得)以外のAPI呼び出しを行いません)。
- バックテスト・最適化結果は過去データに基づくシミュレーションであり、**将来の
  利益を保証するものではありません**。手数料・スリッページ・約定拒否・取引所障害
  など実運用特有のリスクは簡略化されたモデルでしか考慮していません。
- 将来的に実資金での自動発注(実弾)を検討する場合は、本READMEの設計上の理由から
  **相応の追加実装(注文実行層・リスク管理・監視・法規制対応)と、十分な検証期間
  が必須**です。実装なしに実弾運用を始めないでください。
- 投資判断は自己責任で行ってください。本ソフトウェアは金融アドバイスではありません。

## これは何か

過去データに基づくバックテストで戦略パラメータを検証し、**ウォークフォワード
最適化**(過去の複数期間で「訓練→検証」を繰り返し、汎化性能を確認する手法)で
過学習を避けながらパラメータを自動更新していく、暗号資産(スポット・ロングオンリー)
向けのペーパートレードbotです。「自己改善」とは、一定間隔でこの最適化を再実行し、
検証済みの安全条件を満たした場合のみ、稼働中のパラメータを更新することを指します
(無条件のパラメータ切り替えは行いません)。

## アーキテクチャ

```
trading_bot/
├── data/        OHLCV取得(ccxt, 公開エンドポイントのみ)+ CSVキャッシュ
├── strategy/    戦略インターフェース + SMAクロスオーバー戦略
├── backtest/    ベクトル化バックテストエンジン + 指標(Sharpe/DD/勝率等)
├── optimize/    ウォークフォワード・グリッドサーチ最適化
├── paper/       仮想ポートフォリオ + ペーパートレードループ(実発注なし)
├── self_improve/ 定期的な再最適化 + 安全ゲート付きパラメータ昇格 + 過去データでのリプレイ検証
└── cli.py       上記すべてのコマンドラインエントリポイント
```

各コンポーネントは独立してテスト可能な形で疎結合になっています(例:
`PaperTrader` はデータ取得元を関数として注入するため、ネットワークなしで
テストできます)。

## セットアップ

```bash
cd trading-bot
pip install -r requirements.txt
cp config.example.yaml config.yaml   # 現状 config.yaml は参考用(CLI引数が優先)
```

## 使い方

### 1. 相場データ(公開API、APIキー不要)— 保存して積み上げる

取引所のローソク足APIは遡れる本数に上限があります(Kraken は直近約720本 = 1h足で約30日)。
そこで履歴は毎回取り直すのではなく **`data_cache/` のストアに保存し、統合して積み上げます**。

```bash
# 最新の足をストアに統合(古い足は消さない)。bot稼働中は毎バー自動で行われる
python -m trading_bot.cli fetch-data --exchange kraken --symbol BTC/USD

# 720本より古い期間を、Kraken の公開約定履歴(Trades)から1h足に再構成して補完
# 中断しても再実行すれば欠けている期間だけを続きから埋める(1秒1回ペース)
python -m trading_bot.cli backfill --exchange kraken --symbol BTC/USD --days 180

# Kraken 公式の一括ダウンロード(OHLCVT CSV)があれば取り込み可能
python -m trading_bot.cli import-csv --exchange kraken --symbol BTC/USD --file XBTUSD_60.csv --format kraken-ohlcvt

# ストアの期間・欠損・データ出所を確認
python -m trading_bot.cli data-status --exchange kraken --symbol BTC/USD
```

- 各足には出所(`exchange_ohlc` / `exchange_csv` / `trades` / `gap_fill`)を記録し、
  同じ時刻では優先度の高い出所が勝ちます(約定からの再構成が公式足を上書きすることはない)
- 約定から再構成した足は、公式OHLCと重なる48本で始値・高値・安値・終値が完全一致することを確認済み
  (出来高は最大2%程度の差。戦略は価格のみ使用)
- 約定が1件もない時間帯は直前の終値を引き継ぎ、出来高0の `gap_fill` として記録
- 取得期間を延ばすために長い足(4h・日足)に切り替える必要はなく、1h足のまま取引機会を維持できます

ストアのCSVは `--csv data_cache/kraken_BTC-USD_1h.csv` としてそのまま各コマンドに渡せます。

### 2. バックテスト

```bash
python -m trading_bot.cli backtest --symbol BTC/USDT --timeframe 1h \
  --strategy sma_crossover --params '{"fast_window": 10, "slow_window": 50}'
```

`total_return / cagr / sharpe / max_drawdown / win_rate / num_trades` を出力します。

### 3. パラメータ最適化(ウォークフォワード)

```bash
python -m trading_bot.cli optimize --symbol BTC/USDT --timeframe 1h \
  --strategy sma_crossover --n-splits 4
```

- `walk_forward_score`: 「過去に同じ手順で再最適化していたら、実際どうだったか」を
  示すアウトオブサンプルの平均スコア。この値がバックテスト結果の信頼性の指標です。
- `final_params`: 全期間データで再グリッドサーチした、次に使うべきパラメータ候補。

### 4. ペーパートレード(実発注なし)

```bash
python -m trading_bot.cli paper-trade --symbol BTC/USDT --timeframe 1h \
  --strategy sma_crossover --params '{"fast_window": 10, "slow_window": 50}' \
  --iterations 0 --sleep-seconds 3600   # 0 = 無限ループ(1時間ごとに判定)
```

`state/portfolio_<symbol>.json` に仮想ポートフォリオ、
`state/decisions_<symbol>.jsonl` に毎回の判断ログが保存されます。

### 5. 自己改善システム(自動運用)

パラメータは人が手で調整せず、システムが決められたスケジュールとルールで自動更新します。

```bash
python -m trading_bot.cli self-improve --exchange kraken --symbol BTC/USD --timeframe 1h \
  --params '{"fast_window": 10, "slow_window": 50}' \
  --steps 0 --step-seconds 3600 --reoptimize-every 24 \
  --history-candles 1440 --n-splits 4 --min-trades 5 \
  --min-walk-forward-score 0.0 --min-improvement-margin 0.05
```

- **毎バー(1時間ごと)** に稼働中パラメータで売買判断(ペーパートレード)
- **`--reoptimize-every` バーごと(既定24 = 1日1回)** に再最適化サイクルを実行:
  1. 直近 `--history-candles` 本でウォークフォワード最適化 → 挑戦者(候補)を選出
  2. 現行パラメータ(防衛者)を **同じデータ・同じ検証区間で毎回再採点**
  3. 以下のゲートを全て通過した場合のみ昇格(`decide()`):
     有効な候補がある / 検証スコアが `--min-walk-forward-score` 以上 /
     現行と異なる / 現行の再採点スコアを `--min-improvement-margin` 以上上回る
  4. 結果は昇格の有無に関わらず `state/optimization_history_<strategy>.jsonl` に理由コード付きで記録
- 再起動時は `state/active_params_<strategy>.json` の最後に昇格したパラメータから再開
- 学習に使う直近1440本(60日)は Kraken の1h足APIの上限(約720本)を超えるため、
  先に `backfill` でストアを延ばしておくこと(稼働中は毎バー自動で追記される)

### 6. 自己改善システム自体の検証(リプレイ)

「自己改善を入れたら本当に良くなるのか」を、実運用と **同じ判定ロジック** で過去データ上に
1本ずつ再現して確かめます。各サイクルはその時点までのデータしか見ません(先読みなし)。

```bash
python -m trading_bot.cli replay --exchange kraken --symbol BTC/USD \
  --history-candles 1440 --reoptimize-every 24 --export-json state/replay.json
```

自己改善システム / 初期パラメータ固定 / バイ&ホールドの3本を同じ期間で比較し、
全サイクルの判定(候補・スコア・昇格/却下理由)を出力します。

#### 180日分(2026-04〜09, Kraken BTC/USD 1h, 開始 10/50, 24本ごと)での検証結果

| 学習本数 | 分割 | 最低取引 | 昇格/サイクル | 自己改善 | Sharpe | 最大DD |
|---:|---:|---:|---:|---:|---:|---:|
| 360 | 3 | 3 | 4/166 | +17.4% | 1.34 | -15.2% |
| 360 | 4 | 5 | 0/166 | +14.0% | 1.13 | -15.4% |
| 720 | 3 | 3 | 9/151 | +12.4% | 0.97 | -18.5% |
| 720 | 4 | 5 | 2/151 | +25.8% | 1.86 | -10.3% |
| 1440 | 3 | 3 | 2/121 | +20.3% | 1.53 | -13.1% |
| **1440** | **4** | **5** | **6/121** | **+22.2%** | **1.66** | **-13.3%** |

比較: 開始パラメータ固定 +14.0%(Sharpe 1.13)/ バイ&ホールド +22.3%(12通り中の抜粋。全体では自己改善が固定を上回ったのは10通り、バイ&ホールドを上回ったのは1通り)。

- 既定値(太字)は成績最大の設定ではなく、学習1440本の4通りがいずれも固定以上で安定していたこと、
  検証区間が360本あり最低取引5件を満たせることから選んでいる。最良の設定を選ぶこと自体が過剰最適化になるため
- 上昇相場ではロングオンリーのSMAクロスはバイ&ホールドに届きにくい。自己改善の効果は「固定パラメータより良い」の範囲
- 取引回数は180日で50〜70回(週2〜3回)。1h足のまま取引機会を維持している

## テスト

```bash
pip install -r requirements.txt
pytest -q
```

ネットワークアクセスなしで完結します(合成データ・CSVのみ使用)。

## 既知の制約・今後の検討事項

- 長期(ロング)のみ、単一銘柄、成行相当の約定モデル(手数料はターンオーバーに
  比例するドラッグとしてのみ考慮、スリッページ・板の厚み・部分約定は未考慮)。
- 戦略はSMAクロスオーバーのみ実装。`trading_bot/strategy/base.py` の
  `Strategy` を継承すれば新戦略を追加でき、`STRATEGIES` レジストリに登録するだけで
  CLI・最適化・自己改善ループ全てから利用可能。
- 実弾発注(実際の注文実行)は意図的に未実装です。追加する場合は、本READMEの
  「重要な注意事項」を踏まえ、最小限のスコープ・明示的な承認フロー・監視/停止機構を
  併せて設計してください。
