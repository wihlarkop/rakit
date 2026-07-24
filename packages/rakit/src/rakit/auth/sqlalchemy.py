from .._optional import optional_import

with optional_import("rakit_auth_sqlalchemy", extra="auth-sqlalchemy"):
    import rakit_auth_sqlalchemy  # noqa: F401

from rakit_auth_sqlalchemy.plugin import SQLAlchemyAuthPlugin

__all__ = ["SQLAlchemyAuthPlugin"]
