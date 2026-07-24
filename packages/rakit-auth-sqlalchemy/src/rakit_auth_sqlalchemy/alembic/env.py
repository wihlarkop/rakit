import os
from logging.config import fileConfig

from alembic import context
from rakit_auth_sqlalchemy.models import Base
from sqlalchemy import engine_from_config, pool

# This file is only ever executed by the `alembic` CLI (e.g.
# `alembic -c packages/rakit-auth-sqlalchemy/src/rakit_auth_sqlalchemy/alembic.ini
# upgrade head`),
# never imported by rakit_auth_sqlalchemy's runtime package -- migrations
# are always an explicit, manual operation, never applied automatically at
# application startup.

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# A dedicated version table, never Alembic's default "alembic_version" --
# a host application almost certainly runs its own Alembic migrations
# against the same database with its own "alembic_version" table. Sharing
# that table would mean Rakit's auth-schema revision history and the
# host's own revision history fight over a single "current revision" row,
# and an upgrade for one would fail trying to locate a revision ID that
# belongs to the other's history entirely.
VERSION_TABLE = "rakit_auth_alembic_version"

# The RAKIT_AUTH_SQLALCHEMY_URL environment variable takes precedence over
# alembic.ini's own sqlalchemy.url, so a deployment never needs to store a
# real database URL in a checked-in file.
database_url = os.environ.get("RAKIT_AUTH_SQLALCHEMY_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table=VERSION_TABLE,
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
            connection=connection, target_metadata=target_metadata, version_table=VERSION_TABLE
        )
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
