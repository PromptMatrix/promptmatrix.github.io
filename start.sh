#!/bin/bash
if [ ! -d "venv" ]; then
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
else
    source venv/bin/activate
fi
if [ ! -f ".env" ]; then
    cp .env.example .env
fi
alembic upgrade head
uvicorn main:app --reload --port 8000
