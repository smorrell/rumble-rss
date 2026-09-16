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
python extract_scott_adams.py

echo.
echo Pipeline execution complete.


git add .
git commit -m "Update Rumble to RSS pipeline and Scott Adams extraction"
git push -f
