@echo off
REM ============================================
REM  FOL — One-Click Installer (Windows)
REM ============================================

setlocal enabledelayedexpansion

echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║   🧠  FOL — Personal AI Assistant                  ║
echo  ║   One-Click Installer (Windows)                     ║
echo  ╚══════════════════════════════════════════════════════╝
echo.    
   
REM ─── Step 1: Check Python ────────────────────────────────
echo  [1/6] Checking Python... 

python --version >nul 2>&1
if errorlevel 1 (
    echo  ⚠️  Python not found!
    echo.
    echo  Please install Python 3.10+ from:
    echo    https://www.python.org/downloads/
    echo.
    echo  Make sure to check "Add Python to PATH" during installation!
    echo.
    pause
    exit /b 1
)
   
for /f "tokens=2" %%a in ('python --version 2^>^&1') do set PYVER=%%a
echo  ✅ Python %PYVER%

REM ─── Step 2: System dependencies ─────────────────────────
echo.
echo  [2/6] Checking system dependencies...  

REM Check if Chocolatey is installed
choco --version >nul 2>&1
if errorlevel 1 (
    echo  ℹ️  Chocolatey not found — skipping ffmpeg install  
    echo     Install manually: https://chocolatey.org/install
    echo     Then run: choco install ffmpeg
) else (. 
    echo  ℹ️  Installing ffmpeg via Chocolatey...
    choco install ffmpeg -y 2>nul
    echo  ✅ ffmpeg installed
)
   
REM ─── Step 3: Python dependencies ─────────────────────────
echo.
echo  [3/6] Installing Python packages...

python -m pip install --quiet --upgrade pip 2>nul
python -m pip install --quiet -r requirements.txt 2>nul
python -m pip install --quiet pystray Pillow 2>nul
echo  ✅ Python packages installed

REM ─── Step 4: Configure .env ──────────────────────────────
echo.
echo  [4/6] Configuring environment...

if not exist ".env" (
    copy .env.template .env >nul
    echo  ✅ Created .env from template
) else (
    echo  ✅ .env already exists
)

REM ─── Step 5: Setup wizard ────────────────────────────────
echo.
echo  [5/6] Setting up API keys...
echo.
echo  How do you want to configure API keys?
echo.
echo    1. Run interactive wizard (recommended)
echo    2. Skip (configure later)
echo.
set /p CHOICE="  Choice [1/2]: "

if "%CHOICE%"=="1" (
    python setup\setup_wizard.py
) else (
    echo  ℹ️  Skipped. Run later: python setup\setup_wizard.py
)

REM ─── Step 6: Verify ──────────────────────────────────────
echo.
echo  [6/6] Verifying installation...

python setup\install_deps.py --verify 2>nul

REM ─── Done! ───────────────────────────────────────────────
echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║   ✅  FOL installed successfully!                   ║
echo  ╠══════════════════════════════════════════════════════╣
echo  ║                                                      ║
echo  ║   Start FOL:                                         ║
echo  ║     run_all.bat          # all services              ║
echo  ║     python launch_gui.py # GUI launcher              ║
echo  ║     python launch_tray.py # system tray icon         ║
echo  ║                                                      ║
echo  ║   Configure keys:                                    ║
echo  ║     python setup\setup_wizard.py                     ║
echo  ║                                                      ║
echo  ╚══════════════════════════════════════════════════════╝
echo.

set /p START="  Start FOL now? [Y/n]: "
if /i "%START%"=="Y" (
    echo.
    echo  Starting FOL...
    call run_all.bat
) else if "%START%"=="" (
    echo.
    echo  Starting FOL...
    call run_all.bat
)

pause
                 