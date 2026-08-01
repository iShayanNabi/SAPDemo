"""Alembic environment.

The database URL comes from the application settings (and therefore from
``.env``), so a migration run always targets the same database the app uses.
Batch mode is enabled for SQLite, which cannot ALTER columns natively.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.models import Base  # noqa: E402  (imports every model)

config = context.config


def _database_url() -> str:
    """Resolve the database to migrate.

    Precedence, most explicit first:

    1. ``-x db_url=...`` on the command line - the escape hatch for migrating a
       database that is not the one in ``.env`` (a staging copy, a scratch
       database, a test).
    2. a URL already set on the Alembic config by whoever called us
       programmatically - this is what lets a test migrate a temporary file
       instead of the developer's real database.
    3. ``settings.database_url``, i.e. ``.env``. The normal case.

    Reading the settings *unconditionally* was wrong for exactly one reason,
    and it was not hypothetical: a test that built its own Alembic config and
    pointed it at a temporary file was silently migrated over the application's
    own database instead.
    """
    supplied = context.get_x_argument(as_dictionary=True).get("db_url")
    if supplied:
        return supplied
    configured = config.get_main_option("sqlalchemy.url", None)
    if configured:
        return configured
    return settings.database_url


DATABASE_URL = _database_url()
config.set_main_option("sqlalchemy.url", DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL without connecting to a database."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=DATABASE_URL.startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=DATABASE_URL.startswith("sqlite"),
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
