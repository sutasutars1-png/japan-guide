@echo off
cd /d "%~dp0"
git add -A
git commit -m "update site"
git push
pause
