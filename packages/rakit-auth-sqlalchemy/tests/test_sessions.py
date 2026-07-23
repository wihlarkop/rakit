from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from rakit_auth_sqlalchemy.models import Base, User
from rakit_auth_sqlalchemy.sessions import SQLAlchemySessionStore
from rakit_core.auth import Principal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(User(id=1, email="ada@example.com", password_hash="hash"))
        await session.commit()
    yield factory
    await engine.dispose()


async def test_create_returns_raw_token_and_record(session_factory) -> None:
    store = SQLAlchemySessionStore(session_factory)
    principal = Principal(subject_id="1", authenticated=True)

    raw_token, record = await store.create(principal)

    assert raw_token
    assert record.subject_id == "1"


async def test_raw_token_never_stored_in_database(session_factory) -> None:
    store = SQLAlchemySessionStore(session_factory)
    principal = Principal(subject_id="1", authenticated=True)

    raw_token, _ = await store.create(principal)

    async with session_factory() as session:
        from rakit_auth_sqlalchemy.models import Session as SessionRow

        stored = (await session.execute(select(SessionRow))).scalar_one()
        assert stored.token_hash != raw_token
        assert raw_token not in stored.token_hash


async def test_resolve_returns_matching_record_for_a_valid_token(session_factory) -> None:
    store = SQLAlchemySessionStore(session_factory)
    principal = Principal(subject_id="1", authenticated=True)
    raw_token, created = await store.create(principal)

    resolved = await store.resolve(raw_token)

    assert resolved is not None
    assert resolved.session_id == created.session_id
    assert resolved.subject_id == "1"


async def test_resolve_returns_none_for_an_unknown_token(session_factory) -> None:
    store = SQLAlchemySessionStore(session_factory)
    assert await store.resolve("not-a-real-token") is None


async def test_resolve_returns_none_for_a_revoked_session(session_factory) -> None:
    store = SQLAlchemySessionStore(session_factory)
    principal = Principal(subject_id="1", authenticated=True)
    raw_token, created = await store.create(principal)

    await store.revoke(created.session_id)

    assert await store.resolve(raw_token) is None


async def test_resolve_returns_none_past_idle_expiry(session_factory) -> None:
    store = SQLAlchemySessionStore(
        session_factory, idle_timeout=timedelta(seconds=-1), absolute_timeout=timedelta(days=1)
    )
    principal = Principal(subject_id="1", authenticated=True)
    raw_token, _ = await store.create(principal)

    assert await store.resolve(raw_token) is None


async def test_resolve_returns_none_past_absolute_expiry(session_factory) -> None:
    store = SQLAlchemySessionStore(
        session_factory, idle_timeout=timedelta(days=1), absolute_timeout=timedelta(seconds=-1)
    )
    principal = Principal(subject_id="1", authenticated=True)
    raw_token, _ = await store.create(principal)

    assert await store.resolve(raw_token) is None


async def test_resolve_extends_idle_expiry_and_updates_last_seen(session_factory) -> None:
    store = SQLAlchemySessionStore(session_factory, idle_timeout=timedelta(hours=1))
    principal = Principal(subject_id="1", authenticated=True)
    raw_token, created = await store.create(principal)

    resolved = await store.resolve(raw_token)

    assert resolved is not None
    assert resolved.last_seen_at >= created.last_seen_at
    assert resolved.idle_expires_at >= created.idle_expires_at


async def test_rotate_invalidates_previous_raw_token(session_factory) -> None:
    store = SQLAlchemySessionStore(session_factory)
    principal = Principal(subject_id="1", authenticated=True)
    old_token, created = await store.create(principal)

    new_token, rotated = await store.rotate(created.session_id)

    assert new_token != old_token
    assert rotated.session_id == created.session_id
    assert await store.resolve(old_token) is None
    assert await store.resolve(new_token) is not None


async def test_revoke_is_idempotent_for_an_unknown_session_id(session_factory) -> None:
    store = SQLAlchemySessionStore(session_factory)
    await store.revoke("does-not-exist")


async def test_create_rejects_principal_without_subject_id(session_factory) -> None:
    store = SQLAlchemySessionStore(session_factory)
    with pytest.raises(ValueError, match="subject_id"):
        await store.create(Principal(authenticated=True))
