"""Application settings, read from environment variables (or a .env file)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "ScoutIQ API"
    api_prefix: str = "/api/v1"
    database_url: str
    api_football_key: str | None = None  # only the importer needs it
    tm_duckdb_path: str = "/data/transfermarkt-datasets.duckdb"  # mounted read-only in Docker
    raw_dir: str = "/raw"  # cached API responses (mounted from ./raw)


@lru_cache
def get_settings() -> Settings:
    """Load settings once and reuse them."""
    return Settings()
