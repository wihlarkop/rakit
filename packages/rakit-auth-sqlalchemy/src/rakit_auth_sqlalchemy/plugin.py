from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .backend import SQLAlchemyAuthBackend
from .passwords import Argon2PasswordHasher
from .sessions import SQLAlchemySessionStore


class SQLAlchemyAuthPlugin:
    """Composes the concrete SQLAlchemy `AuthBackend`, `SessionStore`, and
    password hasher a caller needs to enable built-in authentication.

    Not a `rakit_core.compiler.Plugin` (it registers nothing into the DI
    registry) -- construct it and pass its `.auth_backend`/`.session_store`
    straight to `Admin(...)`'s own constructor parameters, since those must
    be supplied *before* `Admin.install()`/`.compile()` run::

        from rakit.auth.sqlalchemy import SQLAlchemyAuthPlugin

        auth = SQLAlchemyAuthPlugin(session_factory)
        admin = Admin(..., auth_backend=auth.auth_backend, session_store=auth.session_store)
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        password_hasher: Argon2PasswordHasher | None = None,
        idle_timeout: timedelta | None = None,
        absolute_timeout: timedelta | None = None,
    ) -> None:
        hasher = password_hasher or Argon2PasswordHasher()
        self.auth_backend = SQLAlchemyAuthBackend(session_factory, password_hasher=hasher)

        session_store_kwargs: dict[str, timedelta] = {}
        if idle_timeout is not None:
            session_store_kwargs["idle_timeout"] = idle_timeout
        if absolute_timeout is not None:
            session_store_kwargs["absolute_timeout"] = absolute_timeout
        self.session_store = SQLAlchemySessionStore(session_factory, **session_store_kwargs)
