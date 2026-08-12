@echo off
chcp 65001 >nul
title AI-OS - 停止
cd /d "%~dp0"

echo AI-OS を停止しています...
docker compose down
echo.
echo 停止しました。このウィンドウは閉じて構いません。
pause
