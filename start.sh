#!/bin/bash

# PromptMatrix Local Startup Script

# 1. Install dependencies if not present
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

# 2. Setup .env if not present
if [ ! -f ".env" ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
    echo "Please edit .env and update secrets before production use."
fi

# 3. Run migrations
echo "Running database migrations..."
alembic upgrade head

# 4. Start the server
echo "Starting PromptMatrix server on http://localhost:8000"
uvicorn main:app --reload --port 8000
