@echo off
REM OptiBot startup for Windows (Deliverable 3, FR-7.1)
REM User-space only: no admin, no docker, no services.
REM
REM Usage:
REM   startup.bat              full stack
REM   startup.bat --no-ui      backend + mocks only
REM   startup.bat --offline    skip gateway/model preflight checks
REM   startup.bat --preflight  run checks and exit

setlocal enabledelayedexpansion
cd /d "%~dp0"

set "NO_UI=false"
set "PREFLIGHT_ONLY=false"
set "PASSTHRU="
for %%a in (%*) do (
    set "PASSTHRU=!PASSTHRU! %%a"
    if "%%a"=="--no-ui"     set "NO_UI=true"
    if "%%a"=="--preflight" set "PREFLIGHT_ONLY=true"
)

if not exist logs mkdir logs

REM --- 1. Python venv ----------------------------------------------------
if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: could not create venv. Is Python on PATH?
        exit /b 1
    )
)
call .venv\Scripts\activate.bat

REM --- 2. Dependencies ---------------------------------------------------
if not exist .venv\.deps-installed (
    echo Installing backend dependencies...
    python -m pip install --quiet --upgrade pip
    python -m pip install --quiet -r backend\requirements.txt
    if errorlevel 1 (
        echo ERROR: dependency installation failed.
        exit /b 1
    )
    echo. > .venv\.deps-installed
)

REM --- 3. Environment file -----------------------------------------------
if not exist .env (
    echo ERROR: .env not found. Copy .env.example to .env and fill in gateway settings.
    exit /b 1
)

set "BACKEND_PORT=8787"
set "FRONTEND_PORT=3939"
set "WIREMOCK_PORT=8181"
for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    set "key=%%A"
    if not "!key:~0,1!"=="#" if not "%%B"=="" set "!key!=%%B"
)

REM --- 4. Preflight (fail fast, FR-7.2) ----------------------------------
python scripts\preflight.py %PASSTHRU%
if errorlevel 1 exit /b 1
if "%PREFLIGHT_ONLY%"=="true" exit /b 0

REM --- 5. Mock API -------------------------------------------------------
set "WIREMOCK_JAR="
for %%J in (mocks\wiremock-*.jar) do set "WIREMOCK_JAR=%%J"
where java >nul 2>&1
if not errorlevel 1 if defined WIREMOCK_JAR (
    echo Starting WireMock on :%WIREMOCK_PORT%
    start "OptiBot Mocks" /min cmd /c "java -jar !WIREMOCK_JAR! --port %WIREMOCK_PORT% --root-dir mocks\wiremock --disable-banner > logs\wiremock.log 2>&1"
    goto :mocks_started
)
echo Starting mock API fallback on :%WIREMOCK_PORT% (no JRE/JAR found)
start "OptiBot Mocks" /min cmd /c "python -m scripts.mock_server --port %WIREMOCK_PORT% > logs\wiremock.log 2>&1"
:mocks_started

REM --- 6. Backend --------------------------------------------------------
echo Starting backend on :%BACKEND_PORT%
start "OptiBot Backend" cmd /c "python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port %BACKEND_PORT%"

REM --- 7. Frontend -------------------------------------------------------
if "%NO_UI%"=="false" (
    if not exist frontend\node_modules (
        echo Installing frontend dependencies...
        pushd frontend
        call npm install --silent
        popd
    )
    echo Starting frontend on :%FRONTEND_PORT%
    start "OptiBot Frontend" cmd /c "cd frontend && npm run dev -- --port %FRONTEND_PORT%"
)

echo.
echo OptiBot is running.
echo   Backend   http://127.0.0.1:%BACKEND_PORT%
if "%NO_UI%"=="false" echo   Frontend  http://127.0.0.1:%FRONTEND_PORT%
echo   Mocks     http://127.0.0.1:%WIREMOCK_PORT%
echo.
echo Close the spawned windows to stop, or run: shutdown.bat
echo.
endlocal
