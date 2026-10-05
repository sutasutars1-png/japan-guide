#!/usr/bin/env bash
# Pull the latest code, refresh dependencies, and restart the bot. Run as root.
set -euo pipefail
APP=/opt/trading-bot
sudo -u bot git -C "$APP/japan-guide" pull --ff-only
sudo -u bot "$APP/venv/bin/pip" install -q -r "$APP/japan-guide/trading-bot/requirements.txt"
install -m 644 "$APP"/japan-guide/trading-bot/deploy/systemd/* /etc/systemd/system/
systemctl daemon-reload
systemctl restart trading-bot.service
systemctl --no-pager status trading-bot.service | head -n 5
