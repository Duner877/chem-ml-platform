@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found. Run install.bat first.
    pause
    exit /b 1
)

set HOST=127.0.0.1
set PORT=8000

echo   Backend (auto-reload) : http://%HOST%:%PORT%
echo   API docs              : http://%HOST%:%PORT%/api/docs
echo.

".venv\Scripts\python.exe" -m uvicorn backend.app:app --reload --host %HOST% --port %PORT%

endlocal
