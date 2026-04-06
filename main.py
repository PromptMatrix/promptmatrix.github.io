import datetime
import logging
import secrets as _secrets
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.v1.approvals import router as approvals_router
from app.api.v1.audit import router as audit_router
from app.api.v1.auth import router as auth_router
from app.api.v1.evals import router as evals_router
from app.api.v1.keys import router as keys_router
from app.api.v1.orgs import router as orgs_router
from app.api.v1.projects import router as projects_router
from app.api.v1.prompts import router as prompts_router
from app.config import get_settings
from app.serve.router import router as serve_router

settings = get_settings()
log = logging.getLogger(__name__)


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        # Content Security Policy: restrict scripts to self
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self';"
        )
        response.headers["Content-Security-Policy"] = csp
        # Anti-Clickjacking
        response.headers["X-Frame-Options"] = "DENY"
        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        # Referrer and Permissions policies
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        # HSTS (1 year) - only if not in dev
        if settings.app_env != "development":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response


def _seed_local_admin():
    """
    Auto-create a default local admin + workspace on the very first run.

    In local/development mode the backend already bypasses JWT auth entirely
    (see app/core/auth.py — get_current_user returns db.query(User).first()
    when APP_ENV=development and no Bearer token is present).  The dashboard
    also calls /api/v1/auth/me without a token and auto-logs in if it gets a
    valid response, so the login screen is never shown.

    This function ensures a valid user always exists, so that first-run
    users land directly in the dashboard without any registration step.

    Safe to call every startup: returns immediately if users already exist.
    """
    from app.core.auth import hash_password
    from app.database import SessionLocal
    from app.models import Environment, Organisation, OrgMember, Project, User

    db = SessionLocal()
    try:
        if db.query(User).count() > 0:
            return  # already seeded — skip

        log.info("First-run: seeding local admin workspace (no login required)...")

        user = User(
            id=str(uuid.uuid4()),
            email="admin@local",
            # Random password — never used because dev-mode bypasses auth entirely
            hashed_pw=hash_password(_secrets.token_hex(16)),
            full_name="Local Admin",
            is_active=True,
            email_verified=True,
            created_at=datetime.datetime.utcnow(),
        )
        db.add(user)
        db.flush()

        # Unique org slug
        slug = "promptmatrix"
        i = 1
        while db.query(Organisation).filter(Organisation.slug == slug).first():
            slug = f"promptmatrix-{i}"
            i += 1

        org = Organisation(
            id=str(uuid.uuid4()),
            name="PromptMatrix",
            slug=slug,
            plan="local",
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        db.add(org)
        db.flush()

        member = OrgMember(
            id=str(uuid.uuid4()),
            org_id=org.id,
            user_id=user.id,
            role="owner",
            joined_at=datetime.datetime.now(datetime.timezone.utc),
        )
        db.add(member)

        # We must add an audit log so it doesn't break analytics later
        from datetime import datetime, timezone
        from app.models import AuditLog
        
        db.add(AuditLog(
            id=str(uuid.uuid4()),
            org_id=org.id,
            actor_id=user.id,
            actor_email=user.email,
            action="init.local_admin",
            resource_type="system",
            created_at=datetime.now(timezone.utc)
        ))
        db.add(member)
        db.flush()

        # Seed default project + three standard environments
        project = Project(
            id=str(uuid.uuid4()),
            org_id=org.id,
            name="Default Project",
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        db.add(project)
        db.flush()

        for env_name, display, color, protected, threshold in [
            ("production", "Production", "#00e676", True, 7.0),
            ("staging", "Staging", "#ff9800", True, 6.0),
            ("development", "Development", "#448aff", False, 0.0),
        ]:
            db.add(
                Environment(
                    id=str(uuid.uuid4()),
                    project_id=project.id,
                    name=env_name,
                    display_name=display,
                    color=color,
                    is_protected=protected,
                    eval_pass_threshold=threshold,
                    created_at=datetime.datetime.now(datetime.timezone.utc),
                )
            )

        db.commit()
        log.info("Local admin seeded — dashboard opens without login.")
    except Exception as e:
        db.rollback()
        log.warning(
            "Could not auto-seed local admin: %s (non-fatal, will show login screen)", e
        )
    finally:
        db.close()


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

    # Local-first: auto-seed default admin on first run so the login screen
    # never appears in development/local mode.
    # In production (APP_ENV=production), this is skipped — users must register.
    if settings.app_env == "development":
        _seed_local_admin()

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
    "http://localhost:5173",
    "http://localhost:4173",
    "http://127.0.0.1:5173",
]

app.add_middleware(SecurityMiddleware)
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
app.include_router(orgs_router)
app.include_router(projects_router)
app.include_router(audit_router)
app.include_router(evals_router)


@app.get("/api/status")
async def status():
    from sqlalchemy import text
    from app.database import SessionLocal
    db_status = "unknown"
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {str(e)[:80]}"
    finally:
        db.close()
    return {
        "status": "ok",
        "version": "0.1.0",
        "env": settings.app_env,
        "db": db_status,
    }


BASE_DIR = Path(__file__).resolve().parent


@app.get("/")
async def root():
    return FileResponse(BASE_DIR / "index.html")


@app.get("/dashboard")
async def dashboard():
    return FileResponse(BASE_DIR / "dashboard.html")


@app.get("/manifest.json")
async def manifest():
    return FileResponse(BASE_DIR / "manifest.json")


@app.get("/sw.js")
async def service_worker():
    return FileResponse(BASE_DIR / "sw.js")


@app.get("/dashboard.js")
async def dashboard_script():
    return FileResponse(BASE_DIR / "dashboard.js")


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    if settings.debug:
        raise exc
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
