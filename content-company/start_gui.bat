@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem Python ランチャを検出（py 優先、無ければ python）
where py >nul 2>nul && (set "PY=py") || (set "PY=python")

echo ============================================
echo   AI会社 OS - ローカル GUI を起動します
echo   URL : http://127.0.0.1:8787/
echo   停止: この黒い画面で Ctrl+C / ウィンドウを閉じる
echo ============================================
echo.

rem サーバ起動を少し待ってから既定ブラウザを開く
start "" /min cmd /c "timeout /t 2 >nul & start "" http://127.0.0.1:8787/"

rem GUI サーバ起動（127.0.0.1 束縛・標準ライブラリのみ）
%PY% -m company gui

echo.
echo GUI を終了しました。
pause
