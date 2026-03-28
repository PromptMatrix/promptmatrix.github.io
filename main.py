import os
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from app.config import get_settings
from app.serve.router import router as serve_router
from app.api.v1.auth import router as auth_router
from app.api.v1.prompts import router as prompts_router
from app.api.v1.approvals import router as approvals_router
from app.api.v1.keys import router as keys_router
from app.api.v1.projects import router as projects_router
from app.api.v1.audit import router as audit_router
from app.api.v1.evals import router as evals_router

settings = get_settings()
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle — runs on startup, yields, then runs on shutdown."""
    log.info("PromptMatrix ready — env=%s", settings.app_env)

    # Security warning: ENCRYPTION_KEY should be set separately from JWT_SECRET_KEY
    if not settings.encryption_key:
        log.warning(
            "ENCRYPTION_KEY is not set in .env — eval key encryption is falling back to "
            "JWT_SECRET_KEY. If you rotate JWT_SECRET_KEY, all stored eval keys will be "
            "unreadable. Set a separate ENCRYPTION_KEY in .env to avoid data loss."
        )

    yield


app = FastAPI(
    title="PromptMatrix API",
    description="Prompt governance infrastructure for AI applications",
    version="0.1.0",
    docs_url="/docs" if settings.app_env != "production" else None,
    redoc_url=None,
    lifespan=lifespan,
)

allowed_origins = [
    settings.app_url,
    "http://localhost:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(serve_router)
app.include_router(auth_router)
app.include_router(prompts_router)
app.include_router(approvals_router)
app.include_router(keys_router)
app.include_router(projects_router)
app.include_router(audit_router)
app.include_router(evals_router)


@app.get("/api/status")
async def status():
    return {
        "status": "ok",
        "version": "0.1.0",
        "env": settings.app_env,
    }

BASE_DIR = Path(__file__).resolve().parent

@app.get("/")
async def root():
    return FileResponse(BASE_DIR / "index.html")

@app.get("/dashboard")
async def dashboard():
    return FileResponse(BASE_DIR / "dashboard.html")

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    if settings.debug:
        raise exc
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )
