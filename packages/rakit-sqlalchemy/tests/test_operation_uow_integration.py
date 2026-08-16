"""Real SQLAlchemy operation-UoW integration."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import cast

import pytest
from rakit_core.compiler import ApplicationBuilder
from rakit_core.events import DomainEvent, EventBus, EventPublisher
from rakit_core.mutations import OperationAuthorization
from rakit_core.operations import (
    CancellationContext,
    OperationContext,
    OperationExecutorCapabilities,
    OperationKind,
    OperationPlan,
    run_operation_plan,
)
from rakit_core.permissions import PermissionRequirement
from rakit_core.transactions import OperationUnitOfWorkFactory, TransactionPolicy
from rakit_sqlalchemy.plugin import SQLAlchemyPlugin
from rakit_sqlalchemy.uow import SQLAlchemyOperationUnitOfWorkFactory, SQLAlchemyUnitOfWork
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Item(Base):
    __tablename__ = "c2a_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


@dataclass(frozen=True)
class ItemCreated(DomainEvent):
    pass


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def _authorization() -> OperationAuthorization:
    return OperationAuthorization.for_requirement(
        admin_id="ops",
        resource_id="items",
        operation="action:write",
        principal_id="operator",
        requirement=PermissionRequirement.all_of("ops.actions.write.execute"),
    )


def _context(*, events: EventPublisher | None = None) -> OperationContext:
    authorization = _authorization()
    return OperationContext(
        deadline=None,
        cancellation=CancellationContext(),
        operation_id="op-1",
        principal_id="operator",
        admin_id="ops",
        resource_id="items",
        operation="action:write",
        permissions=authorization.permissions,
        permission_requirement=authorization.requirement,
        events=events,
    )


def _plan(execute, *, policy: TransactionPolicy = TransactionPolicy.AUTO, success=None):
    return OperationPlan(
        operation_id="write",
        kind=OperationKind.ACTION,
        input=None,
        authorization=_authorization(),
        execute=execute,
        mutating=True,
        transaction_policy=policy,
        executor_capabilities=OperationExecutorCapabilities(participates_in_uow=True),
        result_is_success=success or (lambda result: result == "ok"),
    )


async def _count(factory: async_sessionmaker[AsyncSession]) -> int:
    async with factory() as session:
        return int(await session.scalar(select(func.count(Item.id))) or 0)


@pytest.mark.anyio
async def test_sqlalchemy_plugin_registers_the_generic_uow_factory(session_factory) -> None:
    builder = ApplicationBuilder(admin_id="ops")
    SQLAlchemyPlugin(session_factory=session_factory).configure(builder)
    resolver = builder.registry.application_scope()
    factory = resolver.require(OperationUnitOfWorkFactory)
    assert isinstance(factory, SQLAlchemyOperationUnitOfWorkFactory)
    assert factory._session_factory is session_factory


@pytest.mark.anyio
async def test_auto_success_commits_and_exception_or_rejection_rolls_back(session_factory) -> None:
    factory = SQLAlchemyOperationUnitOfWorkFactory(session_factory)

    async def success(context: OperationContext, _input: None) -> str:
        uow = cast(SQLAlchemyUnitOfWork, context.unit_of_work)
        uow.session.add(Item(id=1, name="committed"))
        return "ok"

    await run_operation_plan(_plan(success), _context(), unit_of_work_factory=factory)
    assert await _count(session_factory) == 1

    async def rejected(context: OperationContext, _input: None) -> str:
        uow = cast(SQLAlchemyUnitOfWork, context.unit_of_work)
        uow.session.add(Item(id=2, name="rejected"))
        return "rejected"

    await run_operation_plan(_plan(rejected), _context(), unit_of_work_factory=factory)
    assert await _count(session_factory) == 1

    async def exploding(context: OperationContext, _input: None) -> str:
        uow = cast(SQLAlchemyUnitOfWork, context.unit_of_work)
        uow.session.add(Item(id=3, name="boom"))
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await run_operation_plan(_plan(exploding), _context(), unit_of_work_factory=factory)
    assert await _count(session_factory) == 1


@pytest.mark.anyio
async def test_manual_commit_is_durable_and_no_completion_rolls_back(session_factory) -> None:
    factory = SQLAlchemyOperationUnitOfWorkFactory(session_factory)

    async def committed(context: OperationContext, _input: None) -> str:
        uow = cast(SQLAlchemyUnitOfWork, context.unit_of_work)
        uow.session.add(Item(id=1, name="manual"))
        await uow.commit()
        return "ok"

    await run_operation_plan(
        _plan(committed, policy=TransactionPolicy.MANUAL),
        _context(),
        unit_of_work_factory=factory,
    )
    assert await _count(session_factory) == 1

    async def incomplete(context: OperationContext, _input: None) -> str:
        uow = cast(SQLAlchemyUnitOfWork, context.unit_of_work)
        uow.session.add(Item(id=2, name="rolled back"))
        return "ok"

    await run_operation_plan(
        _plan(incomplete, policy=TransactionPolicy.MANUAL),
        _context(),
        unit_of_work_factory=factory,
    )
    assert await _count(session_factory) == 1


@pytest.mark.anyio
async def test_nested_sqlalchemy_uow_inherits_root_session(session_factory) -> None:
    factory = SQLAlchemyOperationUnitOfWorkFactory(session_factory)
    seen_same_session: list[bool] = []

    async def execute(context: OperationContext, _input: None) -> str:
        root = cast(SQLAlchemyUnitOfWork, context.unit_of_work)
        async with SQLAlchemyUnitOfWork(session_factory, policy=TransactionPolicy.AUTO) as nested:
            seen_same_session.append(nested.session is root.session)
            nested.session.add(Item(id=1, name="nested"))
            await nested.mark_success()
            with pytest.raises(RuntimeError, match="Nested unit of work"):
                await nested.commit()
        return "ok"

    await run_operation_plan(_plan(execute), _context(), unit_of_work_factory=factory)
    assert seen_same_session == [True]
    assert await _count(session_factory) == 1


@pytest.mark.anyio
async def test_events_dispatch_only_after_commit_and_see_no_completed_uow(session_factory) -> None:
    bus = EventBus()
    publisher = EventPublisher(bus)
    context = _context(events=publisher)
    observations: list[tuple[int, object | None]] = []

    async def observe(_event: ItemCreated) -> None:
        observations.append((await _count(session_factory), context.unit_of_work))

    bus.subscribe(ItemCreated, observe)
    factory = SQLAlchemyOperationUnitOfWorkFactory(session_factory)

    async def execute(operation_context: OperationContext, _input: None) -> str:
        uow = cast(SQLAlchemyUnitOfWork, operation_context.unit_of_work)
        uow.session.add(Item(id=1, name="event"))
        assert operation_context.events is publisher
        publisher.publish(ItemCreated())
        assert observations == []
        return "ok"

    await run_operation_plan(_plan(execute), context, unit_of_work_factory=factory)
    assert observations == [(1, None)]


@pytest.mark.anyio
async def test_rollback_discards_events_and_manual_commit_detaches_generic_uow(
    session_factory,
) -> None:
    bus = EventBus()
    publisher = EventPublisher(bus)
    rollback_context = _context(events=publisher)
    observed_uows: list[object | None] = []

    async def observe(_event: ItemCreated) -> None:
        observed_uows.append(active_context[0].unit_of_work)

    bus.subscribe(ItemCreated, observe)
    factory = SQLAlchemyOperationUnitOfWorkFactory(session_factory)
    active_context = [rollback_context]

    async def rejected(operation_context: OperationContext, _input: None) -> str:
        publisher.publish(ItemCreated())
        return "rejected"

    await run_operation_plan(_plan(rejected), rollback_context, unit_of_work_factory=factory)
    assert observed_uows == []

    manual_context = _context(events=publisher)
    active_context[0] = manual_context

    async def manual(operation_context: OperationContext, _input: None) -> str:
        uow = cast(SQLAlchemyUnitOfWork, operation_context.unit_of_work)
        uow.session.add(Item(id=1, name="manual-event"))
        publisher.publish(ItemCreated())
        await uow.commit()
        return "ok"

    await run_operation_plan(
        _plan(manual, policy=TransactionPolicy.MANUAL),
        manual_context,
        unit_of_work_factory=factory,
    )
    assert observed_uows == [None]
    assert await _count(session_factory) == 1
