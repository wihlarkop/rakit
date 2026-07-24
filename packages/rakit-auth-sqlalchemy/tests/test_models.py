from datetime import UTC, datetime, timedelta

import pytest
from rakit_auth_sqlalchemy.models import Base, Permission, Role, Session, User
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload


def test_user_defaults_are_secure() -> None:
    user = User(email="ada@example.com", password_hash="hash")
    assert user.is_active is True
    assert user.is_superuser is False


def test_user_email_is_normalized_to_lowercase_and_stripped() -> None:
    user = User(email="  Ada@Example.COM  ", password_hash="hash")
    assert user.email == "ada@example.com"


def test_role_collects_allow_only_permissions() -> None:
    role = Role(name="editor")
    role.permissions.append(Permission(key="operations.resources.orders.read"))
    assert {item.key for item in role.permissions} == {"operations.resources.orders.read"}


def test_permission_defaults_are_not_orphaned() -> None:
    permission = Permission(key="operations.access", label="Access Admin", group="Admin")
    assert permission.orphaned is False


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def test_user_email_is_unique(session_factory) -> None:
    async with session_factory() as session:
        session.add(User(email="ada@example.com", password_hash="hash-a"))
        await session.commit()

    async with session_factory() as session:
        session.add(User(email="ada@example.com", password_hash="hash-b"))
        with pytest.raises(Exception):  # noqa: B017 -- backend-specific IntegrityError subclass
            await session.commit()


async def test_permission_key_is_unique(session_factory) -> None:
    async with session_factory() as session:
        session.add(Permission(key="operations.access", label="Access", group="Admin"))
        await session.commit()

    async with session_factory() as session:
        session.add(Permission(key="operations.access", label="Access Again", group="Admin"))
        with pytest.raises(Exception):  # noqa: B017
            await session.commit()


async def test_session_stores_only_token_hash_not_raw_token(session_factory) -> None:
    now = datetime.now(UTC)
    async with session_factory() as session:
        user = User(email="ada@example.com", password_hash="hash")
        session.add(user)
        await session.flush()
        session.add(
            Session(
                token_hash="a" * 64,
                user_id=user.id,
                created_at=now,
                last_seen_at=now,
                idle_expires_at=now + timedelta(hours=1),
                absolute_expires_at=now + timedelta(days=14),
            )
        )
        await session.commit()

    async with session_factory() as session:
        stored = await session.get(Session, 1)
        assert stored is not None
        assert stored.token_hash == "a" * 64
        assert stored.revoked_at is None
        assert not hasattr(stored, "token")
        assert not hasattr(stored, "raw_token")


async def test_role_user_and_permission_associations_persist(session_factory) -> None:
    async with session_factory() as session:
        user = User(email="ada@example.com", password_hash="hash")
        role = Role(name="editor")
        role.permissions.append(Permission(key="operations.resources.orders.read"))
        user.roles.append(role)
        session.add(user)
        await session.commit()

    async with session_factory() as session:
        stored = await session.get(
            User,
            1,
            options=[selectinload(User.roles).selectinload(Role.permissions)],
        )
        assert stored is not None
        assert [role.name for role in stored.roles] == ["editor"]
        assert [permission.key for permission in stored.roles[0].permissions] == [
            "operations.resources.orders.read"
        ]
