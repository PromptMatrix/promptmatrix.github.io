"""
Test fixtures
=============
All tests share a SQLite in-memory database that is created fresh per test.
No mocking of business logic — tests run against real SQLAlchemy models.

Email sending is patched at the httpx level so no real network calls happen.
Cache is replaced with a fresh _NoopCache so tests run without external deps.
"""

import os

import pytest

# Set test env before any app imports
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-not-for-prod")
os.environ.setdefault("ENCRYPTION_KEY", "test-enc-key-not-for-prod-xxxxxx")
# Use 'testing' not 'development' so the dev-bypass auto-login does NOT fire in tests.
# Protected routes must still require real JWT tokens.
os.environ["APP_ENV"] = "testing"

import sys

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.auth import generate_api_key, hash_password
from app.database import Base, get_db
from app.models import (ApiKey, AuditLog, Environment, EvalKey, EvalResult,
                        Organisation, OrgMember, PlanOverride, Project, Prompt,
                        PromotionRequest, PromptVersion, ServeEvent, User)

# ── Test database — fresh in-memory SQLite ────────────────────────

TEST_DB_URL = "sqlite://"
test_engine = create_engine(
    TEST_DB_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool
)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="session", autouse=True)
def _create_tables():
    """Create all tables once for the test session."""
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(autouse=True)
def _clean_db():
    """Wipe all rows between tests — keeps tests independent."""
    yield
    db = TestSessionLocal()
    try:
        # Delete in FK dependency order — children before parents
        for model in [
            ServeEvent,
            EvalResult,
            AuditLog,
            PromotionRequest,
            PromptVersion,
            Prompt,
            ApiKey,
            EvalKey,
            Environment,
            Project,
            OrgMember,
            User,
            PlanOverride,
            Organisation,
        ]:
            db.query(model).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture
def client():
    """TestClient with DB dependency overridden to test database."""
    # Import here so env vars are already set
    import main
    from app.serve import cache as cache_module

    # Replace cache with a fresh instance so tests don't share state
    original_cache = cache_module._cache
    cache_module._cache = cache_module._NoopCache()

    import app.database

    original_session_local = app.database.SessionLocal
    app.database.SessionLocal = TestSessionLocal

    main.app.dependency_overrides[get_db] = override_get_db
    with TestClient(main.app, raise_server_exceptions=True) as c:
        yield c

    main.app.dependency_overrides.clear()
    cache_module._cache = original_cache
    app.database.SessionLocal = original_session_local


@pytest.fixture
def db():
    """Raw DB session for fixtures and assertions."""
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()


# ── Seed helpers ──────────────────────────────────────────────────


def seed_org_user(db, email="owner@test.com", role="owner", plan="local"):
    """Create org + user + membership. Returns (org, user, member, project, env)."""
    import re

    slug_base = re.sub(r"[^a-z0-9]", "-", email.split("@")[0])
    slug = slug_base
    i = 1
    while db.query(Organisation).filter(Organisation.slug == slug).first():
        slug = f"{slug_base}-{i}"
        i += 1

    org = Organisation(name=f"{email}'s Org", slug=slug, plan=plan)
    db.add(org)
    db.flush()

    user = User(
        email=email, hashed_pw=hash_password("password123"), full_name="Test User"
    )
    db.add(user)
    db.flush()

    member = OrgMember(org_id=org.id, user_id=user.id, role=role)
    db.add(member)
    db.flush()

    project = Project(org_id=org.id, name="Default")
    db.add(project)
    db.flush()

    env = Environment(
        project_id=project.id,
        name="production",
        display_name="Production",
        color="#00e676",
        is_protected=True,
        eval_pass_threshold=7.0,
    )
    db.add(env)
    db.flush()
    db.commit()

    return org, user, member, project, env


def seed_approved_prompt(
    db, env_id, user_id, key="assistant.system", content="You are a helpful assistant."
):
    """Create a prompt with one approved live version. Returns (prompt, version)."""
    prompt = Prompt(environment_id=env_id, key=key, description="test")
    db.add(prompt)
    db.flush()

    v = PromptVersion(
        prompt_id=prompt.id,
        version_num=1,
        content=content,
        commit_message="init",
        status="approved",
        proposed_by_id=user_id,
        approved_by_id=user_id,
    )
    db.add(v)
    db.flush()
    prompt.live_version_id = v.id
    db.commit()
    return prompt, v


def seed_api_key(db, env_id, name="test-key", org_id=None, plan="local"):
    """Create and return (full_key_string, ApiKey row).

    Args:
        org_id: The org's ID for denormalized rate-limiting lookups.
        plan: The plan name for denormalized rate-limit tier (local|free|solo|team|scale).
    """
    full_key, key_hash, key_prefix = generate_api_key("production")
    row = ApiKey(
        environment_id=env_id,
        name=name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        org_id=org_id,
        plan=plan,
    )
    db.add(row)
    db.commit()
    return full_key, row


def auth_headers(client, email="owner@test.com", password="password123"):
    """Login and return Authorization headers."""
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"Login failed: {r.text}"
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
