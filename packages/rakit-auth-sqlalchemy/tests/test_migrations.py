"""Alembic migration integration tests.

Runs the real `alembic` upgrade/downgrade machinery (via `alembic.config`)
against a temporary on-disk SQLite database and the installed
`rakit_auth_sqlalchemy` package -- these are not unit tests against Python
functions, they exercise the actual migration scripts the way a deployment
would invoke them.
"""

from __future__ import annotations

import importlib.resources
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.util.exc import CommandError

VERSION_TABLE = "rakit_auth_alembic_version"


def _alembic_config(db_path: Path) -> Config:
    package_root = importlib.resources.files("rakit_auth_sqlalchemy")
    ini_path = Path(str(package_root)) / "alembic.ini"
    script_location = Path(str(package_root)) / "alembic"

    cfg = Config(str(ini_path))
    cfg.set_main_option("script_location", str(script_location))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


def _seed_full_dataset(db_path: Path) -> None:
    """Seeds a user, role, permission, their associations, and a session --
    everything the destructive downgrade used to drop."""
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO rakit_auth_users "
                "(id, email, password_hash, is_active, is_superuser, created_at, updated_at) "
                "VALUES (1, 'ada@example.com', 'hash', 1, 0, '2026-01-01', '2026-01-01')"
            )
        )
        conn.execute(sa.text("INSERT INTO rakit_auth_roles (id, name) VALUES (1, 'admin')"))
        conn.execute(
            sa.text(
                'INSERT INTO rakit_auth_permissions (id, key, label, "group", orphaned) '
                "VALUES (1, 'users.read', 'Read users', 'users', 0)"
            )
        )
        conn.execute(sa.text("INSERT INTO rakit_auth_user_roles (user_id, role_id) VALUES (1, 1)"))
        conn.execute(
            sa.text(
                "INSERT INTO rakit_auth_role_permissions (role_id, permission_id) VALUES (1, 1)"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO rakit_auth_sessions "
                "(id, token_hash, user_id, created_at, last_seen_at, "
                "idle_expires_at, absolute_expires_at) "
                "VALUES (1, 'a' * 64, 1, '2026-01-01', '2026-01-01', '2026-01-02', '2026-01-08')"
            )
        )
    engine.dispose()


def _seed_host_alembic_table(db_path: Path) -> None:
    """Simulates a host application's *own*, independent Alembic history in
    the same database -- using the default `alembic_version` table name,
    which must never collide with Rakit's own `rakit_auth_alembic_version`."""
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(sa.text("INSERT INTO alembic_version (version_num) VALUES ('host-rev-1')"))
    engine.dispose()


def _table_names(db_path: Path) -> set[str]:
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        return set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()


def _row_count(db_path: Path, table: str) -> int:
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as conn:
            return conn.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
    finally:
        engine.dispose()


def _current_revision(db_path: Path) -> str | None:
    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as conn:
            if VERSION_TABLE not in sa.inspect(engine).get_table_names():
                return None
            return conn.execute(
                sa.text(f"SELECT version_num FROM {VERSION_TABLE}")
            ).scalar_one_or_none()
    finally:
        engine.dispose()


AUTH_TABLES = {
    "rakit_auth_users",
    "rakit_auth_roles",
    "rakit_auth_permissions",
    "rakit_auth_user_roles",
    "rakit_auth_role_permissions",
    "rakit_auth_sessions",
}


def test_downgrade_to_base_refuses_and_raises(tmp_path) -> None:
    db_path = tmp_path / "auth.db"
    cfg = _alembic_config(db_path)
    command.upgrade(cfg, "head")

    with pytest.raises((RuntimeError, CommandError)):
        command.downgrade(cfg, "base")


def test_downgrade_refusal_preserves_seeded_data_and_head_revision(tmp_path) -> None:
    db_path = tmp_path / "auth.db"
    cfg = _alembic_config(db_path)
    command.upgrade(cfg, "head")

    _seed_full_dataset(db_path)
    _seed_host_alembic_table(db_path)

    head_revision = _current_revision(db_path)
    assert head_revision is not None

    with pytest.raises((RuntimeError, CommandError)):
        command.downgrade(cfg, "base")

    assert _current_revision(db_path) == head_revision
    assert _table_names(db_path) >= AUTH_TABLES
    assert _row_count(db_path, "rakit_auth_users") == 1
    assert _row_count(db_path, "rakit_auth_roles") == 1
    assert _row_count(db_path, "rakit_auth_permissions") == 1
    assert _row_count(db_path, "rakit_auth_user_roles") == 1
    assert _row_count(db_path, "rakit_auth_role_permissions") == 1
    assert _row_count(db_path, "rakit_auth_sessions") == 1

    assert "alembic_version" in _table_names(db_path)
    assert _row_count(db_path, "alembic_version") == 1
