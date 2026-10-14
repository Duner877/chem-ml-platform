@echo off
REM ===========================================================================
REM  Chem ML Platform v0.7.2  -  Desktop (Electron) launcher
REM ---------------------------------------------------------------------------
REM  Starts the platform in its OWN window.  This is NOT the browser mode --
REM  for that, use start-platform.bat instead.
REM
REM  v0.7.2 ships the "controlled installer" strategy (plan B): no Python
REM  interpreter is bundled.  The shell looks for one in this order:
REM    1. CHEMML_PYTHON                  <- set below, so it matches this repo
REM    2. resources\python-runtime\      (intentionally empty in this version)
REM    3. app\.venv
REM    4. PATH
REM  Pointing (1) at this repository's .venv is what lets the packaged shell
REM  run without a second, separately maintained environment.
REM ===========================================================================
setlocal
cd /d "%~dp0"

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if exist "%VENV_PY%" (
    set "CHEMML_PYTHON=%VENV_PY%"
) else (
    echo [WARN] %VENV_PY% not found -- run install.bat first.
    echo        Falling back to whatever "python" is on PATH.
    echo.
)

set "APP=%~dp0desktop\dist\win-unpacked\Chem ML Platform.exe"
if exist "%APP%" goto :packaged

if exist "%~dp0desktop\node_modules\electron" goto :devshell

echo [ERROR] Neither a packaged desktop build nor the Electron shell is present.
echo.
echo   Option 1 - build/obtain the packaged app, then re-run this script:
echo       desktop\dist\win-unpacked\Chem ML Platform.exe
echo   Option 2 - install the dev shell (downloads Electron, ~100 MB):
echo       cd desktop ^&^& npm install
echo.
pause
exit /b 1

:packaged
echo   Chem ML Platform v0.7.2  -  Desktop window
echo   ------------------------------------------------------------
echo   Python : %CHEMML_PY%
echo   App    : %APP%
echo.
echo   Close the window (or press Ctrl+C here) to stop the platform.
echo.
"%APP%"
exit /b %ERRORLEVEL%

:devshell
echo   Chem ML Platform v0.7.2  -  Desktop window (dev shell)
echo   ------------------------------------------------------------
echo   Python : %CHEMML_PY%
echo.
pushd "%~dp0desktop"
call npm start
popd
exit /b %ERRORLEVEL%
