from datetime import timedelta

import pytest
from rakit_auth_sqlalchemy.backend import SQLAlchemyAuthBackend
from rakit_auth_sqlalchemy.discovery import AUTH_SQLALCHEMY_INTEGRATION
from rakit_auth_sqlalchemy.plugin import SQLAlchemyAuthPlugin
from rakit_auth_sqlalchemy.sessions import SQLAlchemySessionStore
from rakit_core.errors import RakitError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def _session_factory() -> async_sessionmaker:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    return async_sessionmaker(engine, expire_on_commit=False)


def test_plugin_composes_a_matching_backend_and_session_store() -> None:
    factory = _session_factory()
    plugin = SQLAlchemyAuthPlugin(factory)

    assert isinstance(plugin.auth_backend, SQLAlchemyAuthBackend)
    assert isinstance(plugin.session_store, SQLAlchemySessionStore)
    assert plugin.auth_backend._session_factory is factory
    assert plugin.session_store._session_factory is factory


def test_auth_backend_and_session_store_share_discovery_identity() -> None:
    plugin = SQLAlchemyAuthPlugin(_session_factory())

    assert AUTH_SQLALCHEMY_INTEGRATION.integration_id == "auth.sqlalchemy"
    assert AUTH_SQLALCHEMY_INTEGRATION.category == "authentication"
    assert plugin.auth_backend.rakit_integration is AUTH_SQLALCHEMY_INTEGRATION
    assert plugin.session_store.rakit_integration is AUTH_SQLALCHEMY_INTEGRATION


def test_plugin_accepts_a_custom_password_hasher() -> None:
    from rakit_auth_sqlalchemy.passwords import Argon2PasswordHasher

    hasher = Argon2PasswordHasher()
    plugin = SQLAlchemyAuthPlugin(_session_factory(), password_hasher=hasher)

    assert plugin.auth_backend._password_hasher is hasher


def test_plugin_accepts_custom_session_timeouts() -> None:
    plugin = SQLAlchemyAuthPlugin(
        _session_factory(),
        idle_timeout=timedelta(minutes=5),
        absolute_timeout=timedelta(hours=1),
    )

    assert plugin.session_store._idle_timeout == timedelta(minutes=5)
    assert plugin.session_store._absolute_timeout == timedelta(hours=1)


def test_plugin_rejects_invalid_session_timeouts_before_use() -> None:
    with pytest.raises(RakitError) as exc_info:
        SQLAlchemyAuthPlugin(
            _session_factory(),
            idle_timeout=timedelta(days=2),
            absolute_timeout=timedelta(days=1),
        )
    assert exc_info.value.details["reason"] == "idle_timeout_exceeds_absolute"
