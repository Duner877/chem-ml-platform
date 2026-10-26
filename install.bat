@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo   Chem ML Platform v0.7.4  -  dependency installer
echo ============================================================
echo.

echo [1/4] Python virtual environment (.venv)
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Could not create the virtual environment.
        echo         Make sure Python 3.11+ is installed and on PATH.
        pause
        exit /b 1
    )
) else (
    echo       already present, skipping
)

echo [2/4] Python packages (requirements.txt)
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
".venv\Scripts\python.exe" -m pip install -e ./node_sdk/python
if errorlevel 1 (
    echo [ERROR] pip install failed. See the output above.
    pause
    exit /b 1
)

echo [3/4] Frontend packages (npm install)
pushd frontend
call npm install --no-audit --no-fund
if errorlevel 1 (
    echo [ERROR] npm install failed. Make sure Node.js 18+ is installed.
    popd
    pause
    exit /b 1
)

echo [4/4] Frontend production build (npm run build)
call npm run build
popd

echo.
echo ============================================================
echo   Installation complete.
echo   Start the platform with:  start-platform.bat
echo ============================================================
pause

endlocal
