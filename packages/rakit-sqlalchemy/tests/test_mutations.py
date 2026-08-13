from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import replace
from typing import cast

import pytest
from rakit_core.auth import Principal
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.events import DomainEvent, EventBus, EventPublisher
from rakit_core.fields import FieldDefinition
from rakit_core.forms import FormSchema
from rakit_core.identity import RecordIdentity
from rakit_core.mutations import (
    MutationAuthorization,
    MutationHooks,
    MutationOperation,
    UpdateMutationPlan,
)
from rakit_core.operations import (
    CancellationContext,
    Deadline,
    OperationContext,
    activate_operation_context,
)
from rakit_sqlalchemy.mutations import ResourceCreated, SQLAlchemyMutationService
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "mutation_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    password_hash: Mapped[str | None] = mapped_column(nullable=True)


def _authorization(operation: MutationOperation) -> MutationAuthorization:
    return MutationAuthorization(
        admin_id="admin",
        resource_id="mutation_users",
        operation=operation,
        principal_id="tester",
        permissions=(f"admin.resources.mutation_users.{operation}",),
    )


async def _authorized[T](
    authorization: MutationAuthorization,
    awaitable: Awaitable[T],
    *,
    events: EventPublisher | None = None,
) -> T:
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
        events=events,
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


@pytest.fixture
def received_events() -> tuple[EventPublisher, list[object]]:
    received: list[object] = []
    bus = EventBus()
    bus.subscribe(ResourceCreated, received.append)
    return EventPublisher(bus), received


@pytest.mark.anyio
async def test_create_commits_only_whitelisted_values_and_emits_event(
    session_factory: async_sessionmaker[AsyncSession],
    received_events: tuple[EventPublisher, list[object]],
) -> None:
    publisher, received = received_events
    service = SQLAlchemyMutationService(
        model=User,
        session_factory=session_factory,
        form_schema=FormSchema(
            fields=(FieldDefinition(field_id="name", python_type=str, required=True),)
        ),
        writable_fields=("name",),
        identity_fields=("id",),
        event_publisher=publisher,
    )

    authorization = _authorization("create")
    result = await _authorized(
        authorization, service.create({"name": "Ada"}, authorization=authorization)
    )

    assert result.identity.values == {"id": 1}
    assert cast(User, result.record).name == "Ada"
    assert [type(event).__name__ for event in received] == ["ResourceCreated"]


@pytest.mark.anyio
async def test_long_lived_mutation_service_uses_each_operation_publisher(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    class RecordingPublisher(EventPublisher):
        def __init__(self, bus: EventBus) -> None:
            super().__init__(bus)
            self.published = 0
            self.committed = 0

        def publish(self, event: DomainEvent, *, version: int = 1) -> None:
            self.published += 1
            super().publish(event, version=version)

        async def after_commit(self) -> None:
            self.committed += 1
            await super().after_commit()

    bus = EventBus()
    service = SQLAlchemyMutationService(
        model=User,
        session_factory=session_factory,
        form_schema=FormSchema(
            fields=(FieldDefinition(field_id="name", python_type=str, required=True),)
        ),
        writable_fields=("name",),
        identity_fields=("id",),
        event_publisher=EventPublisher(bus),
    )
    first = RecordingPublisher(bus)
    second = RecordingPublisher(bus)
    authorization = _authorization("create")

    await _authorized(
        authorization,
        service.create({"name": "Ada"}, authorization=authorization),
        events=first,
    )
    await _authorized(
        authorization,
        service.create({"name": "Grace"}, authorization=authorization),
        events=second,
    )

    assert first is not second
    assert (first.published, first.committed) == (1, 1)
    assert (second.published, second.committed) == (1, 1)


@pytest.mark.anyio
async def test_invalid_create_does_not_execute_or_mass_assign(
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
    )

    with pytest.raises(RakitError) as caught:
        authorization = _authorization("create")
        await _authorized(
            authorization,
            service.create({"name": "Ada", "password_hash": "forged"}, authorization=authorization),
        )
    assert caught.value.code == ErrorCode.VALIDATION_FAILED


@pytest.mark.anyio
async def test_normal_update_prepares_submitted_fields_exactly_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    calls = 0

    def parse_once(value: object) -> object:
        nonlocal calls
        calls += 1
        return str(value).strip()

    service = SQLAlchemyMutationService(
        model=User,
        session_factory=session_factory,
        form_schema=FormSchema(
            fields=(FieldDefinition(field_id="name", python_type=str, parser=parse_once),)
        ),
        writable_fields=("name",),
        identity_fields=("id",),
    )
    async with session_factory() as session:
        session.add(User(name="before"))
        await session.commit()

    authorization = _authorization("update")
    await _authorized(
        authorization,
        service.update(
            RecordIdentity(values={"id": 1}), {"name": " after "}, authorization=authorization
        ),
    )
    assert calls == 1
    async with session_factory() as session:
        assert (await session.scalars(select(User.name))).one() == "after"


@pytest.mark.anyio
async def test_normal_create_prepares_submitted_fields_exactly_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    calls = 0

    def parse_once(value: object) -> object:
        nonlocal calls
        calls += 1
        return str(value).strip()

    service = SQLAlchemyMutationService(
        model=User,
        session_factory=session_factory,
        form_schema=FormSchema(
            fields=(FieldDefinition(field_id="name", python_type=str, parser=parse_once),)
        ),
        writable_fields=("name",),
        identity_fields=("id",),
    )
    authorization = _authorization("create")
    await _authorized(authorization, service.create({"name": " Ada "}, authorization=authorization))
    assert calls == 1


@pytest.mark.anyio
async def test_mutation_hooks_run_in_commit_order_and_pre_commit_failure_rolls_back(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    order: list[str] = []

    async def before_execute(_plan: object) -> None:
        order.append("before_execute")

    async def before_commit(_plan: object) -> None:
        order.append("before_commit")

    async def after_commit(_result: object) -> None:
        order.append("after_commit")

    service = SQLAlchemyMutationService(
        model=User,
        session_factory=session_factory,
        form_schema=FormSchema(
            fields=(FieldDefinition(field_id="name", python_type=str, required=True),)
        ),
        writable_fields=("name",),
        identity_fields=("id",),
        hooks=MutationHooks(
            before_execute=(before_execute,),
            before_commit=(before_commit,),
            after_commit=(after_commit,),
        ),
    )

    authorization = _authorization("create")
    await _authorized(authorization, service.create({"name": "Ada"}, authorization=authorization))
    assert order == ["before_execute", "before_commit", "after_commit"]

    async def reject(_plan: object) -> None:
        raise RuntimeError("stop before commit")

    blocked = SQLAlchemyMutationService(
        model=User,
        session_factory=session_factory,
        form_schema=FormSchema(
            fields=(FieldDefinition(field_id="name", python_type=str, required=True),)
        ),
        writable_fields=("name",),
        identity_fields=("id",),
        hooks=MutationHooks(before_commit=(reject,)),
    )
    with pytest.raises(RuntimeError, match="stop before commit"):
        authorization = _authorization("create")
        await _authorized(
            authorization, blocked.create({"name": "Grace"}, authorization=authorization)
        )

    async with session_factory() as session:
        names = list((await session.scalars(select(User.name))).all())
    assert names == ["Ada"]


@pytest.mark.anyio
async def test_post_commit_hook_failure_does_not_reclassify_a_durable_write(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    calls: list[str] = []

    async def fail_after_commit(_result: object) -> None:
        calls.append("after_commit")
        raise RuntimeError("observer unavailable")

    service = SQLAlchemyMutationService(
        model=User,
        session_factory=session_factory,
        form_schema=FormSchema(
            fields=(FieldDefinition(field_id="name", python_type=str, required=True),)
        ),
        writable_fields=("name",),
        identity_fields=("id",),
        hooks=MutationHooks(after_commit=(fail_after_commit,)),
    )

    authorization = _authorization("create")
    result = await _authorized(
        authorization, service.create({"name": "Ada"}, authorization=authorization)
    )

    assert result.identity.values == {"id": 1}
    assert calls == ["after_commit"]
    async with session_factory() as session:
        assert list((await session.scalars(select(User.name))).all()) == ["Ada"]


@pytest.mark.anyio
async def test_create_runs_the_explicit_mutation_pipeline_in_order(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    phases: list[str] = []

    def phase(name: str):
        def record(_value: object) -> None:
            phases.append(name)

        return record

    service = SQLAlchemyMutationService(
        model=User,
        session_factory=session_factory,
        form_schema=FormSchema(
            fields=(FieldDefinition(field_id="name", python_type=str, required=True),)
        ),
        writable_fields=("name",),
        identity_fields=("id",),
        hooks=MutationHooks(
            normalize=(phase("normalize"),),
            business_validate=(phase("validate"),),
            prepare=(phase("prepare"),),
            authorize=(phase("authorize"),),
            pre_event=(phase("pre_event"),),
            before_execute=(phase("execute"),),
            after_execute=(phase("executed"),),
            after_flush=(phase("flush"),),
            before_commit=(phase("before_commit"),),
            after_commit=(phase("post_event"),),
        ),
    )

    authorization = _authorization("create")
    await _authorized(authorization, service.create({"name": "Ada"}, authorization=authorization))
    assert phases == [
        "normalize",
        "validate",
        "prepare",
        "authorize",
        "pre_event",
        "execute",
        "executed",
        "flush",
        "before_commit",
        "post_event",
    ]


@pytest.mark.anyio
async def test_direct_create_without_authorization_is_rejected_before_persistence(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = SQLAlchemyMutationService(
        model=User,
        session_factory=session_factory,
        form_schema=FormSchema(fields=(FieldDefinition(field_id="name", python_type=str),)),
        writable_fields=("name",),
        identity_fields=("id",),
    )

    with pytest.raises(RakitError) as caught:
        await service.create({"name": "Ada"})
    assert caught.value.code == ErrorCode.AUTH_FORBIDDEN
    async with session_factory() as session:
        assert list((await session.scalars(select(User))).all()) == []


@pytest.mark.anyio
async def test_direct_update_rejects_a_create_authorization_before_writing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = SQLAlchemyMutationService(
        model=User,
        session_factory=session_factory,
        form_schema=FormSchema(fields=(FieldDefinition(field_id="name", python_type=str),)),
        writable_fields=("name",),
        identity_fields=("id",),
    )
    create_authorization = _authorization("create")
    created = await _authorized(
        create_authorization,
        service.create({"name": "Ada"}, authorization=create_authorization),
    )

    with pytest.raises(RakitError) as caught:
        await _authorized(
            create_authorization,
            service.update(created.identity, {"name": "Grace"}, authorization=create_authorization),
        )
    assert caught.value.code == ErrorCode.AUTH_FORBIDDEN
    async with session_factory() as session:
        record = await session.get(User, 1)
        assert record is not None
        assert record.name == "Ada"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "mismatch",
    (
        lambda authorization: replace(authorization, admin_id="other-admin"),
        lambda authorization: replace(authorization, principal_id="other-principal"),
        lambda authorization: replace(authorization, permissions=("other.permission",)),
    ),
)
async def test_direct_update_rejects_capability_bindings_that_do_not_match_context(
    session_factory: async_sessionmaker[AsyncSession],
    mismatch: object,
) -> None:
    service = SQLAlchemyMutationService(
        model=User,
        session_factory=session_factory,
        form_schema=FormSchema(fields=(FieldDefinition(field_id="name", python_type=str),)),
        writable_fields=("name",),
        identity_fields=("id",),
    )
    create_authorization = _authorization("create")
    created = await _authorized(
        create_authorization,
        service.create({"name": "Ada"}, authorization=create_authorization),
    )
    expected = _authorization("update")
    provided = cast(Callable[[MutationAuthorization], MutationAuthorization], mismatch)(expected)

    with pytest.raises(RakitError) as caught:
        await _authorized(
            expected,
            service.update(created.identity, {"name": "Grace"}, authorization=provided),
        )
    assert caught.value.code == ErrorCode.AUTH_FORBIDDEN
    async with session_factory() as session:
        record = await session.get(User, 1)
        assert record is not None
        assert record.name == "Ada"


@pytest.mark.anyio
async def test_update_uses_the_bound_resource_scope_for_load_and_atomic_write(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = SQLAlchemyMutationService(
        model=User,
        session_factory=session_factory,
        form_schema=FormSchema(fields=(FieldDefinition(field_id="name", python_type=str),)),
        writable_fields=("name",),
        identity_fields=("id",),
        scoped_statement=lambda: select(User).where(User.name == "visible"),
    )
    async with session_factory() as session:
        session.add_all((User(name="visible"), User(name="hidden")))
        await session.commit()

    with pytest.raises(RakitError) as caught:
        authorization = _authorization("update")
        await _authorized(
            authorization,
            service.update(
                RecordIdentity(values={"id": 2}), {"name": "changed"}, authorization=authorization
            ),
        )
    assert caught.value.code == ErrorCode.RESOURCE_NOT_FOUND
    async with session_factory() as session:
        hidden = await session.get(User, 2)
        assert hidden is not None
        assert hidden.name == "hidden"


@pytest.mark.anyio
async def test_update_uses_update_specific_hooks_with_current_record_and_metadata(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    phases: list[str] = []

    def update_normalize(plan: object) -> None:
        update_plan = cast(UpdateMutationPlan, plan)
        assert cast(User, update_plan.current_record).name == "Ada"
        assert update_plan.scalar_changes == {"name": "Grace"}
        assert update_plan.relationship_changes == {}
        assert update_plan.operation == "update"
        phases.append("normalize_update")

    def update_validate(plan: object) -> None:
        assert cast(UpdateMutationPlan, plan).concurrency_metadata == {}
        phases.append("validate_update")

    service = SQLAlchemyMutationService(
        model=User,
        session_factory=session_factory,
        form_schema=FormSchema(fields=(FieldDefinition(field_id="name", python_type=str),)),
        writable_fields=("name",),
        identity_fields=("id",),
        hooks=MutationHooks(
            normalize=(lambda _plan: phases.append("create_normalize"),),
            normalize_update=(update_normalize,),
            business_validate_update=(update_validate,),
            prepare_update=(lambda _plan: phases.append("prepare_update"),),
            execute_update=(lambda _plan: phases.append("execute_update"),),
        ),
    )
    create_authorization = _authorization("create")
    created = await _authorized(
        create_authorization,
        service.create({"name": "Ada"}, authorization=create_authorization),
    )

    update_authorization = _authorization("update")
    await _authorized(
        update_authorization,
        service.update(created.identity, {"name": "Grace"}, authorization=update_authorization),
    )

    assert phases == [
        "create_normalize",
        "normalize_update",
        "validate_update",
        "prepare_update",
        "execute_update",
    ]
