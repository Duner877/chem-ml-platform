@echo off
setlocal
cd /d "%~dp0\frontend"

if not exist "node_modules" (
    echo [ERROR] frontend\node_modules is missing.
    echo         Run:  npm install
    pause
    exit /b 1
)

echo   Frontend dev server : http://127.0.0.1:5173
echo   API proxy target    : http://127.0.0.1:8000  ^(start start-backend.bat first^)
echo.

call npm run dev

endlocal
