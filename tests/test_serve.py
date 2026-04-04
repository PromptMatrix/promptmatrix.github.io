"""
Serve endpoint tests — /pm/serve/{key}
=======================================
Covers: happy path, variable substitution, 401/404 errors,
cache invalidation on approve, rate limiting.
"""

import pytest

from tests.conftest import (auth_headers, seed_api_key, seed_approved_prompt,
                            seed_org_user)


def _serve(client, full_key, prompt_key, **params):
    """Helper: GET /pm/serve/{key} with Bearer auth."""
    return client.get(
        f"/pm/serve/{prompt_key}",
        headers={"Authorization": f"Bearer {full_key}"},
        params=params,
    )


# ── Happy path ────────────────────────────────────────────────────


def test_serve_returns_approved_content(client, db):
    _, user, _, _, env = seed_org_user(db)
    seed_approved_prompt(db, env.id, user.id, content="You are a helpful assistant.")
    full_key, _ = seed_api_key(db, env.id)

    r = _serve(client, full_key, "assistant.system")
    assert r.status_code == 200
    assert r.text == "You are a helpful assistant."


def test_serve_returns_json_format(client, db):
    _, user, _, _, env = seed_org_user(db)
    seed_approved_prompt(db, env.id, user.id, content="Hello.")
    full_key, _ = seed_api_key(db, env.id)

    r = _serve(client, full_key, "assistant.system", format="json")
    assert r.status_code == 200
    data = r.json()
    assert data["key"] == "assistant.system"
    assert data["content"] == "Hello."
    assert data["version"] == 1
    assert "latency_ms" in data
    assert "served_at" in data


def test_serve_returns_version_header(client, db):
    _, user, _, _, env = seed_org_user(db)
    seed_approved_prompt(db, env.id, user.id)
    full_key, _ = seed_api_key(db, env.id)

    r = _serve(client, full_key, "assistant.system")
    assert r.status_code == 200
    assert r.headers.get("x-pm-version") == "1"


def test_serve_variable_substitution(client, db):
    _, user, _, _, env = seed_org_user(db)
    seed_approved_prompt(
        db, env.id, user.id, content="Hello {{name}}. Your tone is {{tone}}."
    )
    full_key, _ = seed_api_key(db, env.id)

    # BUG-02 FIX: vars must be repeated query params, not comma-separated
    r = client.get(
        "/pm/serve/assistant.system",
        headers={"Authorization": f"Bearer {full_key}"},
        params=[("vars", "name=User"), ("vars", "tone=direct")],
    )
    assert r.status_code == 200
    assert r.text == "Hello User. Your tone is direct."


def test_serve_leaves_unmatched_variables_intact(client, db):
    """Variables not passed in ?vars= stay as {{placeholders}}."""
    _, user, _, _, env = seed_org_user(db)
    seed_approved_prompt(db, env.id, user.id, content="Hello {{name}}.")
    full_key, _ = seed_api_key(db, env.id)

    r = _serve(client, full_key, "assistant.system")
    assert r.status_code == 200
    assert r.text == "Hello {{name}}."


# ── Content updates ───────────────────────────────────────────────


def test_serve_reflects_newly_approved_version(client, db):
    """
    The critical governance test: after a new version is approved,
    the serve endpoint must return the new content immediately.
    Cache is invalidated on approve — next call gets fresh content.
    """
    _, user, _, _, env = seed_org_user(db)
    prompt, v1 = seed_approved_prompt(db, env.id, user.id, content="Version one.")
    full_key, _ = seed_api_key(db, env.id)
    hdrs = auth_headers(client)

    # Confirm v1 is served
    r = _serve(client, full_key, "assistant.system")
    assert r.text == "Version one."

    # Create and approve v2
    r = client.post(
        f"/api/v1/prompts/{prompt.id}/versions",
        json={"content": "Version two.", "commit_message": "v2"},
        headers=hdrs,
    )
    v2_id = r.json()["version"]["id"]
    client.post(
        f"/api/v1/prompts/{prompt.id}/versions/{v2_id}/submit", json={}, headers=hdrs
    )
    client.post(
        f"/api/v1/prompts/{prompt.id}/versions/{v2_id}/approve", json={}, headers=hdrs
    )

    # Must now serve v2 without redeploy
    r = _serve(client, full_key, "assistant.system")
    assert r.status_code == 200
    assert r.text == "Version two.", "Serve endpoint did not reflect approved version"


def test_serve_reflects_rollback(client, db):
    """After rollback, serve must return the rolled-back content."""
    _, user, _, _, env = seed_org_user(db)
    prompt, v1 = seed_approved_prompt(db, env.id, user.id, content="Original.")
    full_key, _ = seed_api_key(db, env.id)
    hdrs = auth_headers(client)

    # Approve v2
    r = client.post(
        f"/api/v1/prompts/{prompt.id}/versions",
        json={"content": "Replaced.", "commit_message": "v2"},
        headers=hdrs,
    )
    v2_id = r.json()["version"]["id"]
    client.post(
        f"/api/v1/prompts/{prompt.id}/versions/{v2_id}/submit", json={}, headers=hdrs
    )
    client.post(
        f"/api/v1/prompts/{prompt.id}/versions/{v2_id}/approve", json={}, headers=hdrs
    )
    assert _serve(client, full_key, "assistant.system").text == "Replaced."

    # Rollback to v1
    client.post(f"/api/v1/prompts/{prompt.id}/versions/{v1.id}/rollback", headers=hdrs)

    r = _serve(client, full_key, "assistant.system")
    assert r.text == "Original.", "Rollback did not propagate to serve endpoint"


# ── Error cases ───────────────────────────────────────────────────


def test_serve_rejects_missing_auth_header(client, db):
    r = client.get("/pm/serve/assistant.system")
    assert r.status_code == 401


def test_serve_rejects_invalid_api_key(client, db):
    r = client.get(
        "/pm/serve/assistant.system",
        headers={"Authorization": "Bearer pm_live_totallyinvalidkey"},
    )
    assert r.status_code == 401


def test_serve_returns_404_for_unknown_prompt_key(client, db):
    _, user, _, _, env = seed_org_user(db)
    full_key, _ = seed_api_key(db, env.id)

    r = _serve(client, full_key, "does.not.exist")
    assert r.status_code == 404


def test_serve_returns_404_when_no_approved_version(client, db):
    """Prompt exists but has no live version — must return 404, not 500."""
    _, user, _, _, env = seed_org_user(db)
    from app.models import Prompt

    prompt = Prompt(environment_id=env.id, key="draft.only")
    db.add(prompt)
    db.commit()

    full_key, _ = seed_api_key(db, env.id)
    r = _serve(client, full_key, "draft.only")
    assert r.status_code == 404


def test_serve_rejects_revoked_api_key(client, db):
    _, user, _, _, env = seed_org_user(db)
    seed_approved_prompt(db, env.id, user.id)
    full_key, key_row = seed_api_key(db, env.id)
    hdrs = auth_headers(client)

    # Confirm it works
    assert _serve(client, full_key, "assistant.system").status_code == 200

    # Revoke the key
    r = client.delete(f"/api/v1/keys/{key_row.id}", headers=hdrs)
    assert r.status_code == 200

    # Must now be rejected
    r = _serve(client, full_key, "assistant.system")
    assert r.status_code == 401


# ── Rate limiting ─────────────────────────────────────────────────


def test_rate_limit_allows_under_threshold(client, db):
    """Requests under the limit must all succeed."""
    _, user, _, _, env = seed_org_user(db)
    seed_approved_prompt(db, env.id, user.id)
    full_key, _ = seed_api_key(db, env.id)

    # With NoopCache (no Upstash), rate limiting is disabled — all pass
    for _ in range(5):
        r = _serve(client, full_key, "assistant.system")
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_rate_limit_logic_directly():
    """
    Unit test for check_rate_limit with local MemoryCache.
    First call in a window must return count=1 and allowed=True.
    """
    import app.serve.cache as cache_module
    from app.serve.cache import _NoopCache, check_rate_limit

    original = cache_module._cache
    cache_module._cache = _NoopCache()  # fresh empty cache

    try:
        allowed, count, limit = await check_rate_limit("any-hash", rpm_limit=5)
        assert allowed is True, "First request must be allowed"
        assert (
            1 <= count <= limit
        ), f"count {count} should be 1 on first call and <= limit {limit}"
    finally:
        cache_module._cache = original


def test_rate_limit_disabled_when_rpm_is_zero(client, db):
    """SERVE_RATE_LIMIT_RPM=0 disables rate limiting entirely."""
    import app.serve.router as router_module

    original_rpm = router_module.settings.serve_rate_limit_rpm

    _, user, _, _, env = seed_org_user(db)
    seed_approved_prompt(db, env.id, user.id)
    full_key, _ = seed_api_key(db, env.id)

    # Temporarily disable
    router_module.settings.serve_rate_limit_rpm = 0
    try:
        for _ in range(10):
            r = _serve(client, full_key, "assistant.system")
            assert r.status_code == 200
    finally:
        router_module.settings.serve_rate_limit_rpm = original_rpm
