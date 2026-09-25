@echo off
echo ===================================================
echo  Installing Dependencies (Python, FFmpeg, yt-dlp)
echo ===================================================
echo.

echo [1/4] Installing FFmpeg via winget...
winget install --id=Gyan.FFmpeg -e
if %errorlevel% neq 0 (
    echo Winget installation failed or FFmpeg is already installed.
)

echo.
echo [2/4] Checking for Python updates via winget...
winget upgrade --id=Python.Python.3.14.7 -e --accept-source-agreements --accept-package-agreements
if %errorlevel% neq 0 (
    echo Python is already up to date, or no Python update was found.
)

echo.
echo [3/4] Installing Node.js LTS (required for YouTube extraction with yt-dlp)...
winget install --id=OpenJS.NodeJS.LTS -e --accept-source-agreements --accept-package-agreements
if %errorlevel% neq 0 (
    echo Node.js installation failed or it is already installed.
)

echo.
echo [4/4] Checking for Python pip...
python -m pip --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Python or pip is not installed or not in PATH!
    echo Please install Python and check 'Add Python to PATH' during installation.
    pause
    exit /b
)

echo.
echo [5/5] Installing Python libraries (yt-dlp, curl-cffi)...
python -m pip install --user "yt-dlp[default,curl-cffi]"
if %errorlevel% neq 0 (
    echo Error: Python libraries could not be installed.
    echo Try running this file from a normal user account, or install Python for your user.
    pause
    exit /b 1
)

echo.
echo ===================================================
echo  Installation complete! 
echo  IMPORTANT: Close this window before running run.bat 
echo  so Windows updates your system PATH for FFmpeg.
echo ===================================================
pause
