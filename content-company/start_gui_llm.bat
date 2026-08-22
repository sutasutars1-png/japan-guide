@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem Python ランチャを検出（py 優先、無ければ python）
where py >nul 2>nul && (set "PY=py") || (set "PY=python")

echo ============================================
echo   AI会社 OS - GUI 起動（実 LLM 生成 ON）
echo   URL : http://127.0.0.1:8787/
echo   前提: この PC に claude(Claude Code CLI) が入り
echo         サブスクでログイン済みであること（APIキー不要）
echo   停止: この黒い画面で Ctrl+C / ウィンドウを閉じる
echo ============================================
echo.

rem サーバ起動を少し待ってから既定ブラウザを開く
start "" /min cmd /c "timeout /t 2 >nul & start "" http://127.0.0.1:8787/"

rem GUI サーバ起動（--llm で実 LLM 生成を有効化。未検出時は雛形にフォールバック）
%PY% -m company gui --llm

echo.
echo GUI を終了しました。
pause
