from pydantic_settings import BaseSettings
from pydantic import model_validator
from functools import lru_cache


class Settings(BaseSettings):
    # Database — use Supabase transaction pooler URL (port 6543)
    database_url: str = "sqlite:///./promptmatrix.db"

    # Auth
    jwt_secret_key: str = "dev-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30

    # Encryption — SEPARATE from JWT secret.
    # Rotating jwt_secret_key must never break stored LLM keys.
    # Generate: python -c "import secrets; print(secrets.token_hex(32))"
    encryption_key: str = ""

    # App
    app_env: str = "development"
    app_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:3000"
    debug: bool = False

    # Email (Resend — free: 100 emails/day)
    resend_api_key: str = ""
    from_email: str = "noreply@promptmatrix.io"

    # Payments
    razorpay_webhook_secret: str = ""
    razorpay_key_id: str = ""

    # Cache (Upstash Redis — free: 10k commands/day)
    upstash_redis_rest_url: str = ""
    upstash_redis_rest_token: str = ""

    # Cache TTLs (seconds)
    prompt_cache_ttl_seconds: int = 30
    api_key_cache_ttl_seconds: int = 300

    # Rate limiting — requests per minute per API key on /pm/serve
    # Requires Upstash Redis. Set to 0 to disable.
    serve_rate_limit_rpm: int = 600

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        """Hard fail on startup if required production secrets are missing."""
        if self.app_env == "production":
            errors = []

            if self.jwt_secret_key == "dev-secret-change-in-production":
                errors.append("JWT_SECRET_KEY must be set")

            if not self.encryption_key:
                errors.append(
                    "ENCRYPTION_KEY must be set — "
                    "generate: python -c \"import secrets; print(secrets.token_hex(32))\""
                )

            if self.encryption_key and self.encryption_key == self.jwt_secret_key:
                errors.append(
                    "ENCRYPTION_KEY and JWT_SECRET_KEY must be different values"
                )

            if not self.database_url.startswith("postgresql"):
                errors.append("DATABASE_URL must be a PostgreSQL URL in production")

            if errors:
                raise ValueError(
                    "Production startup failed — fix these environment variables:\n" +
                    "\n".join(f"  • {e}" for e in errors)
                )

        return self

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
