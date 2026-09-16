@echo off
cd /d "%~dp0"
where node >nul 2>&1
if errorlevel 1 (
    echo Node.js was not found on PATH.
    pause
    exit /b 1
)
node server.js
pause
