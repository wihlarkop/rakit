from rakit_auth_sqlalchemy.migrations import ALEMBIC_VERSION_TABLE
from rakit_auth_sqlalchemy.models import Base


def test_rakit_owned_auth_tables_use_framework_namespace() -> None:
    table_names = set(Base.metadata.tables)

    assert table_names
    assert all(name.startswith("rakit_") for name in table_names)
    assert {
        "rakit_auth_users",
        "rakit_auth_roles",
        "rakit_auth_permissions",
        "rakit_auth_user_roles",
        "rakit_auth_role_permissions",
        "rakit_auth_sessions",
        "rakit_auth_idempotency",
    } <= table_names


def test_auth_migration_stream_uses_dedicated_version_table() -> None:
    assert ALEMBIC_VERSION_TABLE == "rakit_auth_alembic_version"
    assert ALEMBIC_VERSION_TABLE.startswith("rakit_")
    assert ALEMBIC_VERSION_TABLE != "alembic_version"
