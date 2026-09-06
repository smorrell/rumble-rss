@echo off
echo ===================================================
echo  Installing Dependencies (FFmpeg, yt-dlp, GitPython)
echo ===================================================
echo.

echo [1/3] Installing FFmpeg via winget...
winget install --id=Gyan.FFmpeg -e
if %errorlevel% neq 0 (
    echo Winget installation failed or FFmpeg is already installed.
)

echo.
echo [2/3] Checking for Python pip...
python -m pip --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Python or pip is not installed or not in PATH!
    echo Please install Python and check 'Add Python to PATH' during installation.
    pause
    exit /b
)

echo.
echo [3/3] Installing Python libraries (yt-dlp, gitpython)...
python -m pip install --user yt-dlp gitpython
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
