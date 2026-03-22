@echo off
setlocal

echo ============================================================
echo   PromptMatrix - Windows Local Startup Script
echo ============================================================

:: 1. Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Please install Python 3.9+ from https://www.python.org/
    pause
    exit /b 1
)

:: 2. Create virtual environment if it doesn't exist
if not exist venv (
    echo [INFO] Creating virtual environment...
    python -m venv venv
)

:: 3. Activate virtual environment and install dependencies
echo [INFO] Activating virtual environment...
call venv\Scripts\activate.bat
echo [INFO] Installing/Updating dependencies...
pip install -r requirements.txt

:: 4. Setup .env if it doesn't exist
if not exist .env (
    echo [INFO] Creating .env from .env.example...
    copy .env.example .env
    echo [WARNING] Please edit the .env file and set your JWT_SECRET_KEY and ENCRYPTION_KEY.
)

:: 5. Run migrations
echo [INFO] Running database migrations...
alembic upgrade head

:: 6. Start the server
echo [INFO] Starting PromptMatrix server on http://localhost:8000
echo [INFO] Use Ctrl+C to stop the server.
python -m uvicorn main:app --reload --port 8000

pause
