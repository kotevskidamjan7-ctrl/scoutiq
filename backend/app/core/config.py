"""Application settings, read from environment variables (or a .env file)."""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "ScoutIQ API"
    api_prefix: str = "/api/v1"
    database_url: str
    api_football_key: str | None = None  # only the importer needs it
    tm_duckdb_path: str = "/data/transfermarkt-datasets.duckdb"  # mounted read-only in Docker
    raw_dir: str = "/raw"  # cached API responses (mounted from ./raw)
    jwt_secret: str  # required: signs login tokens; set JWT_SECRET in .env, never commit it
    jwt_minutes: int = 60  # how long a login token stays valid

    @field_validator("jwt_secret")
    @classmethod
    def strong_secret(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError(
                "JWT_SECRET must be at least 32 characters. Generate one with: "
                "python -c \"import secrets; print(secrets.token_urlsafe(48))\""
            )
        return v


@lru_cache
def get_settings() -> Settings:
    """Load settings once and reuse them."""
    return Settings()
