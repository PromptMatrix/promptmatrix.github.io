@echo off
setlocal
python --version >nul 2>&1
if %errorlevel% neq 0 (
    exit /b 1
)
if not exist venv (
    python -m venv venv
)
call venv\Scripts\activate.bat
pip install -r requirements.txt
if not exist .env (
    copy .env.example .env
)
alembic upgrade head
python -m uvicorn main:app --reload --port 8000
pause
