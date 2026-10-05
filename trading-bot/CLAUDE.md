# trading-bot 開発ルール

## 作業の前に

1. `ROADMAP.md` を読み、依頼がどのフェーズのどの項目にあたるかを確認する
2. 依頼が現在のフェーズの外にある、または「開発の原則」に反する場合は、実装する前に
   その旨と理由をユーザーに伝え、進め方を確認する(例: フェーズ6の基準を満たす前の実発注、
   人が手で戦略パラメータを決める変更、1時間足より長い足への切り替え)

## 作業の後に

- 完了したロードマップ項目は、同じコミットで `ROADMAP.md` のチェック・状態・「現在地」を更新する
- 優先順位や方針が変わったら `ROADMAP.md` の「更新履歴」に日付と理由を残す
- 検証結果の数値は README とロードマップの両方に反映する(不利な結果も残す)

## 守ること

- 実際の注文を出すコードは書かない(ペーパートレードのみ。`ROADMAP.md` フェーズ6参照)
- 戦略・ルールを変えたら `replay` で自己改善 / 固定 / バイ&ホールドを比較してから採否を決める
- 判断は確定済みのデータだけで行う(先読みしない)
- 保存データ(`data_cache/`, `seed_data/`)を上書きで失わない
- コミット前に `pytest -q` を通す

## よく使うコマンド

```bash
cd trading-bot
pip install -r requirements.txt
pytest -q
python -m trading_bot.cli data-status --exchange kraken --symbol BTC/USD
python -m trading_bot.cli import-csv --exchange kraken --symbol BTC/USD --file seed_data/kraken_BTC-USD_1h.csv
python -m trading_bot.cli replay --exchange kraken --symbol BTC/USD --export-json state/replay.json
```
