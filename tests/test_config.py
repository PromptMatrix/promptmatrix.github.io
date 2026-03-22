"""
Config validation tests
========================
Hard-fail production startup checks:
  - default JWT secret rejected
  - missing ENCRYPTION_KEY rejected
  - identical JWT + ENC keys rejected
  - SQLite rejected in production
  - valid config accepted
"""

import pytest
from app.config import Settings


def test_valid_production_config_passes():
    s = Settings(
        app_env="production",
        database_url="postgresql://user:pass@host:6543/db",
        jwt_secret_key="unique-jwt-secret-abc123",
        encryption_key="unique-enc-key-different-abc123",
    )
    assert s.app_env == "production"


def test_production_rejects_default_jwt_secret():
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        Settings(
            app_env="production",
            database_url="postgresql://x/db",
            jwt_secret_key="dev-secret-change-in-production",
            encryption_key="some-enc-key",
        )


def test_production_rejects_missing_encryption_key():
    with pytest.raises(ValueError, match="ENCRYPTION_KEY"):
        Settings(
            app_env="production",
            database_url="postgresql://x/db",
            jwt_secret_key="good-jwt-key",
            encryption_key="",
        )


def test_production_rejects_identical_jwt_and_encryption_keys():
    with pytest.raises(ValueError):
        Settings(
            app_env="production",
            database_url="postgresql://x/db",
            jwt_secret_key="same-key-for-both",
            encryption_key="same-key-for-both",
        )


def test_production_rejects_sqlite_database():
    with pytest.raises(ValueError, match="DATABASE_URL"):
        Settings(
            app_env="production",
            database_url="sqlite:///./local.db",
            jwt_secret_key="good-jwt",
            encryption_key="good-enc-different",
        )


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
