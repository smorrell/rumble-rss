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
if %errorlevel% neq 0 (
    echo Error: Rumble RSS generation failed.
    exit /b 1
)

python ScottAdams.py
if %errorlevel% neq 0 (
    echo Error: Scott Adams RSS generation failed.
    exit /b 1
)

python azure_upload.py
if %errorlevel% neq 0 (
    echo Error: Azure Blob Storage upload failed.
    exit /b 1
)

echo.
echo Pipeline execution complete.


git add -A -- . ":(exclude,glob)**/*.mp3"
git commit -m "Update Rumble to RSS pipeline and Scott Adams extraction"
git lfs prune
git push -f
