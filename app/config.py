from pydantic_settings import BaseSettings
from pydantic import model_validator
from functools import lru_cache


class Settings(BaseSettings):
    # ── Core ─────────────────────────────────────────────────────────────
    database_url: str = "sqlite:///./promptmatrix.db"
    jwt_secret_key: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30
    encryption_key: str = ""
    app_env: str = "local"
    app_url: str = "http://localhost:8000"
    debug: bool = False

    # ── Local Performance ────────────────────────────────────────────────
    prompt_cache_ttl_seconds: int = 30
    api_key_cache_ttl_seconds: int = 300
    serve_rate_limit_rpm: int = 600

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
