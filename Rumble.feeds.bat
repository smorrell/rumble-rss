@echo off
setlocal
set "PIPELINE_EXIT=0"
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
    set "PIPELINE_EXIT=1"
    goto finalize
)

python rumble_to_rss.py
if %errorlevel% neq 0 (
    echo Error: Rumble RSS generation failed.
    set "PIPELINE_EXIT=1"
    goto finalize
)

python ScottAdams.py
if %errorlevel% neq 0 (
    echo Error: Scott Adams RSS generation failed.
    set "PIPELINE_EXIT=1"
    goto finalize
)

python azure_upload.py
if %errorlevel% neq 0 (
    echo Error: Azure Blob Storage upload failed.
    set "PIPELINE_EXIT=1"
    goto finalize
)

:finalize
echo.
if "%PIPELINE_EXIT%"=="0" echo Pipeline execution complete.

git add -A -- . ":(exclude,glob)**/*.mp3"
if errorlevel 1 (
    echo Error: Could not stage files.
    set "PIPELINE_EXIT=1"
) else (
    git commit -m "Update Rumble to RSS pipeline and Scott Adams extraction"
    if errorlevel 1 (
        echo Error: Git commit failed.
        set "PIPELINE_EXIT=1"
    )
)
git lfs prune
git push -f
if errorlevel 1 (
    echo Error: Git push failed.
    set "PIPELINE_EXIT=1"
)
exit /b %PIPELINE_EXIT%
