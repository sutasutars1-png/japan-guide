#!/usr/bin/env bash
# Daily backup of the bot's data (run by trading-bot-backup.timer as user "bot").
# 1) Always: a dated tarball of state/ and data_cache/ under /var/lib/trading-bot/backups (last 14 kept).
# 2) If BACKUP_GIT_REMOTE is set: commit the same files to that *private* repository and push.
set -euo pipefail

DATA=${TRADING_BOT_DATA:-/var/lib/trading-bot}
KEEP=${BACKUP_KEEP:-14}
stamp=$(date -u +%Y%m%dT%H%M%SZ)

mkdir -p "$DATA/backups"
tar -C "$DATA" -czf "$DATA/backups/trading-bot-$stamp.tar.gz.part" state data_cache
mv "$DATA/backups/trading-bot-$stamp.tar.gz.part" "$DATA/backups/trading-bot-$stamp.tar.gz"
ls -1t "$DATA"/backups/trading-bot-*.tar.gz | tail -n +"$((KEEP + 1))" | xargs -r rm --
echo "local backup: $DATA/backups/trading-bot-$stamp.tar.gz"

if [ -z "${BACKUP_GIT_REMOTE:-}" ]; then
  echo "BACKUP_GIT_REMOTE not set: skipping the off-server copy"
  exit 0
fi

repo="$DATA/backup-repo"
export GIT_SSH_COMMAND="ssh -i ${BACKUP_SSH_KEY:-$DATA/.ssh/backup_ed25519} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$DATA/.ssh/known_hosts"
if [ ! -d "$repo/.git" ]; then
  git clone "$BACKUP_GIT_REMOTE" "$repo" 2>/dev/null || { mkdir -p "$repo" && git -C "$repo" init -q -b main && git -C "$repo" remote add origin "$BACKUP_GIT_REMOTE"; }
fi
git -C "$repo" config user.name "trading-bot backup"
git -C "$repo" config user.email "trading-bot@localhost"
# Logs and the candle store; the dashboard HTML and rolling caches are rebuildable and skipped.
rm -rf "$repo/state" "$repo/data_cache"
mkdir -p "$repo/state" "$repo/data_cache"
shopt -s nullglob
for f in "$DATA"/state/*.json "$DATA"/state/*.jsonl; do cp -p "$f" "$repo/state/"; done
for f in "$DATA"/data_cache/*.csv; do cp -p "$f" "$repo/data_cache/"; done
git -C "$repo" add -A
if git -C "$repo" diff --cached --quiet; then
  echo "off-server copy: nothing changed"
  exit 0
fi
git -C "$repo" commit -q -m "backup $stamp"
for wait in 2 4 8 16; do
  git -C "$repo" push -q origin HEAD:main && { echo "off-server copy pushed"; exit 0; }
  sleep "$wait"
done
echo "off-server copy: push failed" >&2
exit 1
