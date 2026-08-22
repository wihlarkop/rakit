from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from rakit_core.compiler import ApplicationBuilder
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.events import EventBus, EventPublisher
from rakit_core.generated_input import GeneratedInput
from rakit_core.generated_operations import GeneratedCrudRequest
from rakit_core.generated_runtime import GeneratedResourceExecutorContext
from rakit_core.mutations import ResourceCreated
from rakit_core.operations import CancellationContext, OperationContext
from rakit_core.transactions import TransactionPolicy
from rakit_sqlalchemy.core_generated import SQLAlchemyCoreGeneratedResourceExecutor
from rakit_sqlalchemy.core_plugin import SQLAlchemyCorePlugin
from rakit_sqlalchemy.core_uow import SQLAlchemyCoreOperationUnitOfWorkFactory
from sqlalchemy import Column, Integer, MetaData, String, Table, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

metadata = MetaData()
items = Table(
    "core_write_items",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(100), nullable=False),
)


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    value = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with value.begin() as connection:
        await connection.run_sync(metadata.create_all)
    yield value
    await value.dispose()


def _policy() -> ResourceFieldPolicy:
    return ResourceFieldPolicy(
        list_fields=("id", "name"),
        detail_fields=("id", "name"),
    )


def _runtime(engine: AsyncEngine):
    builder = ApplicationBuilder()
    plugin = SQLAlchemyCorePlugin(engine=engine)
    builder.install(plugin)
    runtime = plugin._claim(items, _policy())
    assert runtime is not None
    assert runtime.generated_executor_provider is not None
    executor = runtime.generated_executor_provider.build(
        GeneratedResourceExecutorContext(
            resource_id="items",
            data_source=runtime.data_source,
        )
    )
    assert isinstance(executor, SQLAlchemyCoreGeneratedResourceExecutor)
    factory = dict(builder.unit_of_work_factories)["persistence.sqlalchemy-core"]
    assert isinstance(factory, SQLAlchemyCoreOperationUnitOfWorkFactory)
    return runtime, executor, factory


async def _execute(
    executor: SQLAlchemyCoreGeneratedResourceExecutor,
    factory: SQLAlchemyCoreOperationUnitOfWorkFactory,
    request: GeneratedCrudRequest,
    *,
    success: bool,
    events: EventPublisher | None = None,
):
    context = OperationContext(
        deadline=None,
        cancellation=CancellationContext(),
        resource_id="items",
        events=events,
    )
    async with factory.open(
        policy=TransactionPolicy.AUTO,
        event_publisher=events,
        operation_context=context,
    ) as uow:
        object.__setattr__(context, "unit_of_work", uow)
        try:
            result = await executor.execute(context, request)
            if success:
                await uow.mark_success()
            return result, context
        finally:
            object.__setattr__(context, "unit_of_work", None)


async def _row(engine: AsyncEngine) -> dict[str, object] | None:
    async with engine.connect() as connection:
        result = await connection.execute(select(items))
        value = result.mappings().one_or_none()
        return None if value is None else dict(value)


@pytest.mark.anyio
async def test_core_generated_scalar_create_update_delete_commit_through_root_uow(engine) -> None:
    runtime, executor, factory = _runtime(engine)
    assert runtime.unit_of_work_provider_id == "persistence.sqlalchemy-core"

    created, _ = await _execute(
        executor,
        factory,
        GeneratedCrudRequest.create(
            GeneratedInput(values={"name": "created"}, present_fields=frozenset({"name"}))
        ),
        success=True,
    )
    assert await _row(engine) == {"id": created.identity.values["id"], "name": "created"}

    updated, _ = await _execute(
        executor,
        factory,
        GeneratedCrudRequest.update_partial(
            created.identity,
            GeneratedInput(values={"name": "updated"}, present_fields=frozenset({"name"})),
        ),
        success=True,
    )
    assert updated.record == {"id": created.identity.values["id"], "name": "updated"}
    assert await _row(engine) == updated.record

    await _execute(
        executor,
        factory,
        GeneratedCrudRequest.delete(created.identity),
        success=True,
    )
    assert await _row(engine) is None


@pytest.mark.anyio
async def test_core_root_uow_rolls_back_mutation_without_success(engine) -> None:
    _, executor, factory = _runtime(engine)
    created, _ = await _execute(
        executor,
        factory,
        GeneratedCrudRequest.create(
            GeneratedInput(values={"name": "temporary"}, present_fields=frozenset({"name"}))
        ),
        success=False,
    )

    assert created.record == {"id": created.identity.values["id"], "name": "temporary"}
    assert await _row(engine) is None


@pytest.mark.anyio
async def test_core_deferred_events_dispatch_after_durable_commit_without_completed_uow(
    engine,
) -> None:
    _, executor, factory = _runtime(engine)
    bus = EventBus()
    publisher = EventPublisher(bus)
    observations: list[tuple[int, object | None]] = []
    active_context: list[OperationContext] = []

    async def observe(_event: ResourceCreated) -> None:
        async with engine.connect() as connection:
            count = int((await connection.scalar(select(func.count()).select_from(items))) or 0)
        observations.append((count, active_context[0].unit_of_work))

    bus.subscribe(ResourceCreated, observe)
    request = GeneratedCrudRequest.create(
        GeneratedInput(values={"name": "event"}, present_fields=frozenset({"name"}))
    )
    context = OperationContext(
        deadline=None,
        cancellation=CancellationContext(),
        resource_id="items",
        events=publisher,
    )
    active_context.append(context)
    async with factory.open(
        policy=TransactionPolicy.AUTO,
        event_publisher=publisher,
        operation_context=context,
    ) as uow:
        object.__setattr__(context, "unit_of_work", uow)
        try:
            await executor.execute(context, request)
            assert observations == []
            await uow.mark_success()
        finally:
            object.__setattr__(context, "unit_of_work", None)

    assert observations == [(1, None)]
    assert context.durable_commit_completed is True
