#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu 24.04 VPS (e.g. ConoHa VPS) for the paper-trading bot.
# Run as root:   curl -fsSL <raw URL of this file> -o setup_vps.sh && sudo bash setup_vps.sh
# Idempotent: re-running updates the code and units without losing data.
#
# Options (environment variables):
#   REPO_URL   code repository (default: the public japan-guide repository)
#   BRANCH     branch to run (default: main)
#   START=0    install everything but do not start the bot
#   HARDEN_SSH=1  disable SSH password login (only after you have logged in with a key!)
set -euo pipefail

REPO_URL=${REPO_URL:-https://github.com/sutasutars1-png/japan-guide.git}
BRANCH=${BRANCH:-main}
APP=/opt/trading-bot
DATA=/var/lib/trading-bot
SRC=$APP/japan-guide/trading-bot

[ "$(id -u)" -eq 0 ] || { echo "run as root (sudo bash setup_vps.sh)"; exit 1; }

echo "== packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q python3 python3-venv python3-pip git ufw unattended-upgrades fail2ban
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "== firewall: SSH only (the bot makes outbound connections; nothing listens)"
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw --force enable
systemctl enable --now fail2ban

if [ "${HARDEN_SSH:-0}" = "1" ]; then
  echo "== SSH: key login only"
  printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin prohibit-password\n' \
    > /etc/ssh/sshd_config.d/90-trading-bot.conf
  systemctl reload ssh
fi

echo "== user and directories"
id bot >/dev/null 2>&1 || useradd --system --home-dir "$APP" --create-home --shell /usr/sbin/nologin bot
install -d -o bot -g bot -m 750 "$APP" "$DATA" "$DATA/state" "$DATA/data_cache" "$DATA/backups" "$DATA/.ssh"

echo "== code"
if [ -d "$APP/japan-guide/.git" ]; then
  sudo -u bot git -C "$APP/japan-guide" fetch -q origin "$BRANCH"
  sudo -u bot git -C "$APP/japan-guide" checkout -q "$BRANCH"
  sudo -u bot git -C "$APP/japan-guide" pull -q --ff-only
else
  sudo -u bot git clone -q --branch "$BRANCH" "$REPO_URL" "$APP/japan-guide"
fi
[ -x "$APP/venv/bin/python" ] || sudo -u bot python3 -m venv "$APP/venv"
sudo -u bot "$APP/venv/bin/pip" install -q --upgrade pip
sudo -u bot "$APP/venv/bin/pip" install -q -r "$SRC/requirements.txt"
chmod +x "$SRC/deploy/backup.sh" "$SRC/deploy/update.sh"

echo "== configuration"
if [ ! -f /etc/trading-bot.env ]; then
  install -m 600 -o root -g root "$SRC/deploy/trading-bot.env.example" /etc/trading-bot.env
  echo "   created /etc/trading-bot.env (edit it for alerts and backups)"
fi
install -d /etc/systemd/journald.conf.d
install -m 644 "$SRC/deploy/journald-trading-bot.conf" /etc/systemd/journald.conf.d/trading-bot.conf
systemctl restart systemd-journald
install -m 644 "$SRC"/deploy/systemd/* /etc/systemd/system/
systemctl daemon-reload

# shellcheck disable=SC1091
set -a; . /etc/trading-bot.env; set +a
run_bot() { sudo -u bot --preserve-env=EXCHANGE,SYMBOL "$APP/venv/bin/python" -m trading_bot.cli "$@"; }

echo "== exchange check ($EXCHANGE $SYMBOL, read-only)"
(cd "$SRC" && run_bot exchange-check --exchange "$EXCHANGE" --symbol "$SYMBOL" --cache-dir "$DATA/data_cache")

echo "== initial history (enough for every rule setting)"
(cd "$SRC" && run_bot fetch-data --exchange "$EXCHANGE" --symbol "$SYMBOL" --cache-dir "$DATA/data_cache" --max-candles 3000)
(cd "$SRC" && run_bot data-status --exchange "$EXCHANGE" --symbol "$SYMBOL" --cache-dir "$DATA/data_cache")

systemctl enable trading-bot.service trading-bot-health.timer trading-bot-market-log.timer trading-bot-backup.timer
if [ "${START:-1}" = "1" ]; then
  systemctl restart trading-bot.service
  systemctl start trading-bot-health.timer trading-bot-market-log.timer trading-bot-backup.timer
  sleep 5
  systemctl --no-pager status trading-bot.service | head -n 8
fi
echo "== done. Logs: journalctl -u trading-bot -f"
