@echo off
chcp 65001 >nul
title AI-OS - Execution Plane
cd /d "%~dp0"

echo ============================================
echo    AI-OS - Execution Plane   起動中...
echo ============================================
echo.

REM --- Docker が動いているか確認 ---
docker version >nul 2>&1
if errorlevel 1 (
  echo [エラー] Docker が起動していません。
  echo   先に「Docker Desktop」を起動してから、もう一度このアイコンを実行してください。
  echo.
  pause
  exit /b 1
)

REM --- 初回だけ .env を用意 ---
if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo .env を作成しました（設定ファイル）。
)

echo サービスを起動します（初回はイメージ構築のため数分かかります）...
docker compose up -d --build
if errorlevel 1 (
  echo.
  echo [エラー] 起動に失敗しました。上のメッセージを確認してください。
  pause
  exit /b 1
)

echo.
echo 画面（Web UI）の準備を待っています...
set /a tries=0
:waitloop
timeout /t 3 /nobreak >nul
curl -s -o nul http://localhost:3000 && goto ready
set /a tries+=1
if %tries% lss 60 goto waitloop

:ready
start "" http://localhost:3000
echo.
echo ============================================
echo   起動しました！
echo   画面:      http://localhost:3000
echo   API仕様:   http://localhost:8000/docs
echo ============================================
echo.
echo 停止するときは「STOP-AI-OS.bat」を実行してください。
echo このウィンドウは閉じて構いません。
pause
