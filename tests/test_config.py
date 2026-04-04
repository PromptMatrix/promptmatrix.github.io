"""
Config validation tests
========================
PromptMatrix local config accepts all environment values for ease of setup.
"""

from app.config import Settings


def test_default_config_has_sqlite():
    """OSS default is SQLite — no external DB required."""
    s = Settings()
    assert s.database_url.startswith("sqlite")


def test_default_app_env_is_development():
    """Default environment is development (set in .env.example)."""
    import os
    # When DATABASE_URL is set in test env, app_env comes from os.environ
    env_val = os.environ.get("APP_ENV", "development")
    s = Settings()
    assert s.app_env == env_val


def test_local_config_with_sqlite_always_passes():
    """SQLite is always valid in OSS — no production enforcement."""
    s = Settings(
        app_env="local",
        database_url="sqlite:///./promptmatrix.db",
        jwt_secret_key="any-key-is-fine-locally",
        encryption_key="",
    )
    assert s.database_url.startswith("sqlite")


def test_any_app_env_is_accepted():
    """OSS does not restrict app_env values — all are valid."""
    for env in ["local", "development", "staging", "production"]:
        s = Settings(app_env=env)
        assert s.app_env == env


def test_development_config_has_no_restrictions():
    """Dev mode must never fail — all defaults are fine."""
    s = Settings(app_env="development")
    assert s.app_env == "development"
    assert s.database_url.startswith("sqlite")


def test_rate_limit_default_is_sensible():
    s = Settings()
    assert s.serve_rate_limit_rpm == 600
    assert s.serve_rate_limit_rpm > 0


def test_rate_limit_can_be_disabled():
    s = Settings(serve_rate_limit_rpm=0)
    assert s.serve_rate_limit_rpm == 0


def test_valid_config_with_postgres_also_passes():
    """Even with postgres URL and strong keys, OSS config accepts it fine."""
    s = Settings(
        app_env="production",
        database_url="postgresql://user:pass@host:5432/db",
        jwt_secret_key="unique-jwt-secret-abc123",
        encryption_key="unique-enc-key-different-abc123",
    )
    assert s.app_env == "production"
