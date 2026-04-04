"""API key lifecycle tests — create, revoke, rotate"""

from tests.conftest import seed_org_user, seed_approved_prompt, seed_api_key, auth_headers


def test_create_key_returns_full_key_once(client, db):
    _, _, _, _, env = seed_org_user(db)
    hdrs = auth_headers(client)

    r = client.post("/api/v1/keys", json={
        "environment_id": env.id,
        "name": "prod key",
    }, headers=hdrs)
    assert r.status_code == 200
    data = r.json()
    assert data["key"].startswith("pm_live_")
    assert data["prefix"] in data["key"]
    assert "Copy" in data["message"]


def test_list_keys(client, db):
    _, _, _, _, env = seed_org_user(db)
    seed_api_key(db, env.id, name="key-one")
    seed_api_key(db, env.id, name="key-two")
    hdrs = auth_headers(client)

    r = client.get(f"/api/v1/keys?environment_id={env.id}", headers=hdrs)
    assert r.status_code == 200
    assert len(r.json()["keys"]) == 2


def test_revoke_key_blocks_serve(client, db):
    _, user, _, _, env = seed_org_user(db)
    seed_approved_prompt(db, env.id, user.id)
    full_key, key_row = seed_api_key(db, env.id)
    hdrs = auth_headers(client)

    # Works before revoke
    r = client.get("/pm/serve/assistant.system",
                   headers={"Authorization": f"Bearer {full_key}"})
    assert r.status_code == 200

    # Revoke
    r = client.delete(f"/api/v1/keys/{key_row.id}", headers=hdrs)
    assert r.status_code == 200

    # Blocked after revoke
    r = client.get("/pm/serve/assistant.system",
                   headers={"Authorization": f"Bearer {full_key}"})
    assert r.status_code == 401


def test_rotate_key_old_key_blocked_new_works(client, db):
    _, user, _, _, env = seed_org_user(db)
    seed_approved_prompt(db, env.id, user.id)
    full_key, key_row = seed_api_key(db, env.id)
    hdrs = auth_headers(client)

    # Rotate
    r = client.post(f"/api/v1/keys/{key_row.id}/rotate", headers=hdrs)
    assert r.status_code == 200
    new_key = r.json()["key"]
    assert new_key != full_key
    assert r.json()["message"]  # rotation succeeded — key changed

    # Old key blocked
    r = client.get("/pm/serve/assistant.system",
                   headers={"Authorization": f"Bearer {full_key}"})
    assert r.status_code == 401

    # New key works
    r = client.get("/pm/serve/assistant.system",
                   headers={"Authorization": f"Bearer {new_key}"})
    assert r.status_code == 200


def test_viewer_cannot_create_key(client, db):
    """Only engineer+ can create API keys — viewer must get 403."""
    _, _, _, _, env = seed_org_user(db)
    auth_headers(client)  # owner (logged in via seed)

    # Create a second user as viewer in the SAME org
    from app.models import User, OrgMember
    owner = db.query(User).filter(User.email == "owner@test.com").first()
    owner_member = db.query(OrgMember).filter(OrgMember.user_id == owner.id).first()
    from app.core.auth import hash_password
    viewer = User(email="viewer@test.com", hashed_pw=hash_password("password123"), full_name="Viewer")
    db.add(viewer); db.flush()
    db.add(OrgMember(org_id=owner_member.org_id, user_id=viewer.id, role="viewer"))
    db.commit()

    # Log in as viewer
    r = client.post("/api/v1/auth/login", json={"email": "viewer@test.com", "password": "password123"})
    assert r.status_code == 200
    viewer_token = r.json()["access_token"]
    viewer_hdrs = {"Authorization": f"Bearer {viewer_token}"}

    # Viewer must be rejected when trying to create a key
    r = client.post("/api/v1/keys", json={"environment_id": env.id, "name": "test-key"}, headers=viewer_hdrs)
    assert r.status_code == 403, f"Expected 403 for viewer creating key, got {r.status_code}"


def test_key_prefix_format(client, db):
    """Key prefix must encode environment type."""
    _, _, _, _, env = seed_org_user(db)
    hdrs = auth_headers(client)

    r = client.post("/api/v1/keys", json={
        "environment_id": env.id,
        "name": "format test",
    }, headers=hdrs)
    key = r.json()["key"]
    assert key.startswith("pm_live_"), f"Production key must start with pm_live_, got: {key[:20]}"
