@echo off
echo ===================================================
echo  Running Rumble to RSS Pipeline
echo ===================================================
echo.

:: Verify ffmpeg is available in path
ffmpeg -version >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: FFmpeg is not detected in your PATH.
    echo If you just installed it, please close this window and reopen it.
    pause
    exit /b
)

python rumble_to_rss.py

echo.
echo Pipeline execution complete.
pause
