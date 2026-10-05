# ConoHa VPS で bot を24時間動かす手順

bot は **ペーパートレード専用** です(SoDEX の公開データで判断し、仮想の口座で売買を記録します)。
VPS には秘密鍵もAPIキーも置きません。SoDEX へ実際の注文を出すコードはありません(`ROADMAP.md` 原則1)。

## 全体像

| 置き場所 | 中身 |
|---|---|
| `/opt/trading-bot/japan-guide` | このリポジトリ(コード。`update.sh` で更新) |
| `/opt/trading-bot/venv` | Python の実行環境 |
| `/var/lib/trading-bot/state` | 判断ログ・仮想口座・自己改善の記録・ダッシュボード・取引所の記録 |
| `/var/lib/trading-bot/data_cache` | SoDEX の1時間足(毎時追記) |
| `/var/lib/trading-bot/backups` | 毎日のバックアップ(直近14日分) |
| `/etc/trading-bot.env` | 設定(通知先・バックアップ先・追加の引数) |

| systemd ユニット | 役割 |
|---|---|
| `trading-bot.service` | bot 本体。足の確定ごとに判断し、1日1回再最適化。落ちたら30秒後に自動で再起動 |
| `trading-bot-health.timer` | 30分ごとに確認し、判断が2時間以上止まったら通知(再開したらもう1回通知) |
| `trading-bot-market-log.timer` | 毎時、SoDEX の手数料・資金調達率・気配を記録(`state/market_log.jsonl`) |
| `trading-bot-backup.timer` | 毎日 03:30(UTC)にバックアップ |

## 1. 契約時に選ぶもの

- **OS**: Ubuntu 24.04
- **プラン**: メモリ1GBで動きます(`--committee` を使うなら2GB以上を推奨)。ディスクは最小構成で足ります
- **リージョン**: 東京
- **SSHキー**: 作成画面で公開鍵を登録する(パスワードログインより安全)
- **セキュリティグループ**: SSH(22番)を許可するものを選ぶ。bot は外へ接続するだけなので、他のポートは開けない

## 2. 初期設定(1コマンド)

VPS に root で SSH ログインして実行します。

```bash
curl -fsSL https://raw.githubusercontent.com/sutasutars1-png/japan-guide/main/trading-bot/deploy/setup_vps.sh -o setup_vps.sh
sudo bash setup_vps.sh
```

行うこと:
- パッケージ更新と自動セキュリティ更新
- ファイアウォール(SSH以外を遮断)と fail2ban(総当たり対策)
- 専用ユーザー `bot` の作成、コードの取得、Python 環境の作成
- SoDEX への接続確認(`exchange-check`。手数料・資金調達率・最新足を表示)
- 履歴の取得(3,000本)
- 全ユニットの登録と起動

何度実行しても、データは消えません。

SSH キーでログインできることを確認したら、パスワードログインを止めます:

```bash
sudo HARDEN_SSH=1 START=0 bash setup_vps.sh
```

## 3. 設定(`/etc/trading-bot.env`)

```bash
sudo nano /etc/trading-bot.env
sudo systemctl restart trading-bot
```

| 項目 | 内容 |
|---|---|
| `EXCHANGE` / `SYMBOL` | 既定 `sodex` / `BTC-USD`(SoDEX 本番の BTC 無期限先物) |
| `BOT_EXTRA_ARGS` | `self-improve` への追加引数。例: SoDEX の実際の手数料に合わせる `--fee-rate 0.0001` |
| `TRADING_BOT_WEBHOOK_URL` | Discord または Slack の Webhook URL。停止・再開の通知が届く |
| `BACKUP_GIT_REMOTE` | バックアップ先の**非公開**リポジトリ(下記)。空ならVPS内のバックアップのみ |

**手数料と金利の合わせ方**: 初期設定の出力(または `state/market_log.jsonl`)にある
`maker_fee`(指値の手数料)と `funding_rate`(資金調達率)を確認し、`BOT_EXTRA_ARGS` の
`--fee-rate` と `--carry-rate-per-day` を実際の値に近づけます。資金調達率の計算間隔
(1時間ごとか8時間ごとか)は SoDEX の資料で確認してください。この開発環境からは
SoDEX に接続できなかったため、実際の値はまだ確認していません。

## 4. 毎日のバックアップを VPS の外にも置く(任意)

コードのリポジトリ(japan-guide)は**公開**なので、ここには絶対にバックアップしません。

1. GitHub に**非公開**リポジトリを作る(例: `trading-bot-data`)
2. VPS で bot 専用の鍵を作る:
   ```bash
   sudo -u bot ssh-keygen -t ed25519 -N "" -f /var/lib/trading-bot/.ssh/backup_ed25519
   sudo cat /var/lib/trading-bot/.ssh/backup_ed25519.pub
   ```
3. そのリポジトリの Settings → Deploy keys に公開鍵を登録し、「Allow write access」にチェック
4. `/etc/trading-bot.env` に `BACKUP_GIT_REMOTE=git@github.com:<ユーザー名>/trading-bot-data.git` を設定
5. 試しに実行: `sudo systemctl start trading-bot-backup && journalctl -u trading-bot-backup -n 20`

## 5. 日々の操作

```bash
systemctl status trading-bot                 # 動いているか
journalctl -u trading-bot -f                 # 判断の記録をリアルタイムで見る
systemctl list-timers 'trading-bot*'         # 監視・記録・バックアップの予定
sudo /opt/trading-bot/japan-guide/trading-bot/deploy/update.sh   # コードを最新にして再起動
sudo systemctl stop trading-bot              # 止める(start で再開。判断ログから続きを再開する)
```

ダッシュボードは再最適化のたび(1日1回)に `/var/lib/trading-bot/state/dashboard.html` に
書き出されます。手元のPCに取ってきて開きます:

```bash
scp root@<VPSのIP>:/var/lib/trading-bot/state/dashboard.html .
```

## 注意

- 2年分の検証で、現在の戦略に手数料・金利を上回る優位性は見つかっていません(`README.md` 冒頭)。
  VPS での稼働は、実地のデータ(ペーパートレードの成績と SoDEX の実際のコスト)を集めるためのものです
- VPS に秘密鍵・APIキー・ウォレットを置かないでください。このbotには不要です
