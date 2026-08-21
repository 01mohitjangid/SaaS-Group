"""Alembic environment.

Migrations run synchronously (psycopg) even though the app is async (asyncpg) —
the URL is derived in one place, ``Settings.sync_database_url``.
"""

from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.config import get_settings
from app.db import (
    Base,
    models,  # noqa: F401
)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# A caller (the migration tests) may have already pointed this at a scratch
# database; only fall back to the configured one when it has not.
if not config.get_main_option("sqlalchemy.url", None):
    config.set_main_option("sqlalchemy.url", get_settings().sync_database_url)
target_metadata = Base.metadata

#: Tables that exist on purpose without a mapped model. `storage_objects` holds artwork
#: bytes and belongs to the storage layer, which sits below the domain — giving it an ORM
#: class would invite the rest of the app to read it directly instead of going through
#: `ObjectStorage`. Autogenerate would otherwise report it as a table to drop.
UNMAPPED_TABLES = {"storage_objects"}


def include_object(
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    return not (type_ == "table" and name in UNMAPPED_TABLES)


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
