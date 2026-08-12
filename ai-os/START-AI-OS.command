#!/bin/bash
# AI-OS - Execution Plane launcher (macOS / Linux)
cd "$(dirname "$0")" || exit 1

echo "============================================"
echo "   AI-OS - Execution Plane   起動中..."
echo "============================================"
echo

# --- Docker が動いているか確認 ---
if ! docker version >/dev/null 2>&1; then
  echo "[エラー] Docker が起動していません。"
  echo "  先に Docker Desktop を起動してから、もう一度このアイコンを実行してください。"
  echo
  read -n 1 -s -r -p "何かキーを押すと閉じます..."
  exit 1
fi

# --- 初回だけ .env を用意 ---
if [ ! -f .env ]; then
  cp .env.example .env
  echo ".env を作成しました（設定ファイル）。"
fi

echo "サービスを起動します（初回はイメージ構築のため数分かかります）..."
if ! docker compose up -d --build; then
  echo
  echo "[エラー] 起動に失敗しました。上のメッセージを確認してください。"
  read -n 1 -s -r -p "何かキーを押すと閉じます..."
  exit 1
fi

echo
echo "画面（Web UI）の準備を待っています..."
for i in $(seq 1 60); do
  sleep 3
  curl -s -o /dev/null http://localhost:3000 && break
done

open http://localhost:3000 2>/dev/null || xdg-open http://localhost:3000 2>/dev/null
echo
echo "============================================"
echo "  起動しました！"
echo "  画面:    http://localhost:3000"
echo "  API仕様: http://localhost:8000/docs"
echo "============================================"
echo
echo "停止するときは STOP-AI-OS.command を実行してください。"
read -n 1 -s -r -p "このウィンドウは閉じて構いません。何かキーを押すと閉じます..."
