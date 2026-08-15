@echo off
chcp 65001 >nul
title AI-OS - Claude統括モード
cd /d "%~dp0"

echo ============================================
echo    AI-OS - Claude統括モード（ローカルCLI）
echo ============================================
echo.
echo このモードは api を「あなたのPC」で起動し、ログイン済みの
echo claude をそのまま使います（サブスク・API課金なし）。
echo UIの使い方は通常どおり: ブラウザでゴールを入力するだけです。
echo.

REM --- 前提チェック: Docker / claude / python ---
docker version >nul 2>&1
if errorlevel 1 (
  echo [エラー] Docker Desktop が起動していません。先に起動してください。
  pause & exit /b 1
)
where claude >nul 2>&1
if errorlevel 1 (
  echo [エラー] claude CLI が見つかりません。
  echo   Claude Code をインストールし、このPCでログインしてください。
  pause & exit /b 1
)
where python >nul 2>&1
if errorlevel 1 (
  echo [エラー] Python が見つかりません（api はPythonで動きます）。
  echo   https://www.python.org/downloads/ から 3.11+ を入れてください
  echo   （インストール時に「Add python.exe to PATH」にチェック）。
  pause & exit /b 1
)

if not exist ".env" ( copy ".env.example" ".env" >nul & echo .env を作成しました。 )

echo [1/3] Docker で db と web を起動（api はホストで動かすので除外）...
docker compose stop api >nul 2>&1
docker compose up -d --no-deps --build db web
if errorlevel 1 ( echo [エラー] db/web の起動に失敗しました。 & pause & exit /b 1 )

echo [2/3] 依存パッケージを確認（初回のみ時間がかかります）...
cd apps\api
python -m pip install -q -r requirements.txt

echo [3/3] api をこのPCで起動します（claude を使用）。ブラウザを開きます...
start "" http://localhost:3000
echo.
echo ============================================
echo   画面: http://localhost:3000
echo   Agents で Planner の Model を「claude-cli」にすると
echo   統括AIがローカルClaude（サブスク・自動）になります。
echo   ワーカーは Gemini（Connectionsでキー登録）。
echo ============================================
echo   このウィンドウが api のログです。閉じると api が止まります。
echo   db/web を止めるには: STOP-AI-OS.bat
echo.
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
