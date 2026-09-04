"""Environment-driven settings. No module-level mutable application state."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All values are environment-specific and MUST be set per deployment.

    Secrets are SecretStr so accidental str(settings) / logs do not dump them.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    APP_NAME: str = "MediKiosk-Backend"
    APP_ENV: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    API_V1_PREFIX: str = "/api/v1"
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Postgres — SECRET password lives inside DATABASE_URL
    DATABASE_URL: SecretStr = Field(
        ...,
        description="asyncpg URL, e.g. postgresql+asyncpg://user:pass@host:5432/db",
    )
    DB_POOL_SIZE: int = Field(
        default=8,
        description="Per-process pool_size. Recalculate when replica count changes.",
    )
    DB_MAX_OVERFLOW: int = Field(default=4)
    DB_POOL_TIMEOUT_SECONDS: int = Field(default=30)
    DB_POOL_RECYCLE_SECONDS: int = Field(default=1800)

    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: SecretStr | None = None
    REDIS_DB_SESSION: int = 0
    REDIS_DB_CELERY_BROKER: int = 1
    REDIS_DB_CELERY_RESULT: int = 2
    REDIS_DB_LOCKS: int = 3
    REDIS_DB_RATELIMIT: int = 4
    REDIS_PREFIX_SESSION: str = "medikiosk:session:"
    REDIS_PREFIX_INTERVIEW: str = "medikiosk:interview:"
    REDIS_PREFIX_WS: str = "medikiosk:ws:"
    REDIS_PREFIX_LOCK: str = "medikiosk:lock:"
    REDIS_PREFIX_RATELIMIT: str = "medikiosk:rl:"
    REDIS_PREFIX_IDEMPOTENCY: str = "medikiosk:idem:"

    INTERVIEW_STATE_TTL_SECONDS: int = 1800
    IDEMPOTENCY_TTL_SECONDS: int = 86400
    LOCK_TTL_SECONDS: int = 15

    JWT_SECRET_KEY: SecretStr
    JWT_REFRESH_SECRET_KEY: SecretStr
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TTL_MINUTES: int = 15
    JWT_REFRESH_TTL_DAYS: int = 7
    JWT_ISSUER: str = "medikiosk"

    FIELD_ENCRYPTION_KEY: SecretStr
    PII_LOOKUP_HMAC_KEY: SecretStr
    FIELD_ENCRYPTION_KEY_ID: str = "v1"

    RATE_LIMIT_PUBLIC_PER_MINUTE: int = 60
    RATE_LIMIT_AUTH_PER_MINUTE: int = 10

    CORS_ORIGINS: str = "http://localhost:3000"

    UPLOAD_TEMP_DIR: str = "/app/uploads/temp_scans"
    UPLOAD_VAULT_DIR: str = "/app/uploads/encrypted_vault"
    TEMP_SCAN_TTL_SECONDS: int = 3600

    BHASHINI_API_KEY: SecretStr | None = None
    BHASHINI_BASE_URL: str = "https://bhashini.gov.in/api"
    ABDM_CLIENT_ID: str | None = None
    ABDM_CLIENT_SECRET: SecretStr | None = None
    ABDM_BASE_URL: str = "https://dev.abdm.gov.in"
    ABDM_WEBHOOK_SECRET: SecretStr | None = None
    OCR_VENDOR_API_KEY: SecretStr | None = None
    OCR_VENDOR_BASE_URL: str | None = None

    CELERY_BROKER_URL: str = "redis://redis:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://redis:6379/2"

    @field_validator("DEBUG")
    @classmethod
    def no_debug_in_production(cls, value: bool, info: ValidationInfo):
        env = info.data.get("APP_ENV")
        if env == "production" and value:
            raise ValueError("DEBUG must be false when APP_ENV=production")
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def database_url_sync(self) -> str:
        """psycopg2 URL for Alembic. Never log this — it embeds the DB password."""
        return self.DATABASE_URL.get_secret_value().replace(
            "postgresql+asyncpg://",
            "postgresql+psycopg2://",
            1,
        )

    def redis_url(self, db: int) -> str:
        password = self.REDIS_PASSWORD.get_secret_value() if self.REDIS_PASSWORD else None
        auth = f":{password}@" if password else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{db}"


@lru_cache
def get_settings() -> Settings:
    """Process-local cached immutable config. Not session/user state."""
    return Settings()  # type: ignore[call-arg]
