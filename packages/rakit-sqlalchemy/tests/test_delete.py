from collections.abc import AsyncIterator, Awaitable

import pytest
from rakit_core.auth import Principal
from rakit_core.config import SecretValue
from rakit_core.crypto import TokenService
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.fields import FieldDefinition
from rakit_core.forms import FormSchema
from rakit_core.idempotency import IdempotencyReservation, IdempotencyStatus, OperationReceipt
from rakit_core.identity import RecordIdentity
from rakit_core.mutations import MutationAuthorization, MutationOperation
from rakit_core.operations import (
    CancellationContext,
    Deadline,
    OperationContext,
    activate_operation_context,
)
from rakit_sqlalchemy.mutations import SQLAlchemyMutationService
from sqlalchemy import ForeignKey, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "delete_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    revision: Mapped[int] = mapped_column(default=1)


class Parent(Base):
    __tablename__ = "delete_parents"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    revision: Mapped[int] = mapped_column(default=1)
    children: Mapped[list["Child"]] = relationship(cascade="all, delete-orphan")


class Child(Base):
    __tablename__ = "delete_children"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("delete_parents.id"))


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


async def _authorized[T](authorization: MutationAuthorization, awaitable: Awaitable[T]) -> T:
    context = OperationContext(
        deadline=Deadline.after(30),
        cancellation=CancellationContext(),
        principal=Principal(
            subject_id=authorization.principal_id,
            authenticated=True,
            permissions=frozenset(authorization.permissions),
        ),
        admin_id=authorization.admin_id,
        resource_id=authorization.resource_id,
        operation=authorization.operation,
        permissions=authorization.permissions,
    )
    with activate_operation_context(context):
        return await awaitable


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

    async def fail_final(self, reservation: IdempotencyReservation) -> None:
        return None


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
    create_authorization = _authorization("create")
    created = await _authorized(
        create_authorization, service.create({"name": "Ada"}, authorization=create_authorization)
    )

    token = await service.issue_delete_token(created.identity)
    delete_authorization = _authorization("delete")
    await _authorized(
        delete_authorization, service.delete(token, authorization=delete_authorization)
    )

    async with session_factory() as session:
        assert (await session.scalars(select(User))).one_or_none() is None


@pytest.mark.anyio
async def test_changed_record_invalidates_delete_plan(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = _service(session_factory)
    create_authorization = _authorization("create")
    created = await _authorized(
        create_authorization, service.create({"name": "Ada"}, authorization=create_authorization)
    )
    token = await service.issue_delete_token(created.identity)
    update_token = service.issue_update_token(created.record)
    update_authorization = _authorization("update")
    await _authorized(
        update_authorization,
        service.update(
            created.identity,
            {"name": "Grace"},
            concurrency_token=update_token,
            authorization=update_authorization,
        ),
    )

    with pytest.raises(RakitError) as caught:
        delete_authorization = _authorization("delete")
        await _authorized(
            delete_authorization, service.delete(token, authorization=delete_authorization)
        )
    assert caught.value.code == ErrorCode.RESOURCE_CONFLICT


@pytest.mark.anyio
async def test_delete_confirmation_is_bound_to_resource_and_consumed_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    users = _service(session_factory, resource_id="users")
    other = _service(session_factory, resource_id="other_users")
    create_authorization = _authorization("create")
    created = await _authorized(
        create_authorization, users.create({"name": "Ada"}, authorization=create_authorization)
    )
    token = await users.issue_delete_token(created.identity)

    with pytest.raises(RakitError) as wrong_resource:
        other_authorization = _authorization("delete", "other_users")
        await _authorized(
            other_authorization,
            other.delete(token, identity=created.identity, authorization=other_authorization),
        )
    assert wrong_resource.value.status_code == 400

    delete_authorization = _authorization("delete")
    await _authorized(
        delete_authorization,
        users.delete(token, identity=created.identity, authorization=delete_authorization),
    )
    with pytest.raises(RakitError) as replay:
        await _authorized(
            delete_authorization,
            users.delete(token, identity=created.identity, authorization=delete_authorization),
        )
    assert replay.value.status_code == 409


@pytest.mark.anyio
async def test_delete_nonce_does_not_authorize_direct_delete(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = _service(session_factory)
    create_authorization = _authorization("create")
    created = await _authorized(
        create_authorization, service.create({"name": "Ada"}, authorization=create_authorization)
    )
    token = await service.issue_delete_token(created.identity)

    with pytest.raises(RakitError) as caught:
        await service.delete(token)
    assert caught.value.code == ErrorCode.AUTH_FORBIDDEN
    async with session_factory() as session:
        assert await session.get(User, 1) is not None


@pytest.mark.anyio
async def test_delete_preview_derives_relationship_impact_from_mapper_metadata(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = SQLAlchemyMutationService(
        model=Parent,
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
        resource_id="parents",
        delete_nonce_store=_NonceStore(),
    )
    create_authorization = _authorization("create", "parents")
    created = await _authorized(
        create_authorization, service.create({"name": "Ada"}, authorization=create_authorization)
    )

    plan = await service.preview_delete(created.identity)

    assert plan.relationship_impact == (
        "children:delete,delete-orphan,expunge,merge,refresh-expire,save-update",
    )


@pytest.mark.anyio
async def test_scoped_delete_preview_and_execution_reject_inaccessible_records(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = SQLAlchemyMutationService(
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
        resource_id="users",
        delete_nonce_store=_NonceStore(),
        scoped_statement=lambda: select(User).where(User.name == "visible"),
    )
    async with session_factory() as session:
        session.add_all((User(name="visible"), User(name="hidden")))
        await session.commit()

    visible_plan = await service.preview_delete(RecordIdentity(values={"id": 1}))
    assert visible_plan.identity.values == {"id": 1}
    with pytest.raises(RakitError) as preview:
        await service.preview_delete(RecordIdentity(values={"id": 2}))
    assert preview.value.code == ErrorCode.RESOURCE_NOT_FOUND

    token = await service.issue_delete_token(RecordIdentity(values={"id": 1}))
    async with session_factory() as session:
        visible = await session.get(User, 1)
        assert visible is not None
        visible.name = "hidden"
        await session.commit()
    authorization = _authorization("delete")
    with pytest.raises(RakitError) as execution:
        await _authorized(
            authorization,
            service.delete(
                token, identity=RecordIdentity(values={"id": 1}), authorization=authorization
            ),
        )
    assert execution.value.code == ErrorCode.RESOURCE_NOT_FOUND
    async with session_factory() as session:
        assert await session.get(User, 1) is not None
