#!/bin/bash
# AI-OS - stop (macOS / Linux)
cd "$(dirname "$0")" || exit 1

echo "AI-OS を停止しています..."
docker compose down
echo
read -n 1 -s -r -p "停止しました。何かキーを押すと閉じます..."
