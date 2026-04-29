@echo off
setlocal

if not exist ".venv\Scripts\streamlit.exe" (
    echo [ERROR] Run setup.bat first.
    pause
    exit /b 1
)

echo Starting MSP Campaign Loader...
echo Open http://localhost:8501 in your browser.
echo Press Ctrl+C to stop.
echo.

call .venv\Scripts\activate.bat
streamlit run streamlit_app.py
