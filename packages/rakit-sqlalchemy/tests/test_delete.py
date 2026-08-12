from collections.abc import AsyncIterator

import pytest
from rakit_core.config import SecretValue
from rakit_core.crypto import TokenService
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.fields import FieldDefinition
from rakit_core.forms import FormSchema
from rakit_core.idempotency import IdempotencyReservation, IdempotencyStatus, OperationReceipt
from rakit_core.mutations import MutationAuthorization, MutationOperation
from rakit_sqlalchemy.mutations import SQLAlchemyMutationService
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "delete_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    revision: Mapped[int] = mapped_column(default=1)


def _authorization(
    operation: MutationOperation, resource_id: str = "users"
) -> MutationAuthorization:
    return MutationAuthorization(
        admin_id="admin",
        resource_id=resource_id,
        operation=operation,
        principal_id="tester",
        permissions=(f"admin.resources.{resource_id}.{operation}",),
    )


class _NonceStore:
    def __init__(self) -> None:
        self.claimed: set[str] = set()

    async def begin(self, token_hash: str, *, fingerprint: str) -> IdempotencyReservation:
        if token_hash in self.claimed:
            return IdempotencyReservation(1, IdempotencyStatus.COMPLETED, claimed=False)
        self.claimed.add(token_hash)
        return IdempotencyReservation(1, IdempotencyStatus.IN_PROGRESS)

    async def complete(
        self, reservation: IdempotencyReservation, receipt: OperationReceipt
    ) -> None:
        return None

    async def release(self, reservation: IdempotencyReservation) -> None:
        self.claimed.clear()


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def _service(
    session_factory: async_sessionmaker[AsyncSession], *, resource_id: str = "users"
) -> SQLAlchemyMutationService:
    return SQLAlchemyMutationService(
        model=User,
        session_factory=session_factory,
        form_schema=FormSchema(
            fields=(FieldDefinition(field_id="name", python_type=str, required=True),)
        ),
        writable_fields=("name",),
        identity_fields=("id",),
        token_service=TokenService.single_key(
            key_id="test", value=SecretValue("x" * 32), admin_id="admin"
        ),
        version_field="revision",
        resource_id=resource_id,
        delete_nonce_store=_NonceStore(),
    )


@pytest.mark.anyio
async def test_hard_delete_uses_a_signed_confirmation_plan(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = _service(session_factory)
    created = await service.create({"name": "Ada"}, authorization=_authorization("create"))

    token = await service.issue_delete_token(created.identity)
    await service.delete(token, authorization=_authorization("delete"))

    async with session_factory() as session:
        assert (await session.scalars(select(User))).one_or_none() is None


@pytest.mark.anyio
async def test_changed_record_invalidates_delete_plan(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = _service(session_factory)
    created = await service.create({"name": "Ada"}, authorization=_authorization("create"))
    token = await service.issue_delete_token(created.identity)
    update_token = service.issue_update_token(created.record)
    await service.update(
        created.identity,
        {"name": "Grace"},
        concurrency_token=update_token,
        authorization=_authorization("update"),
    )

    with pytest.raises(RakitError) as caught:
        await service.delete(token, authorization=_authorization("delete"))
    assert caught.value.code == ErrorCode.RESOURCE_CONFLICT


@pytest.mark.anyio
async def test_delete_confirmation_is_bound_to_resource_and_consumed_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    users = _service(session_factory, resource_id="users")
    other = _service(session_factory, resource_id="other_users")
    created = await users.create({"name": "Ada"}, authorization=_authorization("create"))
    token = await users.issue_delete_token(created.identity)

    with pytest.raises(RakitError) as wrong_resource:
        await other.delete(
            token, identity=created.identity, authorization=_authorization("delete", "other_users")
        )
    assert wrong_resource.value.status_code == 400

    await users.delete(token, identity=created.identity, authorization=_authorization("delete"))
    with pytest.raises(RakitError) as replay:
        await users.delete(token, identity=created.identity, authorization=_authorization("delete"))
    assert replay.value.status_code == 409


@pytest.mark.anyio
async def test_delete_nonce_does_not_authorize_direct_delete(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = _service(session_factory)
    created = await service.create({"name": "Ada"}, authorization=_authorization("create"))
    token = await service.issue_delete_token(created.identity)

    with pytest.raises(RakitError) as caught:
        await service.delete(token)
    assert caught.value.code == ErrorCode.AUTH_FORBIDDEN
    async with session_factory() as session:
        assert await session.get(User, 1) is not None
