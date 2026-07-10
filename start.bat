@echo off
REM One-command launcher untuk Windows — cukup double-click file ini.
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python tidak ditemukan. Install dari https://www.python.org/downloads/
    pause
    exit /b 1
)

python start.py %*
pause
