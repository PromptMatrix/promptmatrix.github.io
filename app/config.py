from pydantic_settings import BaseSettings
from pydantic import model_validator
from functools import lru_cache

class Settings(BaseSettings):
    database_url: str = "sqlite:///./promptmatrix.db"
    jwt_secret_key: str = "dev-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30
    encryption_key: str = ""
    app_env: str = "development"
    app_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:3000"
    debug: bool = False
    resend_api_key: str = ""
    from_email: str = "noreply@promptmatrix.local"
    upstash_redis_rest_url: str = ""
    upstash_redis_rest_token: str = ""
    prompt_cache_ttl_seconds: int = 30
    api_key_cache_ttl_seconds: int = 300
    serve_rate_limit_rpm: int = 600

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        if self.app_env == "production":
            errors = []
            if self.jwt_secret_key == "dev-secret-change-in-production":
                errors.append("JWT_SECRET_KEY must be set")
            if not self.encryption_key:
                errors.append("ENCRYPTION_KEY must be set")
            if self.encryption_key and self.encryption_key == self.jwt_secret_key:
                errors.append("ENCRYPTION_KEY and JWT_SECRET_KEY must be different")
            # Relaxed for self-hosting: Allow SQLite in production mode
            if errors:
                raise ValueError("Production startup failed:\n" + "\n".join(f"  • {e}" for e in errors))
        return self

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

@lru_cache()
def get_settings() -> Settings:
    return Settings()
