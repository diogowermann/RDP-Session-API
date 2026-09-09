from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RDP_SESSION_",
        env_file=".env",
        extra="ignore",
    )

    database_url: str = "sqlite:///./rdp-session.db"
    log_level: str = "INFO"
    query_api_key: str | None = None

    correlation_enabled: bool = False
    resolver_base_url: str | None = None
    resolver_api_key: str | None = None
    resolver_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    correlation_poll_seconds: int = Field(default=30, ge=5, le=3600)
    correlation_batch_size: int = Field(default=100, ge=1, le=1000)
    correlation_max_attempts: int = Field(default=5, ge=1, le=20)
    correlation_retry_base_seconds: int = Field(default=60, ge=5, le=3600)


@lru_cache
def get_settings() -> Settings:
    return Settings()
