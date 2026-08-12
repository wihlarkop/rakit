import asyncio
from collections.abc import AsyncIterator, Awaitable
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

import pytest
from rakit_core.auth import Principal
from rakit_core.concurrency import AttributeVersionProvider, ConcurrencyMode
from rakit_core.config import SecretValue
from rakit_core.crypto import TokenService
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.events import EventBus, EventPublisher
from rakit_core.fields import FieldDefinition
from rakit_core.forms import FormSchema
from rakit_core.identity import RecordIdentity
from rakit_core.mutations import (
    MutationAuthorization,
    MutationOperation,
    ResourceForceOverwritten,
)
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
    password_hash: Mapped[str] = mapped_column(default="private")


class ProviderUser(Base):
    __tablename__ = "concurrency_provider_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    revision: Mapped[int] = mapped_column(default=1)
    explicit_revision: Mapped[int] = mapped_column(default=10)
    __mapper_args__: ClassVar[dict[str, object]] = {"version_id_col": revision}


class SnapshotUser(Base):
    __tablename__ = "concurrency_snapshot_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    password_hash: Mapped[str] = mapped_column(default="private")


class TimestampUser(Base):
    __tablename__ = "concurrency_timestamp_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    updated_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


def _authorization(
    operation: MutationOperation, resource_id: str = "concurrency_users"
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
async def test_explicit_provider_has_priority_over_mapper_version_metadata(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """An explicit provider, not incidental mapper metadata, owns the token."""
    service = SQLAlchemyMutationService(
        model=ProviderUser,
        session_factory=session_factory,
        form_schema=FormSchema(
            fields=(FieldDefinition(field_id="name", python_type=str, required=True),)
        ),
        writable_fields=("name",),
        identity_fields=("id",),
        token_service=TokenService.single_key(
            key_id="test", value=SecretValue("x" * 32), admin_id="admin"
        ),
        concurrency_mode=ConcurrencyMode.AUTO,
        concurrency_provider=AttributeVersionProvider("explicit_revision"),
    )
    authorization = _authorization("create", "concurrency_provider_users")
    created = await _authorized(
        authorization, service.create({"name": "Ada"}, authorization=authorization)
    )

    token = service.issue_update_token(created.record)
    claims = service._token_service.verify(token, expected_purpose="concurrency")

    assert claims["version"] == 10


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


@pytest.mark.anyio
async def test_atomic_conflict_exposes_only_safe_structured_values(
    tmp_path: Path,
) -> None:
    database = tmp_path / "conflict.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    class ChangingService(SQLAlchemyMutationService):
        change_after_load = False

        async def _load(self, session: AsyncSession, identity: RecordIdentity) -> object | None:
            record = await super()._load(session, identity)
            if record is not None and self.change_after_load:
                self.change_after_load = False
                async with factory() as changer:
                    current = await changer.get(User, identity.values["id"])
                    assert current is not None
                    current.name = "Grace"
                    current.revision += 1
                    current.password_hash = "changed-private"
                    await changer.commit()
            return record

    service = ChangingService(
        model=User,
        session_factory=factory,
        form_schema=FormSchema(
            fields=(
                FieldDefinition(field_id="name", python_type=str, required=True),
                FieldDefinition(field_id="password_hash", python_type=str),
            )
        ),
        writable_fields=("name",),
        identity_fields=("id",),
        token_service=TokenService.single_key(
            key_id="test", value=SecretValue("x" * 32), admin_id="admin"
        ),
        version_field="revision",
    )
    async with factory() as session:
        session.add(User(name="Ada"))
        await session.commit()
        record = await session.get(User, 1)
        assert record is not None
        token = service.issue_update_token(record)

    service.change_after_load = True
    authorization = _authorization("update")
    with pytest.raises(RakitError) as caught:
        await _authorized(
            authorization,
            service.update(
                RecordIdentity(values={"id": 1}),
                {"name": "Lin"},
                concurrency_token=token,
                authorization=authorization,
            ),
        )

    conflict = caught.value.details["conflict"]
    assert conflict["base"] == {"name": "Ada"}
    assert conflict["current"] == {"name": "Grace"}
    assert conflict["proposed"] == {"name": "Lin"}
    assert conflict["field_conflicts"] == ["name"]
    assert "password_hash" not in repr(conflict)
    await engine.dispose()


@pytest.mark.anyio
async def test_force_overwrite_requires_dedicated_permission_and_confirmation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    events: list[ResourceForceOverwritten] = []
    event_bus = EventBus()
    event_bus.subscribe(ResourceForceOverwritten, events.append)
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
        event_publisher=EventPublisher(event_bus),
    )
    create_authorization = _authorization("create")
    created = await _authorized(
        create_authorization, service.create({"name": "Ada"}, authorization=create_authorization)
    )
    async with session_factory() as session:
        record = await session.get(User, created.identity.values["id"])
        assert record is not None
        record.name = "Grace"
        record.revision += 1
        await session.commit()

    regular = _authorization("update")
    confirmation = service.issue_force_overwrite_confirmation(created.identity)
    with pytest.raises(RakitError) as caught:
        await _authorized(
            regular,
            service.update(
                created.identity,
                {"name": "Lin"},
                authorization=regular,
                force_overwrite=True,
                force_overwrite_confirmation=confirmation,
            ),
        )
    assert caught.value.code == ErrorCode.AUTH_FORBIDDEN
    assert events == []

    force_permission = "resources.concurrency_users.force_overwrite"
    forced = MutationAuthorization(
        admin_id="admin",
        resource_id="concurrency_users",
        operation="update",
        principal_id="tester",
        permissions=("admin.resources.concurrency_users.update", force_permission),
    )
    with pytest.raises(RakitError):
        await _authorized(
            forced,
            service.update(
                created.identity,
                {"name": "Lin"},
                authorization=forced,
                force_overwrite=True,
            ),
        )

    result = await _authorized(
        forced,
        service.update(
            created.identity,
            {"name": "Lin"},
            authorization=forced,
            force_overwrite=True,
            force_overwrite_confirmation=confirmation,
        ),
    )
    assert result.record.name == "Lin"
    assert events == [ResourceForceOverwritten(identity=created.identity, changed_fields=("name",))]


@pytest.mark.anyio
async def test_auto_mode_uses_mapper_then_snapshot_then_configured_timestamp(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    signer = TokenService.single_key(key_id="test", value=SecretValue("x" * 32), admin_id="admin")
    schema = FormSchema(fields=(FieldDefinition(field_id="name", python_type=str, required=True),))
    mapper_service = SQLAlchemyMutationService(
        model=ProviderUser,
        session_factory=session_factory,
        form_schema=schema,
        writable_fields=("name",),
        identity_fields=("id",),
        token_service=signer,
        concurrency_mode=ConcurrencyMode.AUTO,
    )
    snapshot_service = SQLAlchemyMutationService(
        model=SnapshotUser,
        session_factory=session_factory,
        form_schema=schema,
        writable_fields=("name",),
        identity_fields=("id",),
        token_service=signer,
        concurrency_mode=ConcurrencyMode.AUTO,
    )
    timestamp_service = SQLAlchemyMutationService(
        model=TimestampUser,
        session_factory=session_factory,
        form_schema=schema,
        writable_fields=("name",),
        identity_fields=("id",),
        token_service=signer,
        concurrency_mode=ConcurrencyMode.AUTO,
    )

    mapper_auth = _authorization("create", "concurrency_provider_users")
    mapper = await _authorized(
        mapper_auth, mapper_service.create({"name": "mapper"}, authorization=mapper_auth)
    )
    snapshot_auth = _authorization("create", "concurrency_snapshot_users")
    snapshot = await _authorized(
        snapshot_auth, snapshot_service.create({"name": "snapshot"}, authorization=snapshot_auth)
    )
    timestamp_auth = _authorization("create", "concurrency_timestamp_users")
    timestamp = await _authorized(
        timestamp_auth,
        timestamp_service.create({"name": "timestamp"}, authorization=timestamp_auth),
    )

    assert (
        signer.verify(
            mapper_service.issue_update_token(mapper.record), expected_purpose="concurrency"
        )["version"]
        == 1
    )
    assert isinstance(
        signer.verify(
            snapshot_service.issue_update_token(snapshot.record), expected_purpose="concurrency"
        )["version"],
        str,
    )
    assert (
        signer.verify(
            timestamp_service.issue_update_token(timestamp.record), expected_purpose="concurrency"
        )["version"]
        == timestamp.record.updated_at.isoformat()
    )


@pytest.mark.anyio
async def test_disabled_mode_requires_no_concurrency_token(
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
        concurrency_mode=ConcurrencyMode.DISABLED,
    )
    create = _authorization("create")
    created = await _authorized(create, service.create({"name": "Ada"}, authorization=create))
    update = _authorization("update")

    result = await _authorized(
        update,
        service.update(created.identity, {"name": "Grace"}, authorization=update),
    )

    assert result.record.name == "Grace"


@pytest.mark.anyio
async def test_required_mode_fails_closed_without_a_safe_provider(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    with pytest.raises(ValueError, match="Required concurrency"):
        SQLAlchemyMutationService(
            model=SnapshotUser,
            session_factory=session_factory,
            form_schema=FormSchema(
                fields=(FieldDefinition(field_id="password_hash", python_type=str),)
            ),
            writable_fields=("password_hash",),
            identity_fields=("id",),
            token_service=TokenService.single_key(
                key_id="test", value=SecretValue("x" * 32), admin_id="admin"
            ),
            concurrency_mode=ConcurrencyMode.REQUIRED,
        )
