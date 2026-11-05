"""Test setup: every test run uses a separate database, never the real one.

TEST_DATABASE_URL (set in docker-compose.yml) points at '<db>_test'.
The database is created if missing and migrated to the latest version,
then the app is pointed at it before any app module is imported.
"""

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

TEST_URL = os.environ.get("TEST_DATABASE_URL")
if not TEST_URL:
    raise pytest.UsageError("TEST_DATABASE_URL is not set; refusing to run tests against the real database.")

os.environ["DATABASE_URL"] = TEST_URL  # must happen before app.core.config is imported
os.environ.setdefault("JWT_SECRET", "test-only-secret-never-used-outside-tests-0123456789")


def _create_database_if_missing(url_str: str) -> None:
    url = make_url(url_str)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": url.database})
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()


def _migrate() -> None:
    from alembic import command
    from alembic.config import Config

    backend = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "alembic"))
    command.upgrade(cfg, "head")


_create_database_if_missing(TEST_URL)
_migrate()
