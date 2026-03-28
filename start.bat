@echo off
setlocal

echo.
echo  PromptMatrix — Local Setup
echo  ===========================
echo.

:: Check Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Install Python 3.11+ from https://python.python.org
    pause & exit /b 1
)

:: Create venv if missing
if not exist venv (
    echo [Setup] Creating virtual environment...
    python -m venv venv
)

:: Activate
call venv\Scripts\activate.bat

:: Always install/update dependencies (handles new deps after git pull)
echo [Setup] Installing dependencies...
pip install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo [ERROR] Dependency installation failed. Check requirements.txt and your Python version.
    pause & exit /b 1
)

:: Copy .env.example if no .env exists
if not exist .env (
    echo [Setup] Creating .env from .env.example ...
    copy .env.example .env
    echo [IMPORTANT] Open .env and set your JWT_SECRET_KEY and ENCRYPTION_KEY before using PromptMatrix.
)

:: Run database migrations
echo [Setup] Running database migrations...
alembic upgrade head
if %errorlevel% neq 0 (
    echo [ERROR] Migration failed. Check your DATABASE_URL in .env
    pause & exit /b 1
)

echo.
echo  =====================================================
echo   PromptMatrix is running at http://localhost:8000
echo   Dashboard: http://localhost:8000/dashboard
echo   API Docs:  http://localhost:8000/docs
echo   Press Ctrl+C to stop the server.
echo  =====================================================
echo.

python -m uvicorn main:app --reload --port 8000
pause
