from __future__ import annotations

import asyncio
import os
import tempfile
from typing import Any, cast

from piccolo.columns import Integer, Varchar
from piccolo.engine.sqlite import SQLiteEngine
from piccolo.table import Table, create_db_tables, drop_db_tables
from rakit_core.adapter_capabilities import (
    PERSISTENCE_READ,
    PERSISTENCE_WRITE,
    TRANSACTIONS_ROOT_UOW,
)
from rakit_core.compiler import ApplicationBuilder
from rakit_core.conformance import conformance_matrix_rows, run_integration_conformance
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.events import EventBus, EventPublisher
from rakit_core.generated_input import GeneratedInput
from rakit_core.generated_operations import GeneratedCrudRequest, GeneratedMutationResult
from rakit_core.generated_runtime import GeneratedResourceExecutorContext
from rakit_core.mutations import ResourceCreated
from rakit_core.operations import CancellationContext, OperationContext
from rakit_core.pagination import LimitOffsetPagination, LimitOffsetResult, PageResult
from rakit_core.query import Filter, FilterOperator, ResourceQuery
from rakit_core.testing.capability_conformance import CANONICAL_CONFORMANCE_SPEC_REGISTRY
from rakit_core.transactions import TransactionPolicy
from rakit_piccolo.discovery import PICCOLO_INTEGRATION
from rakit_piccolo.generated import PiccoloGeneratedResourceExecutor
from rakit_piccolo.plugin import PiccoloPlugin
from rakit_piccolo.uow import PiccoloOperationUnitOfWorkFactory

_FILE_DESCRIPTOR, _DATABASE_PATH = tempfile.mkstemp(prefix="rakit-piccolo-", suffix=".sqlite3")
os.close(_FILE_DESCRIPTOR)
ENGINE = SQLiteEngine(path=_DATABASE_PATH)


class Widget(Table, db=ENGINE):
    name = Varchar()
    group = Varchar()
    score = Integer()


POLICY = ResourceFieldPolicy(
    list_fields=("id", "name", "group", "score"),
    detail_fields=("id", "name", "group", "score"),
    filter_fields=("group", "score"),
    search_fields=("name",),
    sort_fields=("name", "group", "score"),
)


class PiccoloPersistenceConformanceHarness:
    def __init__(self) -> None:
        builder = ApplicationBuilder()
        plugin = PiccoloPlugin(engine=ENGINE)
        builder.install(plugin)
        runtime = plugin._claim(Widget, POLICY)
        assert runtime is not None
        assert runtime.generated_executor_provider is not None
        executor = runtime.generated_executor_provider.build(
            GeneratedResourceExecutorContext(
                resource_id="widgets",
                data_source=runtime.data_source,
            )
        )
        assert isinstance(executor, PiccoloGeneratedResourceExecutor)
        factory = dict(builder.unit_of_work_factories)["persistence.piccolo"]
        assert isinstance(factory, PiccoloOperationUnitOfWorkFactory)
        self.source = runtime.data_source
        self.executor = executor
        self.factory = factory

    async def _reset(self) -> None:
        await Widget.delete(force=True)

    async def _execute(
        self,
        request: GeneratedCrudRequest,
        *,
        success: bool,
        event_publisher: EventPublisher | None = None,
    ) -> tuple[GeneratedMutationResult, OperationContext]:
        context = OperationContext(
            deadline=None,
            cancellation=CancellationContext(),
            resource_id="widgets",
            events=event_publisher,
        )
        async with self.factory.open(
            policy=TransactionPolicy.AUTO,
            event_publisher=event_publisher,
            operation_context=context,
        ) as uow:
            object.__setattr__(context, "unit_of_work", uow)
            try:
                result = await self.executor.execute(context, request)
                if success:
                    await uow.mark_success()
                return result, context
            finally:
                object.__setattr__(context, "unit_of_work", None)

    async def _rows(self) -> tuple[dict[str, Any], ...]:
        rows = await Widget.select().order_by(Widget.id)
        return tuple(dict(row) for row in rows)

    async def assert_read_semantics(self) -> None:
        await self._reset()
        for name, group, score in (
            ("bravo", "engineering", 20),
            ("alpha", "engineering", 10),
            ("charlie", "science", 30),
        ):
            await Widget.objects().create(name=name, group=group, score=score)

        page = await self.source.list(
            ResourceQuery.from_params(
                sort="name",
                page=1,
                per_page=2,
                allowed_sort_fields=("name",),
                identity_fields=("id",),
            )
        )
        assert isinstance(page, PageResult)
        assert [item.name for item in page.items] == ["alpha", "bravo"]
        assert page.has_next is True
        assert page.total_count == 3

        filtered = await self.source.list(
            ResourceQuery.from_params(
                page=1,
                per_page=25,
                allowed_sort_fields=("name",),
                identity_fields=("id",),
                filters=(Filter(field="score", operator=FilterOperator.GTE, value=20),),
                search="a",
            )
        )
        assert [item.name for item in filtered.items] == ["bravo", "charlie"]

        offset = await self.source.list(
            ResourceQuery.from_components(
                pagination=LimitOffsetPagination(offset=1, limit=1),
                sort="name",
                allowed_sort_fields=("name",),
                identity_fields=("id",),
            )
        )
        assert isinstance(offset, LimitOffsetResult)
        assert [item.name for item in offset.items] == ["bravo"]
        assert offset.has_previous is True
        assert offset.has_next is True

    async def assert_write_semantics(self) -> None:
        await self._reset()
        created, _ = await self._execute(
            GeneratedCrudRequest.create(
                GeneratedInput(
                    values={"name": "Created", "group": "test", "score": 1},
                    present_fields=frozenset({"name", "group", "score"}),
                )
            ),
            success=True,
        )
        assert await self._rows() == (
            {
                "id": created.identity.values["id"],
                "name": "Created",
                "group": "test",
                "score": 1,
            },
        )

        updated, _ = await self._execute(
            GeneratedCrudRequest.update_partial(
                created.identity,
                GeneratedInput(
                    values={"score": 2},
                    present_fields=frozenset({"score"}),
                ),
            ),
            success=True,
        )
        assert cast(Widget, updated.record).score == 2

        await self._execute(GeneratedCrudRequest.delete(created.identity), success=True)
        assert await self._rows() == ()

    async def assert_root_uow_semantics(self) -> None:
        await self._reset()
        stable, _ = await self._execute(
            GeneratedCrudRequest.create(
                GeneratedInput(
                    values={"name": "Stable", "group": "test", "score": 1},
                    present_fields=frozenset({"name", "group", "score"}),
                )
            ),
            success=True,
        )

        rollback_context = OperationContext(
            deadline=None,
            cancellation=CancellationContext(),
            resource_id="widgets",
        )
        async with self.factory.open(
            policy=TransactionPolicy.AUTO,
            event_publisher=None,
            operation_context=rollback_context,
        ) as uow:
            object.__setattr__(rollback_context, "unit_of_work", uow)
            try:
                rolled_back = await self.executor.execute(
                    rollback_context,
                    GeneratedCrudRequest.update_partial(
                        stable.identity,
                        GeneratedInput(
                            values={"name": "Rolled back"},
                            present_fields=frozenset({"name"}),
                        ),
                    ),
                )
                assert cast(Widget, rolled_back.record).name == "Rolled back"
            finally:
                object.__setattr__(rollback_context, "unit_of_work", None)
        stable_row = cast(Widget, await self.source.detail(stable.identity))
        assert stable_row.name == "Stable"
        assert rollback_context.durable_commit_completed is False

        observed: list[str] = []
        bus = EventBus()

        async def observe_created(_event: ResourceCreated) -> None:
            observed.append("created")

        bus.subscribe(ResourceCreated, observe_created)
        publisher = EventPublisher(bus)
        commit_context = OperationContext(
            deadline=None,
            cancellation=CancellationContext(),
            resource_id="widgets",
            events=publisher,
        )
        async with self.factory.open(
            policy=TransactionPolicy.AUTO,
            event_publisher=publisher,
            operation_context=commit_context,
        ) as uow:
            object.__setattr__(commit_context, "unit_of_work", uow)
            try:
                committed = await self.executor.execute(
                    commit_context,
                    GeneratedCrudRequest.create(
                        GeneratedInput(
                            values={"name": "Commit", "group": "test", "score": 2},
                            present_fields=frozenset({"name", "group", "score"}),
                        )
                    ),
                )
                assert observed == []
                assert commit_context.durable_commit_completed is False
                await uow.mark_success()
                assert observed == []
                assert commit_context.durable_commit_completed is False
            finally:
                object.__setattr__(commit_context, "unit_of_work", None)

        assert observed == ["created"]
        assert commit_context.durable_commit_completed is True
        committed_row = cast(Widget, await self.source.detail(committed.identity))
        assert (
            committed_row.name,
            committed_row.group,
            committed_row.score,
        ) == ("Commit", "test", 2)


def test_piccolo_conforms_to_every_advertised_v1_capability() -> None:
    async def scenario() -> None:
        await create_db_tables(Widget)
        try:
            harness = PiccoloPersistenceConformanceHarness()
            harnesses = {
                PERSISTENCE_READ.name: harness,
                PERSISTENCE_WRITE.name: harness,
                TRANSACTIONS_ROOT_UOW.name: harness,
            }
            result = await run_integration_conformance(
                descriptor=PICCOLO_INTEGRATION,
                harnesses=harnesses,
                specs=CANONICAL_CONFORMANCE_SPEC_REGISTRY,
            )

            assert PICCOLO_INTEGRATION.advertised_capabilities.names == (
                "persistence.read",
                "persistence.write",
                "transactions.root-uow",
            )
            assert result.passed, result.failures
            rows = conformance_matrix_rows((result,))
            assert len(rows) == 3
            assert all(row.contract_version == 1 and row.passed for row in rows)
        finally:
            await drop_db_tables(Widget)

    try:
        asyncio.run(scenario())
    finally:
        if os.path.exists(_DATABASE_PATH):
            os.unlink(_DATABASE_PATH)
