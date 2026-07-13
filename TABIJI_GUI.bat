@echo off
cd /d "%~dp0"
start "" pyw gui.py 2>nul || py gui.py
