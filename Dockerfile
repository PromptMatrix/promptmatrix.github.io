# Stage 1: Dependency Builder
FROM python:3.11-slim as builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /app/wheels -r requirements.txt

# Stage 2: Runtime Environment
FROM python:3.11-slim

WORKDIR /app

# Ensure non-root execution (optional hardening)
RUN useradd -m -U appuser

# Copy wheels and install
COPY --from=builder /app/wheels /wheels
COPY --from=builder /app/requirements.txt .
RUN pip install --no-cache /wheels/*

# Copy project files
COPY . .

# Run as non-root user
RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Run schema migrations then start FastAPI
CMD /bin/bash -c "alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port 8000"
