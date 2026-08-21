from .._install import InstallExtra
from .._optional import OptionalDependency, optional_import

with optional_import(
    "rakit_auth_sqlalchemy",
    dependency=OptionalDependency(
        extra=InstallExtra.AUTH_SQLALCHEMY,
        label="SQLAlchemy authentication",
    ),
):
    import rakit_auth_sqlalchemy  # noqa: F401

from rakit_auth_sqlalchemy.idempotency import SQLAlchemyIdempotencyStore
from rakit_auth_sqlalchemy.models import Base as AuthBase
from rakit_auth_sqlalchemy.models import Permission, Role, User
from rakit_auth_sqlalchemy.passwords import Argon2PasswordHasher
from rakit_auth_sqlalchemy.plugin import SQLAlchemyAuthPlugin
from rakit_auth_sqlalchemy.rbac import PermissionSyncResult, sync_permissions

__all__ = [
    "Argon2PasswordHasher",
    "AuthBase",
    "Permission",
    "PermissionSyncResult",
    "Role",
    "SQLAlchemyAuthPlugin",
    "SQLAlchemyIdempotencyStore",
    "User",
    "sync_permissions",
]
