@echo off
REM ============================================
REM  FOL — Windows Launcher
REM  Starts all FOL services on Windows
REM ============================================

setlocal enabledelayedexpansion

echo.
echo  ╔══════════════════════════════════════════╗
echo  ║  🧠 FOL — Personal AI Assistant         ║
echo  ║  Windows Edition                         ║
echo  ╚══════════════════════════════════════════╝
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.10+ from https://python.org
    echo         Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

REM Check .env
if not exist ".env" (
    echo [SETUP] No .env found. Running setup wizard...
    python setup\setup_wizard.py
    if errorlevel 1 (
        echo [INFO] Copying .env.template to .env...
        copy .env.template .env >nul
    )
)

REM Install dependencies
echo [DEPS] Installing Python dependencies...
pip install -r requirements.txt --quiet 2>nul

echo.
echo [START] Starting FOL services...
echo.

REM Start Orchestrator (port 8420)
echo [1/4] Starting Orchestrator on port 8420...
start "FOL Orchestrator" /min python orchestrator\server.py

REM Wait for orchestrator to start
timeout /t 3 /nobreak >nul

REM Start Agent Server (port 8421)
echo [2/4] Starting Agent Server on port 8421...
start "FOL Agent Server" /min python agent-server\server.py

REM Wait for agent server
timeout /t 2 /nobreak >nul

REM Start FOL API (port 8754)
echo [3/4] Starting FOL API on port 8754...
start "FOL API" /min python fol\main.py

REM Wait for FOL API
timeout /t 2 /nobreak >nul

REM Start Next.js Web (port 3000) — optional
if exist "package.json" (
    echo [4/4] Starting Web UI on port 3000...
    start "FOL Web UI" /min npm run dev
) else (
    echo [4/4] Web UI skipped (no package.json)
)

echo.
echo  ╔══════════════════════════════════════════╗
echo  ║  ✅ FOL is running!                      ║
echo  ╠══════════════════════════════════════════╣
echo  ║  Orchestrator:  http://localhost:8420    ║
echo  ║  Agent Server:  http://localhost:8421    ║
echo  ║  FOL API:       http://localhost:8754    ║
echo  ║  Web UI:        http://localhost:3000    ║
echo  ╚══════════════════════════════════════════╝
echo.
echo  Press Ctrl+C to stop all services.
echo.

REM Keep window open
pause
