"""
Prompt + version workflow tests
================================
Covers the core governance state machine:
  draft → pending_review → approved → live
  approved → archived (on new approval)
  rollback creates new approved version
"""

from tests.conftest import auth_headers, seed_approved_prompt, seed_org_user


def test_create_prompt(client, db):
    _, _, _, _, env = seed_org_user(db)
    hdrs = auth_headers(client)

    r = client.post(
        "/api/v1/prompts",
        json={
            "environment_id": env.id,
            "key": "assistant.system",
            "content": "You are helpful.",
            "description": "Main system prompt",
        },
        headers=hdrs,
    )
    assert r.status_code == 200
    data = r.json()["prompt"]
    assert data["key"] == "assistant.system"
    assert data["version_count"] == 1
    assert data["live_version"] is None  # draft, not approved yet


def test_create_prompt_rejects_invalid_key_format(client, db):
    _, _, _, _, env = seed_org_user(db)
    hdrs = auth_headers(client)

    for bad_key in ["Has Spaces", "UPPERCASE", "slash/key", "x" * 201]:
        r = client.post(
            "/api/v1/prompts",
            json={
                "environment_id": env.id,
                "key": bad_key,
                "content": "content",
            },
            headers=hdrs,
        )
        assert (
            r.status_code == 422
        ), f"Expected 422 for key: {bad_key!r}, got {r.status_code}"


def test_create_prompt_rejects_duplicate_key(client, db):
    _, user, _, _, env = seed_org_user(db)
    seed_approved_prompt(db, env.id, user.id, key="assistant.system")
    hdrs = auth_headers(client)

    r = client.post(
        "/api/v1/prompts",
        json={
            "environment_id": env.id,
            "key": "assistant.system",
            "content": "duplicate",
        },
        headers=hdrs,
    )
    assert r.status_code == 409


def test_full_approval_workflow(client, db):
    """draft → submit → approve → live. Verifies state at each step."""
    _, user, _, _, env = seed_org_user(db)
    hdrs = auth_headers(client)

    # 1. Create prompt (v1 as draft)
    r = client.post(
        "/api/v1/prompts",
        json={
            "environment_id": env.id,
            "key": "workflow.test",
            "content": "You are helpful.",
        },
        headers=hdrs,
    )
    assert r.status_code == 200
    prompt_id = r.json()["prompt"]["id"]

    # 2. Create v2
    r = client.post(
        f"/api/v1/prompts/{prompt_id}/versions",
        json={
            "content": "You are very helpful.",
            "commit_message": "made it better",
        },
        headers=hdrs,
    )
    assert r.status_code == 200
    v2_id = r.json()["version"]["id"]
    assert r.json()["version"]["status"] == "draft"
    assert r.json()["version"]["version_num"] == 2

    # 3. Submit for review
    r = client.post(
        f"/api/v1/prompts/{prompt_id}/versions/{v2_id}/submit",
        json={"note": "please review"},
        headers=hdrs,
    )
    assert r.status_code == 200
    assert r.json()["version"]["status"] == "pending_review"

    # 4. Cannot submit again (already pending)
    r = client.post(
        f"/api/v1/prompts/{prompt_id}/versions/{v2_id}/submit", json={}, headers=hdrs
    )
    assert r.status_code == 400

    # 5. Approve (owner role satisfies engineer requirement)
    r = client.post(
        f"/api/v1/prompts/{prompt_id}/versions/{v2_id}/approve",
        json={"note": "looks good"},
        headers=hdrs,
    )
    assert r.status_code == 200
    assert r.json()["version"]["status"] == "approved"
    assert r.json()["message"]  # approved and now live — message present

    # 6. Prompt now shows v2 as live
    r = client.get(f"/api/v1/prompts/{prompt_id}", headers=hdrs)
    assert r.status_code == 200
    live = r.json()["prompt"]["live_version"]
    assert live["version_num"] == 2
    assert live["content"] == "You are very helpful."


def test_approve_archives_previous_live(client, db):
    """When v2 is approved, v1 must be archived — not still 'approved'."""
    _, user, _, _, env = seed_org_user(db)
    prompt, v1 = seed_approved_prompt(db, env.id, user.id)
    hdrs = auth_headers(client)

    # Create and approve v2
    r = client.post(
        f"/api/v1/prompts/{prompt.id}/versions",
        json={
            "content": "Updated content.",
            "commit_message": "v2",
        },
        headers=hdrs,
    )
    v2_id = r.json()["version"]["id"]
    client.post(
        f"/api/v1/prompts/{prompt.id}/versions/{v2_id}/submit", json={}, headers=hdrs
    )
    client.post(
        f"/api/v1/prompts/{prompt.id}/versions/{v2_id}/approve", json={}, headers=hdrs
    )

    r = client.get(f"/api/v1/prompts/{prompt.id}", headers=hdrs)
    versions = {v["version_num"]: v for v in r.json()["versions"]}
    assert versions[1]["status"] == "archived", "Previous live version must be archived"
    assert versions[2]["status"] == "approved"


def test_reject_version(client, db):
    _, user, _, _, env = seed_org_user(db)
    prompt, _ = seed_approved_prompt(db, env.id, user.id)
    hdrs = auth_headers(client)

    r = client.post(
        f"/api/v1/prompts/{prompt.id}/versions",
        json={
            "content": "Bad content.",
            "commit_message": "draft",
        },
        headers=hdrs,
    )
    v_id = r.json()["version"]["id"]

    client.post(
        f"/api/v1/prompts/{prompt.id}/versions/{v_id}/submit", json={}, headers=hdrs
    )

    r = client.post(
        f"/api/v1/prompts/{prompt.id}/versions/{v_id}/reject",
        json={"reason": "off brand"},
        headers=hdrs,
    )
    assert r.status_code == 200
    assert r.json()["version"]["status"] == "rejected"


def test_rollback_creates_new_approved_version(client, db):
    """Rollback must create new version, not mutate history."""
    _, user, _, _, env = seed_org_user(db)
    prompt, v1 = seed_approved_prompt(db, env.id, user.id, content="Original content.")
    hdrs = auth_headers(client)

    # Approve v2 over it
    r = client.post(
        f"/api/v1/prompts/{prompt.id}/versions",
        json={
            "content": "New content.",
            "commit_message": "v2",
        },
        headers=hdrs,
    )
    v2_id = r.json()["version"]["id"]
    client.post(
        f"/api/v1/prompts/{prompt.id}/versions/{v2_id}/submit", json={}, headers=hdrs
    )
    client.post(
        f"/api/v1/prompts/{prompt.id}/versions/{v2_id}/approve", json={}, headers=hdrs
    )

    # Rollback to v1
    r = client.post(
        f"/api/v1/prompts/{prompt.id}/versions/{v1.id}/rollback", headers=hdrs
    )
    assert r.status_code == 200
    assert r.json()["message"]  # rollback succeeded — message present

    r = client.get(f"/api/v1/prompts/{prompt.id}", headers=hdrs)
    data = r.json()
    assert data["prompt"]["live_version"]["content"] == "Original content."
    assert data["prompt"]["live_version"]["version_num"] == 3  # new version, not v1
    assert len(data["versions"]) == 3


def test_get_prompt_returns_version_history(client, db):
    _, user, _, _, env = seed_org_user(db)
    prompt, _ = seed_approved_prompt(db, env.id, user.id)
    hdrs = auth_headers(client)

    r = client.get(f"/api/v1/prompts/{prompt.id}", headers=hdrs)
    assert r.status_code == 200
    data = r.json()
    assert len(data["versions"]) == 1
    assert data["versions"][0]["is_live"] is True


def test_list_prompts_returns_all_in_environment(client, db):
    _, user, _, _, env = seed_org_user(db)
    seed_approved_prompt(db, env.id, user.id, key="p.one")
    seed_approved_prompt(db, env.id, user.id, key="p.two")
    hdrs = auth_headers(client)

    r = client.get(f"/api/v1/prompts?environment_id={env.id}", headers=hdrs)
    assert r.status_code == 200
    assert len(r.json()["prompts"]) == 2


def test_unauthenticated_cannot_create_prompt(client, db):
    _, _, _, _, env = seed_org_user(db)
    r = client.post(
        "/api/v1/prompts",
        json={
            "environment_id": env.id,
            "key": "test.key",
            "content": "content",
        },
    )
    assert r.status_code == 401


def test_pending_review_appears_in_approval_queue(client, db):
    _, user, _, _, env = seed_org_user(db)
    prompt, _ = seed_approved_prompt(db, env.id, user.id)
    hdrs = auth_headers(client)

    # Create and submit v2
    r = client.post(
        f"/api/v1/prompts/{prompt.id}/versions",
        json={
            "content": "Needs review.",
            "commit_message": "v2",
        },
        headers=hdrs,
    )
    v_id = r.json()["version"]["id"]
    client.post(
        f"/api/v1/prompts/{prompt.id}/versions/{v_id}/submit",
        json={"note": "check this"},
        headers=hdrs,
    )

    # Approval queue must contain it
    r = client.get("/api/v1/approvals", headers=hdrs)
    assert r.status_code == 200
    pending = r.json()["pending"]
    assert len(pending) == 1
    assert pending[0]["prompt"]["key"] == prompt.key
    assert pending[0]["version"]["version_num"] == 2


def test_approving_clears_from_approval_queue(client, db):
    _, user, _, _, env = seed_org_user(db)
    prompt, _ = seed_approved_prompt(db, env.id, user.id)
    hdrs = auth_headers(client)

    r = client.post(
        f"/api/v1/prompts/{prompt.id}/versions",
        json={
            "content": "Needs review.",
            "commit_message": "v2",
        },
        headers=hdrs,
    )
    v_id = r.json()["version"]["id"]
    client.post(
        f"/api/v1/prompts/{prompt.id}/versions/{v_id}/submit", json={}, headers=hdrs
    )
    client.post(
        f"/api/v1/prompts/{prompt.id}/versions/{v_id}/approve", json={}, headers=hdrs
    )

    r = client.get("/api/v1/approvals", headers=hdrs)
    assert r.json()["pending"] == []
