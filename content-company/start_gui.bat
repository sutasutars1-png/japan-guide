@echo off
cd /d "%~dp0"

rem Python launcher: prefer py, fall back to python
where py >nul 2>nul && (set "PY=py") || (set "PY=python")

echo ==========================================
echo   AI Kaisha OS - Local GUI
echo   URL : http://127.0.0.1:8787/
echo   LLM ON/OFF : checkbox at the top-left
echo   Stop       : close this window
echo ==========================================
echo.

rem Open the default browser a couple seconds after the server starts
start "" /min cmd /c "timeout /t 2 >nul & start http://127.0.0.1:8787/"

rem Start the GUI server (bound to 127.0.0.1, stdlib only)
%PY% -m company gui

echo.
pause
