from ._optional import optional_import

with optional_import("rakit_sqlalchemy", extra="sqlalchemy"):
    import rakit_sqlalchemy  # noqa: F401

from rakit_sqlalchemy.plugin import SQLAlchemyPlugin

__all__ = ["SQLAlchemyPlugin"]
