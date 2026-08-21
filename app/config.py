from functools import lru_cache

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
