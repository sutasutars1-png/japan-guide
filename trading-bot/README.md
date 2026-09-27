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
├── self_improve/ 定期的な再最適化 + 安全ゲート付きパラメータ昇格
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

### 1. 相場データの取得(公開API、APIキー不要)

```bash
python -m trading_bot.cli fetch-data --exchange binance --symbol BTC/USDT --timeframe 1h --max-candles 3000
```

`data_cache/` にCSVとしてキャッシュされます。ネットワークが使えない環境では、
同じ列(`timestamp, open, high, low, close, volume`)を持つCSVを用意し、
以降のコマンドに `--csv path/to/file.csv` を渡してください。

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

### 5. 自己改善ループ(最適化 + ペーパートレードの継続運用)

```bash
python -m trading_bot.cli self-improve --symbol BTC/USDT --timeframe 1h \
  --strategy sma_crossover --params '{"fast_window": 10, "slow_window": 50}' \
  --iterations 0 --interval-seconds 86400 \
  --min-walk-forward-score 0.0 --min-improvement-margin 0.05
```

サイクルごとに:
1. 直近 `--history-candles` 本のデータでウォークフォワード最適化を実行
2. `walk_forward_score` が `--min-walk-forward-score` 以上、かつ現在の稼働パラメータの
   スコアより `--min-improvement-margin` 以上優れている場合のみ、パラメータを昇格
3. 昇格の有無に関わらず、`state/optimization_history_<strategy>.jsonl` に全試行を記録
   (無条件のパラメータ切り替えは行わない、監査可能な仕組み)

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
