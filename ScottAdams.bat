@echo off
setlocal
cd /d "%~dp0"

echo Extracting Scott Adams episodes...
python ScottAdams.py

if errorlevel 1 (
    echo.
    echo Extraction failed.
    pause
    exit /b 1
)

echo.
echo ScottAdams.xml created successfully.
pause
