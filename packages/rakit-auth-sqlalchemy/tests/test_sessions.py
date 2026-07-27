import asyncio
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


async def test_rotate_rejects_an_idle_expired_session(session_factory) -> None:
    store = SQLAlchemySessionStore(session_factory, idle_timeout=timedelta(seconds=-1))
    _raw, record = await store.create(Principal(subject_id="1", authenticated=True))
    with pytest.raises(ValueError):
        await store.rotate(record.session_id)


async def test_rotate_rejects_an_absolute_expired_session(session_factory) -> None:
    store = SQLAlchemySessionStore(session_factory, absolute_timeout=timedelta(seconds=-1))
    _raw, record = await store.create(Principal(subject_id="1", authenticated=True))
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


async def test_concurrent_rotations_of_one_session_yield_at_most_one_new_session(
    session_factory,
) -> None:
    """Two requests racing on the same cookie must not both succeed into two
    independent live sessions.
    """
    store = SQLAlchemySessionStore(session_factory)
    _raw, record = await store.create(Principal(subject_id="1", authenticated=True))
    results = await asyncio.gather(
        store.rotate(record.session_id),
        store.rotate(record.session_id),
        return_exceptions=True,
    )
    succeeded = [result for result in results if not isinstance(result, BaseException)]
    assert len(succeeded) <= 1, "a revoked session must not rotate again"
