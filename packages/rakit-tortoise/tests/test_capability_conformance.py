from __future__ import annotations

import asyncio
from typing import cast

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
from rakit_tortoise.discovery import TORTOISE_INTEGRATION
from rakit_tortoise.generated import TortoiseGeneratedResourceExecutor
from rakit_tortoise.plugin import TortoisePlugin
from rakit_tortoise.uow import TortoiseOperationUnitOfWorkFactory
from tortoise import Tortoise, fields
from tortoise.models import Model


class Widget(Model):
    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=100)
    group = fields.CharField(max_length=100)
    score = fields.IntField()


POLICY = ResourceFieldPolicy(
    list_fields=("id", "name", "group", "score"),
    detail_fields=("id", "name", "group", "score"),
    filter_fields=("group", "score"),
    search_fields=("name",),
    sort_fields=("name", "group", "score"),
)


class TortoisePersistenceConformanceHarness:
    def __init__(self) -> None:
        builder = ApplicationBuilder()
        plugin = TortoisePlugin()
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
        assert isinstance(executor, TortoiseGeneratedResourceExecutor)
        factory = dict(builder.unit_of_work_factories)["persistence.tortoise"]
        assert isinstance(factory, TortoiseOperationUnitOfWorkFactory)
        self.source = runtime.data_source
        self.executor = executor
        self.factory = factory

    async def _reset(self) -> None:
        await Widget.all().delete()

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

    async def _rows(self) -> tuple[dict[str, object], ...]:
        rows = await Widget.all().order_by("id").values("id", "name", "group", "score")
        return tuple(dict(row) for row in rows)

    async def assert_read_semantics(self) -> None:
        await self._reset()
        await Widget.create(name="bravo", group="engineering", score=20)
        await Widget.create(name="alpha", group="engineering", score=10)
        await Widget.create(name="charlie", group="science", score=30)

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
        assert [cast(Widget, item).name for item in page.items] == ["alpha", "bravo"]
        assert page.has_next is True
        assert page.total_count == 3

        filtered = await self.source.list(
            ResourceQuery.from_params(
                page=1,
                per_page=25,
                allowed_sort_fields=("name",),
                identity_fields=("id",),
                filters=(
                    Filter(field="score", operator=FilterOperator.GTE, value=20),
                ),
                search="a",
            )
        )
        assert [cast(Widget, item).name for item in filtered.items] == ["bravo", "charlie"]

        offset = await self.source.list(
            ResourceQuery.from_components(
                pagination=LimitOffsetPagination(offset=1, limit=1),
                sort="name",
                allowed_sort_fields=("name",),
                identity_fields=("id",),
            )
        )
        assert isinstance(offset, LimitOffsetResult)
        assert [cast(Widget, item).name for item in offset.items] == ["bravo"]
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
        updated_record = cast(Widget, updated.record)
        assert (
            updated_record.id,
            updated_record.name,
            updated_record.group,
            updated_record.score,
        ) == (created.identity.values["id"], "Created", "test", 2)

        await self._execute(GeneratedCrudRequest.delete(created.identity), success=True)
        assert await self._rows() == ()

    async def assert_root_uow_semantics(self) -> None:
        await self._reset()
        rolled_back, rollback_context = await self._execute(
            GeneratedCrudRequest.create(
                GeneratedInput(
                    values={"name": "Rollback", "group": "test", "score": 1},
                    present_fields=frozenset({"name", "group", "score"}),
                )
            ),
            success=False,
        )
        assert rolled_back.record is not None
        assert await self._rows() == ()
        assert rollback_context.durable_commit_completed is False

        observed: list[str] = []
        bus = EventBus()

        async def observe_created(_event: ResourceCreated) -> None:
            observed.append("created")

        bus.subscribe(ResourceCreated, observe_created)
        publisher = EventPublisher(bus)
        committed, commit_context = await self._execute(
            GeneratedCrudRequest.create(
                GeneratedInput(
                    values={"name": "Commit", "group": "test", "score": 2},
                    present_fields=frozenset({"name", "group", "score"}),
                )
            ),
            success=True,
            event_publisher=publisher,
        )
        assert observed == ["created"]
        assert await self._rows() == (
            {
                "id": committed.identity.values["id"],
                "name": "Commit",
                "group": "test",
                "score": 2,
            },
        )
        assert commit_context.durable_commit_completed is True


def test_tortoise_conforms_to_every_advertised_v1_capability() -> None:
    async def scenario() -> None:
        await Tortoise.init(db_url="sqlite://:memory:", modules={"models": [__name__]})
        await Tortoise.generate_schemas()
        try:
            harness = TortoisePersistenceConformanceHarness()
            harnesses = {
                PERSISTENCE_READ.name: harness,
                PERSISTENCE_WRITE.name: harness,
                TRANSACTIONS_ROOT_UOW.name: harness,
            }
            result = await run_integration_conformance(
                descriptor=TORTOISE_INTEGRATION,
                harnesses=harnesses,
                specs=CANONICAL_CONFORMANCE_SPEC_REGISTRY,
            )

            assert TORTOISE_INTEGRATION.advertised_capabilities.names == (
                "persistence.read",
                "persistence.write",
                "transactions.root-uow",
            )
            assert result.passed, result.failures
            rows = conformance_matrix_rows((result,))
            assert len(rows) == 3
            assert all(row.contract_version == 1 and row.passed for row in rows)
        finally:
            await Tortoise.close_connections()

    asyncio.run(scenario())
