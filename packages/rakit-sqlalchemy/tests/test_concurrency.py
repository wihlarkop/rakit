import asyncio
from collections.abc import AsyncIterator, Awaitable
from pathlib import Path

import pytest
from rakit_core.auth import Principal
from rakit_core.config import SecretValue
from rakit_core.crypto import TokenService
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.fields import FieldDefinition
from rakit_core.forms import FormSchema
from rakit_core.identity import RecordIdentity
from rakit_core.mutations import MutationAuthorization, MutationOperation
from rakit_core.operations import (
    CancellationContext,
    Deadline,
    OperationContext,
    activate_operation_context,
)
from rakit_sqlalchemy.mutations import SQLAlchemyMutationService
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "concurrency_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    revision: Mapped[int] = mapped_column(default=1)


def _authorization(operation: MutationOperation) -> MutationAuthorization:
    return MutationAuthorization(
        admin_id="admin",
        resource_id="concurrency_users",
        operation=operation,
        principal_id="tester",
        permissions=(f"admin.resources.concurrency_users.{operation}",),
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


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.anyio
async def test_stale_update_returns_a_conflict_before_writing(
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
    )
    create_authorization = _authorization("create")
    created = await _authorized(
        create_authorization, service.create({"name": "Ada"}, authorization=create_authorization)
    )
    token = service.issue_update_token(created.record)

    update_authorization = _authorization("update")
    await _authorized(
        update_authorization,
        service.update(
            created.identity,
            {"name": "Grace"},
            concurrency_token=token,
            authorization=update_authorization,
        ),
    )

    with pytest.raises(RakitError) as caught:
        await _authorized(
            update_authorization,
            service.update(
                created.identity,
                {"name": "Ada"},
                concurrency_token=token,
                authorization=update_authorization,
            ),
        )
    assert caught.value.code == ErrorCode.RESOURCE_CONFLICT
    assert caught.value.status_code == 409


@pytest.mark.anyio
async def test_concurrent_updates_with_the_same_token_have_exactly_one_winner(
    tmp_path: Path,
) -> None:
    """The version predicate belongs in SQL, after both writers have read it."""
    database = tmp_path / "concurrency.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    barrier = asyncio.Barrier(2)

    class BarrierService(SQLAlchemyMutationService):
        async def _load(self, session: AsyncSession, identity: RecordIdentity) -> object | None:
            record = await super()._load(session, identity)
            if record is not None:
                await barrier.wait()
            return record

    service = BarrierService(
        model=User,
        session_factory=factory,
        form_schema=FormSchema(
            fields=(FieldDefinition(field_id="name", python_type=str, required=True),)
        ),
        writable_fields=("name",),
        identity_fields=("id",),
        token_service=TokenService.single_key(
            key_id="test", value=SecretValue("x" * 32), admin_id="admin"
        ),
        version_field="revision",
    )
    create_authorization = _authorization("create")
    created = await _authorized(
        create_authorization, service.create({"name": "Ada"}, authorization=create_authorization)
    )
    token = service.issue_update_token(created.record)

    outcomes = await asyncio.gather(
        _authorized(
            _authorization("update"),
            service.update(
                created.identity,
                {"name": "Grace"},
                concurrency_token=token,
                authorization=_authorization("update"),
            ),
        ),
        _authorized(
            _authorization("update"),
            service.update(
                created.identity,
                {"name": "Lin"},
                concurrency_token=token,
                authorization=_authorization("update"),
            ),
        ),
        return_exceptions=True,
    )

    assert sum(isinstance(outcome, RakitError) for outcome in outcomes) == 1
    assert sum(not isinstance(outcome, Exception) for outcome in outcomes) == 1
    assert any(
        isinstance(outcome, RakitError) and outcome.code == ErrorCode.RESOURCE_CONFLICT
        for outcome in outcomes
    )
    await engine.dispose()


@pytest.mark.anyio
async def test_atomic_update_rechecks_scope_after_target_load(
    tmp_path: Path,
) -> None:
    database = tmp_path / "scope-race.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    class ScopeChangingService(SQLAlchemyMutationService):
        switch_scope = False

        async def _load(self, session: AsyncSession, identity: RecordIdentity) -> object | None:
            record = await super()._load(session, identity)
            if record is not None and self.switch_scope:
                self.switch_scope = False
                async with factory() as changer:
                    target = await changer.get(User, identity.values["id"])
                    assert target is not None
                    target.name = "hidden"
                    await changer.commit()
            return record

    service = ScopeChangingService(
        model=User,
        session_factory=factory,
        form_schema=FormSchema(
            fields=(FieldDefinition(field_id="name", python_type=str, required=True),)
        ),
        writable_fields=("name",),
        identity_fields=("id",),
        token_service=TokenService.single_key(
            key_id="test", value=SecretValue("x" * 32), admin_id="admin"
        ),
        version_field="revision",
        scoped_statement=lambda: select(User).where(User.name == "visible"),
    )
    async with factory() as session:
        session.add(User(name="visible"))
        await session.commit()
    identity = RecordIdentity(values={"id": 1})
    async with factory() as session:
        record = await session.get(User, 1)
        assert record is not None
        token = service.issue_update_token(record)

    service.switch_scope = True
    authorization = _authorization("update")
    with pytest.raises(RakitError) as caught:
        await _authorized(
            authorization,
            service.update(
                identity,
                {"name": "Grace"},
                concurrency_token=token,
                authorization=authorization,
            ),
        )
    assert caught.value.code == ErrorCode.RESOURCE_CONFLICT
    async with factory() as session:
        record = await session.get(User, 1)
        assert record is not None
        assert record.name == "hidden"
    await engine.dispose()
