#!/bin/bash
set -e

echo ""
echo " PromptMatrix — Local Setup"
echo " ==========================="
echo ""

# Check Python is installed
if ! command -v python3 &>/dev/null; then
    echo "[ERROR] Python 3 not found. Install Python 3.11+ from https://python.org"
    exit 1
fi

# Create venv if missing
if [ ! -d "venv" ]; then
    echo "[Setup] Creating virtual environment..."
    python3 -m venv venv
fi

# Activate
source venv/bin/activate

# Upgrade pip silently (prevents false failure from pip update notices)
python3 -m pip install --upgrade pip --quiet

# Always install/update deps (handles new deps after git pull)
echo "[Setup] Installing dependencies..."
pip install -r requirements.txt --quiet
if [ $? -ne 0 ]; then
    echo "[ERROR] Dependency installation failed. Check requirements.txt."
    exit 1
fi

# Copy .env.example if no .env
if [ ! -f ".env" ]; then
    echo "[Setup] Creating .env from .env.example ..."
    cp .env.example .env
    python3 -c "import secrets; data=open('.env').read(); data=data.replace('JWT_SECRET_KEY=change-me-to-a-random-secret','JWT_SECRET_KEY='+secrets.token_hex(32)); data=data.replace('ENCRYPTION_KEY=','ENCRYPTION_KEY='+secrets.token_hex(32)); open('.env','w').write(data)"
    echo "[IMPORTANT] Secure keys generated automatically in .env."
fi

# Run migrations
echo "[Setup] Running database migrations..."
alembic upgrade head
if [ $? -ne 0 ]; then
    echo "[ERROR] Migration failed. Check your DATABASE_URL in .env"
    exit 1
fi

echo ""
echo " ====================================================="
echo "  PromptMatrix is running at http://localhost:8000"
echo "  Dashboard: http://localhost:8000/dashboard"
echo "  API Docs:  http://localhost:8000/docs"
echo "  Press Ctrl+C to stop."
echo " ====================================================="
echo ""

uvicorn main:app --reload --port 8000
