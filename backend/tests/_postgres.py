"""Shared plumbing for the tests that need a real PostgreSQL.

Kept out of ``conftest.py`` so importing it is an explicit decision: a test module
that imports this is declaring that it is an integration test.
"""

from __future__ import annotations

import os
from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config

from alembic import command

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://peblo:peblo@localhost:5432/peblo_tv_test"
)
ASYNC_TEST_DATABASE_URL = TEST_DATABASE_URL.replace("+psycopg", "+asyncpg")

SKIP_REASON = f"no PostgreSQL at {TEST_DATABASE_URL} — the schema is UNVERIFIED, not passing"


def postgres_available() -> bool:
    try:
        engine = sa.create_engine(TEST_DATABASE_URL, connect_args={"connect_timeout": 2})
    except Exception:
        return False
    try:
        with engine.connect():
            return True
    except Exception:
        return False
    finally:
        engine.dispose()


def alembic_config() -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    return config


def reset_and_migrate() -> sa.Engine:
    """Drop everything and apply the migration from scratch."""
    engine = sa.create_engine(TEST_DATABASE_URL)
    with engine.begin() as connection:
        connection.execute(sa.text("DROP SCHEMA public CASCADE"))
        connection.execute(sa.text("CREATE SCHEMA public"))
    command.upgrade(alembic_config(), "head")
    return engine
