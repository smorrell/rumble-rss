@echo off
setlocal
cd /d "%~dp0"

echo Uploading files to Azure Blob Storage...
python azure_upload.py
if errorlevel 1 (
    echo.
    echo Azure upload failed.
    exit /b 1
)

echo.
echo Azure upload completed successfully.
exit /b 0
