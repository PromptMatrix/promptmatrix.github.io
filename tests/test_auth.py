"""Auth route tests — register, login, refresh, me"""

import pytest
from tests.conftest import seed_org_user


def test_register_creates_workspace(client):
    r = client.post("/api/v1/auth/register", json={
        "email": "new@test.com",
        "password": "password123",
        "full_name": "New User",
        "org_name": "New Workspace",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["user"]["email"] == "new@test.com"
    assert data["active_org"]["name"] == "PromptMatrix"  # OSS: workspace name is always PromptMatrix
    assert data["active_org"]["role"] == "owner"
    assert data["active_org"]["plan"] == "local"


def test_register_rejects_duplicate_email(client):
    client.post("/api/v1/auth/register", json={
        "email": "dup@test.com", "password": "password123",
        "full_name": "First", "org_name": "First Org",
    })
    r = client.post("/api/v1/auth/register", json={
        "email": "dup@test.com", "password": "password123",
        "full_name": "Second", "org_name": "Second Org",
    })
    assert r.status_code in (403, 409)  # OSS: 403=locked after first user; 409=duplicate email


def test_register_rejects_short_password(client):
    r = client.post("/api/v1/auth/register", json={
        "email": "short@test.com", "password": "short",
        "full_name": "User", "org_name": "Org",
    })
    assert r.status_code == 422


def test_login_returns_tokens(client, db):
    seed_org_user(db, email="login@test.com")
    r = client.post("/api/v1/auth/login", json={
        "email": "login@test.com", "password": "password123"
    })
    assert r.status_code == 200
    data = r.json()
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["active_org"]["role"] == "owner"


def test_login_rejects_wrong_password(client, db):
    seed_org_user(db, email="wrongpw@test.com")
    r = client.post("/api/v1/auth/login", json={
        "email": "wrongpw@test.com", "password": "wrongpassword"
    })
    assert r.status_code == 401


def test_refresh_preserves_org_id(client, db):
    """Core bug fix: refresh token must preserve org_id."""
    seed_org_user(db, email="refresh@test.com")
    login = client.post("/api/v1/auth/login", json={
        "email": "refresh@test.com", "password": "password123"
    }).json()

    r = client.post("/api/v1/auth/refresh", json={
        "refresh_token": login["refresh_token"]
    })
    assert r.status_code == 200
    data = r.json()
    assert data["access_token"]
    assert data["refresh_token"]

    # Decode both tokens and verify org is preserved
    from app.core.auth import decode_token
    orig = decode_token(login["access_token"])
    refreshed = decode_token(data["access_token"])
    assert orig["org"] == refreshed["org"], "org_id lost after token refresh"
    assert orig["sub"] == refreshed["sub"]


def test_refresh_rejects_access_token_as_refresh(client, db):
    """Access tokens must not be accepted as refresh tokens."""
    seed_org_user(db, email="badrefresh@test.com")
    login = client.post("/api/v1/auth/login", json={
        "email": "badrefresh@test.com", "password": "password123"
    }).json()

    r = client.post("/api/v1/auth/refresh", json={
        "refresh_token": login["access_token"]   # wrong — passing access token
    })
    assert r.status_code == 401


def test_me_returns_user_and_org(client, db):
    seed_org_user(db, email="me@test.com")
    from tests.conftest import auth_headers
    r = client.get("/api/v1/auth/me", headers=auth_headers(client, "me@test.com"))
    assert r.status_code == 200
    data = r.json()
    assert data["user"]["email"] == "me@test.com"
    assert data["active_org"]["role"] == "owner"


def test_protected_route_rejects_no_token(client):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401


def test_protected_route_rejects_invalid_token(client):
    r = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage.token.here"})
    assert r.status_code == 401
