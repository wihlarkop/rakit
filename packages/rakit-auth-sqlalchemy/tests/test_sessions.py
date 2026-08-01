import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from rakit_auth_sqlalchemy.models import Base, User
from rakit_auth_sqlalchemy.sessions import SQLAlchemySessionStore
from rakit_core.auth import Principal
from rakit_core.errors import RakitError
from rakit_web.security.validation import validate_session_store_for_production
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


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

    assert store.production_safe is False

    assert raw_token
    assert record.subject_id == "1"


def test_unbound_session_factory_is_not_production_safe() -> None:
    store = SQLAlchemySessionStore(async_sessionmaker())
    assert store.production_safe is False
    with pytest.raises(RakitError) as exc_info:
        validate_session_store_for_production(store, debug=False, auth_enabled=True)
    assert exc_info.value.details["reason"] == "development_only_session_store"


async def test_sqlite_file_session_factory_is_not_claimed_as_production_shared(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'sessions.db'}")
    store = SQLAlchemySessionStore(async_sessionmaker(engine))
    assert store.production_safe is False
    await engine.dispose()


async def test_debug_mode_accepts_sqlite_development_store() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    store = SQLAlchemySessionStore(async_sessionmaker(engine))
    validate_session_store_for_production(store, debug=True, auth_enabled=True)
    await engine.dispose()


def test_bound_shared_database_store_is_production_safe() -> None:
    class _SharedDialect:
        name = "postgresql"

    shared_engine = Mock(spec=AsyncEngine)
    shared_engine.dialect = _SharedDialect()
    factory = SimpleNamespace(kw={"bind": shared_engine})
    store = SQLAlchemySessionStore(factory)  # ty: ignore[invalid-argument-type]
    assert store.production_safe is True
    validate_session_store_for_production(store, debug=False, auth_enabled=True)


def test_dialect_shaped_non_engine_does_not_claim_production_safety() -> None:
    fake_bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    factory = SimpleNamespace(kw={"bind": fake_bind})
    store = SQLAlchemySessionStore(factory)  # ty: ignore[invalid-argument-type]
    assert store.production_safe is False


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


@pytest.mark.parametrize(
    ("idle_timeout", "absolute_timeout", "reason"),
    [
        (timedelta(0), timedelta(days=1), "invalid_idle_timeout"),
        (timedelta(hours=1), timedelta(0), "invalid_absolute_timeout"),
        (timedelta(seconds=-1), timedelta(days=1), "invalid_idle_timeout"),
        (timedelta(hours=1), timedelta(seconds=-1), "invalid_absolute_timeout"),
        (timedelta(days=2), timedelta(days=1), "idle_timeout_exceeds_absolute"),
        (timedelta(days=1), timedelta(days=366), "absolute_timeout_exceeds_token_limit"),
    ],
)
async def test_invalid_session_lifetimes_fail_during_construction(
    session_factory,
    idle_timeout: timedelta,
    absolute_timeout: timedelta,
    reason: str,
) -> None:
    with pytest.raises(RakitError) as exc_info:
        SQLAlchemySessionStore(
            session_factory,
            idle_timeout=idle_timeout,
            absolute_timeout=absolute_timeout,
        )
    assert exc_info.value.details["reason"] == reason


@pytest.mark.parametrize("duration", [timedelta(days=1), timedelta(days=14), timedelta(days=30)])
async def test_supported_session_lifetimes_create_live_sessions(
    session_factory, duration: timedelta
) -> None:
    store = SQLAlchemySessionStore(
        session_factory,
        idle_timeout=min(duration, timedelta(days=1)),
        absolute_timeout=duration,
    )
    raw_token, _ = await store.create(Principal(subject_id="1", authenticated=True))
    assert await store.resolve(raw_token) is not None


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
    assert await store.resolve(old_token) is None
    assert await store.resolve(new_token) is not None


async def test_rotate_issues_a_new_session_id(session_factory) -> None:
    """A rotated session must not merely swap the raw token while keeping
    the same session_id -- any CSRF token already issued (bound to the
    session_id, not the raw token) would otherwise remain valid forever
    even after rotation. A genuinely new session_id is required so a stale
    CSRF token from before rotation stops matching the current session."""
    store = SQLAlchemySessionStore(session_factory)
    principal = Principal(subject_id="1", authenticated=True)
    _old_token, created = await store.create(principal)

    _new_token, rotated = await store.rotate(created.session_id)

    assert rotated.session_id != created.session_id


async def test_rotate_preserves_the_original_absolute_expiry_boundary(session_factory) -> None:
    """Rotation must not reset the absolute-expiry clock -- otherwise a
    session could be kept alive indefinitely by rotating it just before
    each absolute-expiry deadline, defeating the point of an absolute
    boundary entirely."""
    store = SQLAlchemySessionStore(session_factory)
    principal = Principal(subject_id="1", authenticated=True)
    _old_token, created = await store.create(principal)

    _new_token, rotated = await store.rotate(created.session_id)

    assert rotated.absolute_expires_at == created.absolute_expires_at


async def test_rotate_revokes_the_previous_session_id(session_factory) -> None:
    """The old session_id must stop resolving entirely after rotation, not
    merely have its raw token swapped out -- resolving by the (impossible
    to obtain without the raw token, but conceptually) old identity must
    not succeed."""
    store = SQLAlchemySessionStore(session_factory)
    principal = Principal(subject_id="1", authenticated=True)
    old_token, created = await store.create(principal)

    new_token, rotated = await store.rotate(created.session_id)

    assert rotated.session_id != created.session_id
    resolved_new = await store.resolve(new_token)
    assert resolved_new is not None
    assert resolved_new.session_id == rotated.session_id
    # Revoking the *old* session_id again must be a safe no-op (it no
    # longer has a live row to revoke, but that's not an error).
    await store.revoke(created.session_id)
    assert await store.resolve(new_token) is not None


async def test_revoke_is_idempotent_for_an_unknown_session_id(session_factory) -> None:
    store = SQLAlchemySessionStore(session_factory)
    await store.revoke("does-not-exist")


async def test_create_rejects_principal_without_subject_id(session_factory) -> None:
    store = SQLAlchemySessionStore(session_factory)
    with pytest.raises(ValueError, match="subject_id"):
        await store.create(Principal(authenticated=True))


# --- Round 3: rotate() must reject sessions that are no longer live -----


async def test_rotate_rejects_a_revoked_session(session_factory) -> None:
    """Rotation of a revoked session used to mint a brand-new live session
    from a dead one -- turning logout, or a revocation triggered by a
    disabled account, back into a valid credential.
    """
    store = SQLAlchemySessionStore(session_factory)
    _raw, record = await store.create(Principal(subject_id="1", authenticated=True))
    await store.revoke(record.session_id)
    with pytest.raises(ValueError):
        await store.rotate(record.session_id)


async def test_rotate_rejects_an_unknown_session(session_factory) -> None:
    store = SQLAlchemySessionStore(session_factory)
    with pytest.raises(ValueError):
        await store.rotate("999999")
    with pytest.raises(ValueError):
        await store.rotate("not-a-number")


async def test_rotate_still_works_for_a_live_session(session_factory) -> None:
    """The rejections must not have broken the case rotation exists for."""
    store = SQLAlchemySessionStore(session_factory)
    raw_token, record = await store.create(Principal(subject_id="1", authenticated=True))
    new_raw_token, rotated = await store.rotate(record.session_id)

    assert rotated.session_id != record.session_id
    assert new_raw_token != raw_token
    # The absolute boundary is preserved, so rotation is not a way to keep a
    # session alive past its original deadline.
    assert rotated.absolute_expires_at == record.absolute_expires_at
    assert await store.resolve(new_raw_token) is not None
    assert await store.resolve(raw_token) is None


async def test_a_rotated_session_cannot_be_rotated_again_from_its_old_id(
    session_factory,
) -> None:
    """Rotation revokes the previous row, so replaying the old session_id --
    the shape of a stolen-cookie race between two concurrent callers -- must
    not mint a second live session from it.
    """
    store = SQLAlchemySessionStore(session_factory)
    _raw, record = await store.create(Principal(subject_id="1", authenticated=True))
    await store.rotate(record.session_id)
    with pytest.raises(ValueError):
        await store.rotate(record.session_id)


async def test_concurrent_rotations_of_one_session_yield_exactly_one_new_session(
    tmp_path,
) -> None:
    """Two requests racing on the same cookie must not both succeed into two
    independent live sessions -- and exactly one must still get through, or
    rotation would be broken for legitimate concurrent traffic.

    File-backed rather than in-memory: `sqlite+aiosqlite:///:memory:` shares
    one underlying connection across sessions, so the two coroutines are not
    genuinely independent transactions and the winner fails on an unrelated
    identity-map error. A file gives each session its own connection, which
    is what makes this a real test of the conditional-UPDATE claim.
    """
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'sessions.db'}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            session.add(User(id=1, email="ada@example.com", password_hash="hash"))
            await session.commit()

        store = SQLAlchemySessionStore(factory)
        _raw, record = await store.create(Principal(subject_id="1", authenticated=True))
        results = await asyncio.gather(
            store.rotate(record.session_id),
            store.rotate(record.session_id),
            return_exceptions=True,
        )
        succeeded = [result for result in results if not isinstance(result, BaseException)]
        failed = [result for result in results if isinstance(result, ValueError)]
        assert len(succeeded) == 1, f"expected exactly one winner, got {results}"
        assert len(failed) == 1, f"the loser must be rejected as revoked, got {results}"
        assert "revoked" in str(failed[0])
    finally:
        await engine.dispose()
