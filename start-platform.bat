@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found.
    echo         Run install.bat first.
    pause
    exit /b 1
)

REM --- expose the built frontend to the backend (directory junction) ---
if not exist "static" (
    if exist "frontend\dist" (
        mklink /J "static" "frontend\dist" >nul 2>&1
    )
)
if not exist "static" (
    echo [WARN] frontend\dist not found - the API still runs, but the web UI will be missing.
    echo        Build it with:  cd frontend ^&^& npm run build
    echo.
)

set HOST=127.0.0.1
set PORT=8000

echo.
echo   Chem ML Platform v0.6.0  -  Scientific Foundation Model Edition
echo   ------------------------------------------------------------
echo   Web UI + API : http://%HOST%:%PORT%
echo   API docs     : http://%HOST%:%PORT%/api/docs
echo.
echo   Press Ctrl+C to stop the server.
echo.

start "" "http://%HOST%:%PORT%"
".venv\Scripts\python.exe" -m uvicorn backend.app:app --host %HOST% --port %PORT%

endlocal
