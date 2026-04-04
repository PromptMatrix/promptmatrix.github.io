from functools import lru_cache
from typing import Self

from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Core ─────────────────────────────────────────────────────────────
    database_url: str = "sqlite:///./promptmatrix.db"
    jwt_secret_key: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30
    encryption_key: str = ""
    app_env: str = "development"
    app_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:8000"
    debug: bool = False

    # ── Local Performance (Hot Path) ────────────────────────────────────
    prompt_cache_ttl_seconds: int = 60  # Increased for efficiency
    api_key_cache_ttl_seconds: int = 600  # 10 minutes cache for keys
    serve_rate_limit_rpm: int = 600  # Requests per minute per API key

    @model_validator(mode="after")
    def validate_security(self) -> Self:
        if self.app_env == "production" and not self.encryption_key:
            raise ValueError(
                "CRITICAL SECURITY ERROR: encryption_key MUST be set in production. "
                "Falling back to jwt_secret_key is a data-loss risk during key rotation."
            )
        return self

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
