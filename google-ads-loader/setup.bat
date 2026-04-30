@echo off
setlocal enabledelayedexpansion

echo ================================================
echo  MSP Campaign Loader -- First-Time Setup
echo ================================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not on PATH.
    echo.
    echo Install Python 3.11 or 3.12 from:
    echo   https://www.python.org/downloads/
    echo.
    echo Make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('python --version 2^>^&1') do echo [OK] %%i found
echo.

:: Create virtual environment
if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created.
) else (
    echo [OK] Virtual environment already exists.
)
echo.

:: Activate and install packages
echo Installing packages (this may take a minute)...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Package installation failed. Check the error above.
    pause
    exit /b 1
)
echo [OK] All packages installed.
echo.

:: Create .env from example if missing
if not exist ".env" (
    if exist ".env.example" (
        copy .env.example .env >nul
        echo [OK] Created .env from .env.example
        echo      >>> Open .env in a text editor and fill in your API credentials <<<
    ) else (
        echo [WARN] No .env.example found -- create a .env file manually.
    )
) else (
    echo [OK] .env file already exists.
)
echo.

:: Create client_configs/assets folder
if not exist "client_configs\assets" (
    mkdir client_configs\assets
    echo [OK] Created client_configs\assets folder.
)

echo ================================================
echo  Setup complete!
echo.
echo  Next:
echo    1. Edit .env with your credentials (if not done)
echo    2. Run:  run.bat
echo ================================================
echo.
pause
