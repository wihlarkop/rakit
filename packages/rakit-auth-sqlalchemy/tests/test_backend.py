import asyncio
import time
from collections.abc import AsyncIterator

import pytest
from rakit_auth_sqlalchemy.backend import SQLAlchemyAuthBackend
from rakit_auth_sqlalchemy.models import Base, Permission, Role, User
from rakit_auth_sqlalchemy.passwords import Argon2PasswordHasher
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed_user(
    session_factory,
    *,
    email: str = "ada@example.com",
    password: str = "correct horse battery staple",
    is_active: bool = True,
    is_superuser: bool = False,
) -> int:
    hasher = Argon2PasswordHasher()
    password_hash = await hasher.hash(password)
    async with session_factory() as session:
        user = User(
            email=email,
            password_hash=password_hash,
            is_active=is_active,
            is_superuser=is_superuser,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id


async def test_authenticate_succeeds_with_correct_credentials(session_factory) -> None:
    await _seed_user(session_factory, email="ada@example.com", password="secret-password")
    backend = SQLAlchemyAuthBackend(session_factory)

    principal = await backend.authenticate("ada@example.com", "secret-password")

    assert principal is not None
    assert principal.authenticated is True
    assert principal.subject_id is not None


async def test_authenticate_normalizes_the_identifier(session_factory) -> None:
    await _seed_user(session_factory, email="ada@example.com", password="secret-password")
    backend = SQLAlchemyAuthBackend(session_factory)

    principal = await backend.authenticate("  Ada@Example.COM  ", "secret-password")

    assert principal is not None
    assert principal.authenticated is True


async def test_authenticate_rejects_unknown_identifier(session_factory) -> None:
    backend = SQLAlchemyAuthBackend(session_factory)

    principal = await backend.authenticate("nobody@example.com", "whatever")

    assert principal is None


async def test_authenticate_rejects_wrong_password(session_factory) -> None:
    await _seed_user(session_factory, email="ada@example.com", password="secret-password")
    backend = SQLAlchemyAuthBackend(session_factory)

    principal = await backend.authenticate("ada@example.com", "wrong-password")

    assert principal is None


async def test_authenticate_rejects_inactive_user(session_factory) -> None:
    await _seed_user(
        session_factory, email="ada@example.com", password="secret-password", is_active=False
    )
    backend = SQLAlchemyAuthBackend(session_factory)

    principal = await backend.authenticate("ada@example.com", "secret-password")

    assert principal is None


async def test_authenticate_preserves_superuser_flag(session_factory) -> None:
    await _seed_user(
        session_factory, email="ada@example.com", password="secret-password", is_superuser=True
    )
    backend = SQLAlchemyAuthBackend(session_factory)

    principal = await backend.authenticate("ada@example.com", "secret-password")

    assert principal is not None
    assert principal.is_superuser is True


async def test_authenticate_loads_role_granted_non_orphaned_permissions(session_factory) -> None:
    hasher = Argon2PasswordHasher()
    password_hash = await hasher.hash("secret-password")
    async with session_factory() as session:
        role = Role(name="editor")
        role.permissions.append(Permission(key="operations.access"))
        role.permissions.append(Permission(key="operations.orphaned", orphaned=True))
        user = User(email="ada@example.com", password_hash=password_hash)
        user.roles.append(role)
        session.add(user)
        await session.commit()

    backend = SQLAlchemyAuthBackend(session_factory)
    principal = await backend.authenticate("ada@example.com", "secret-password")

    assert principal is not None
    assert principal.permissions == frozenset({"operations.access"})


async def test_authenticate_updates_last_login_at(session_factory) -> None:
    user_id = await _seed_user(session_factory, email="ada@example.com", password="secret-password")
    backend = SQLAlchemyAuthBackend(session_factory)

    await backend.authenticate("ada@example.com", "secret-password")

    async with session_factory() as session:
        user = await session.get(User, user_id)
        assert user is not None
        assert user.last_login_at is not None


async def test_authenticate_never_exposes_password_hash() -> None:
    """Principal has no field capable of carrying a password hash at all --
    this is a structural guarantee, not a runtime check."""
    from rakit_core.auth import Principal

    assert "password_hash" not in Principal.model_fields
    assert "password" not in Principal.model_fields


async def test_unknown_and_inactive_identifiers_take_similar_time_to_reject(
    session_factory,
) -> None:
    """Both an unknown identifier and an inactive user's correct password
    must pay Argon2's hashing cost before rejecting -- proving the dummy-hash
    warmup path is actually exercised for a missing user, not skipped."""
    await _seed_user(
        session_factory, email="inactive@example.com", password="secret-password", is_active=False
    )
    backend = SQLAlchemyAuthBackend(session_factory)
    # Warm up the dummy-hash cache so the *first* call's extra hashing cost
    # doesn't skew this specific comparison.
    await backend.authenticate("unknown-warmup@example.com", "whatever")

    start_unknown = time.monotonic()
    await backend.authenticate("still-unknown@example.com", "whatever")
    unknown_elapsed = time.monotonic() - start_unknown

    start_inactive = time.monotonic()
    await backend.authenticate("inactive@example.com", "secret-password")
    inactive_elapsed = time.monotonic() - start_inactive

    # Not an exact-timing assertion (too flaky) -- just proves neither path
    # short-circuits to near-zero while the other actually hashes.
    assert unknown_elapsed > 0.001
    assert inactive_elapsed > 0.001


class _CountingDummyHasher:
    def __init__(self, *, failures: int = 0) -> None:
        self.hash_calls = 0
        self.verify_calls = 0
        self._failures = failures

    async def hash(self, password: str) -> str:
        self.hash_calls += 1
        await asyncio.sleep(0.01)
        if self.hash_calls <= self._failures:
            raise RuntimeError("synthetic hash failure")
        return "completed-dummy-hash"

    async def verify(self, password: str, encoded: str) -> bool:
        self.verify_calls += 1
        return False


async def test_dummy_hash_initialization_is_single_flight_for_fifty_callers(
    session_factory,
) -> None:
    hasher = _CountingDummyHasher()
    backend = SQLAlchemyAuthBackend(
        session_factory,
        password_hasher=hasher,  # ty: ignore[invalid-argument-type]
    )

    hashes = await asyncio.gather(*(backend._get_dummy_hash() for _ in range(50)))

    assert hasher.hash_calls == 1
    assert hashes == ["completed-dummy-hash"] * 50


async def test_failed_dummy_hash_initialization_can_be_retried(session_factory) -> None:
    hasher = _CountingDummyHasher(failures=1)
    backend = SQLAlchemyAuthBackend(
        session_factory,
        password_hasher=hasher,  # ty: ignore[invalid-argument-type]
    )

    with pytest.raises(RuntimeError, match="synthetic hash failure"):
        await backend._get_dummy_hash()
    assert await backend._get_dummy_hash() == "completed-dummy-hash"
    assert hasher.hash_calls == 2


async def test_dummy_hash_failure_does_not_reveal_whether_identifier_exists(
    session_factory,
) -> None:
    await _seed_user(session_factory, email="known@example.com")
    hasher = _CountingDummyHasher(failures=10)
    backend = SQLAlchemyAuthBackend(
        session_factory,
        password_hasher=hasher,  # ty: ignore[invalid-argument-type]
    )

    with pytest.raises(RuntimeError, match="synthetic hash failure"):
        await backend.authenticate("missing@example.com", "wrong")
    with pytest.raises(RuntimeError, match="synthetic hash failure"):
        await backend.authenticate("known@example.com", "wrong")


async def test_concurrent_cold_unknown_users_share_one_dummy_hash(session_factory) -> None:
    hasher = _CountingDummyHasher()
    backend = SQLAlchemyAuthBackend(
        session_factory,
        password_hasher=hasher,  # ty: ignore[invalid-argument-type]
    )

    results = await asyncio.gather(
        *(backend.authenticate(f"missing-{index}@example.com", "wrong") for index in range(50))
    )

    assert results == [None] * 50
    assert hasher.hash_calls == 1
    assert hasher.verify_calls == 50


async def test_resolve_principal_returns_current_state_for_active_user(session_factory) -> None:
    user_id = await _seed_user(session_factory, email="ada@example.com")
    backend = SQLAlchemyAuthBackend(session_factory)

    principal = await backend.resolve_principal(str(user_id))

    assert principal is not None
    assert principal.authenticated is True
    assert principal.subject_id == str(user_id)


async def test_resolve_principal_returns_none_for_inactive_user(session_factory) -> None:
    user_id = await _seed_user(session_factory, email="ada@example.com", is_active=False)
    backend = SQLAlchemyAuthBackend(session_factory)

    assert await backend.resolve_principal(str(user_id)) is None


async def test_resolve_principal_returns_none_for_unknown_subject_id(session_factory) -> None:
    backend = SQLAlchemyAuthBackend(session_factory)
    assert await backend.resolve_principal("999999") is None


async def test_resolve_principal_returns_none_for_malformed_subject_id(session_factory) -> None:
    backend = SQLAlchemyAuthBackend(session_factory)
    assert await backend.resolve_principal("not-a-number") is None


async def test_resolve_principal_reflects_permission_changes_since_login(session_factory) -> None:
    """resolve_principal must re-query, not cache -- a permission granted
    after the session was created must show up on the next resolution."""
    hasher = Argon2PasswordHasher()
    password_hash = await hasher.hash("secret-password")
    async with session_factory() as session:
        user = User(email="ada@example.com", password_hash=password_hash)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        user_id = user.id

    backend = SQLAlchemyAuthBackend(session_factory)
    before = await backend.resolve_principal(str(user_id))
    assert before is not None
    assert before.permissions == frozenset()

    async with session_factory() as session:
        role = Role(name="editor")
        role.permissions.append(Permission(key="operations.access"))
        user = await session.get(User, user_id, options=[selectinload(User.roles)])
        assert user is not None
        user.roles.append(role)
        await session.commit()

    after = await backend.resolve_principal(str(user_id))
    assert after is not None
    assert after.permissions == frozenset({"operations.access"})
