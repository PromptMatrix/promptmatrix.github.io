"""
PromptMatrix API — main.py
===========================
FastAPI entry point. Works as:
  - Vercel serverless function (main.py is the handler)
  - Local uvicorn server (uvicorn main:app --reload)
  - Railway / fly.io persistent server

Run locally:
  uvicorn main:app --reload --port 8000

Deploy to Vercel:
  vercel --prod

Environment variables:
  See .env.example for all required variables.
  Set them in Vercel dashboard → Settings → Environment Variables.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse

from app.config import get_settings
from app.database import create_tables

# ── Routers ──────────────────────────────────────────────────────
from app.serve.router import router as serve_router
from app.api.v1.auth import router as auth_router
from app.api.v1.prompts import router as prompts_router
from app.api.v1.approvals import router as approvals_router
from app.api.v1.keys import router as keys_router
from app.api.v1.projects import router as projects_router
from app.api.v1.orgs import router as orgs_router
from app.api.v1.audit import router as audit_router
from app.api.v1.evals import router as evals_router
from app.api.v1.webhooks import router as webhooks_router

settings = get_settings()

# ── App ───────────────────────────────────────────────────────────
app = FastAPI(
    title="PromptMatrix API",
    description="Prompt governance infrastructure for AI teams",
    version="0.1.0",
    docs_url="/docs" if settings.app_env != "production" else None,
    redoc_url=None,
)

# ── CORS ─────────────────────────────────────────────────────────
# Allow requests from:
#   - The app HTML (GitHub Pages / Vercel frontend)
#   - localhost for development
allowed_origins = [
    settings.frontend_url,
    "http://localhost:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    # GitHub Pages
    "https://promptmatrix.github.io",
    # Vercel preview deployments
    "https://*.vercel.app",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ────────────────────────────────────────────────────────
app.include_router(serve_router)           # /pm/serve/{key}
app.include_router(auth_router)            # /api/v1/auth/*
app.include_router(prompts_router)         # /api/v1/prompts/*
app.include_router(approvals_router)       # /api/v1/approvals/*
app.include_router(keys_router)            # /api/v1/keys/*
app.include_router(projects_router)        # /api/v1/projects/*
app.include_router(orgs_router)            # /api/v1/orgs/*
app.include_router(audit_router)           # /api/v1/audit/*
app.include_router(evals_router)           # /api/v1/evals/*
app.include_router(webhooks_router)        # /api/v1/webhooks/*

# ── Startup ───────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    """Create DB tables on first boot. Safe to call multiple times (CREATE IF NOT EXISTS)."""
    create_tables()


# ── Health / Status ───────────────────────────────────────────────
@app.get("/api/status")
async def status():
    """
    Health check. The frontend polls this every 30 seconds to show
    the connection indicator in the sidebar.
    """
    return {
        "status": "ok",
        "version": "0.1.0",
        "env": settings.app_env,
    }


@app.get("/")
async def root():
    """
    Public entry point. Redirects to the dashboard because the landing 
    page is kept in a separate private repository for the cloud version.
    """
    return RedirectResponse(url="/dashboard")


@app.get("/dashboard")
async def dashboard():
    """Serve the application dashboard."""
    return FileResponse("dashboard.html")


# ── Global error handler ─────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Catch-all. Never expose stack traces in production."""
    if settings.debug:
        raise exc
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )
