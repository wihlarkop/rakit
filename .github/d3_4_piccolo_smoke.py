from __future__ import annotations

import asyncio
import os
import tempfile
from typing import cast

from piccolo.columns import Integer, Varchar
from piccolo.engine.sqlite import SQLiteEngine
from piccolo.table import Table, create_db_tables, drop_db_tables
from rakit_core.compiler import ApplicationBuilder
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.generated_input import GeneratedInput
from rakit_core.generated_operations import GeneratedCrudRequest
from rakit_core.generated_runtime import GeneratedResourceExecutorContext
from rakit_core.operations import CancellationContext, OperationContext
from rakit_core.pagination import PageResult
from rakit_core.query import Filter, FilterOperator, ResourceQuery
from rakit_core.transactions import TransactionPolicy
from rakit_piccolo.generated import PiccoloGeneratedResourceExecutor
from rakit_piccolo.plugin import PiccoloPlugin
from rakit_piccolo.uow import PiccoloOperationUnitOfWorkFactory

_FD, _PATH = tempfile.mkstemp(prefix="rakit-piccolo-", suffix=".sqlite3")
os.close(_FD)
ENGINE = SQLiteEngine(path=_PATH)


class Widget(Table, db=ENGINE):
    name = Varchar()
    group = Varchar()
    score = Integer()


POLICY = ResourceFieldPolicy(
    list_fields=("id", "name", "group", "score"),
    detail_fields=("id", "name", "group", "score"),
    filter_fields=("group", "score"),
    search_fields=("name",),
    sort_fields=("name", "score"),
)


async def execute(executor, factory, request, *, success: bool):
    context = OperationContext(
        deadline=None,
        cancellation=CancellationContext(),
        resource_id="widgets",
    )
    async with factory.open(
        policy=TransactionPolicy.AUTO,
        event_publisher=None,
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


async def main() -> None:
    await create_db_tables(Widget)
    try:
        builder = ApplicationBuilder()
        plugin = PiccoloPlugin(engine=ENGINE)
        builder.install(plugin)
        runtime = plugin._claim(Widget, POLICY)
        assert runtime is not None
        assert runtime.unit_of_work_provider_id == "persistence.piccolo"
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

        created, create_context = await execute(
            executor,
            factory,
            GeneratedCrudRequest.create(
                GeneratedInput(
                    values={"name": "alpha", "group": "test", "score": 1},
                    present_fields=frozenset({"name", "group", "score"}),
                )
            ),
            success=True,
        )
        assert create_context.durable_commit_completed is True
        committed = cast(Widget, await runtime.data_source.detail(created.identity))
        assert committed.name == "alpha"

        page = await runtime.data_source.list(
            ResourceQuery.from_params(
                page=1,
                per_page=10,
                search="alp",
                filters=(Filter(field="score", operator=FilterOperator.GTE, value=1),),
                sort="name",
                allowed_sort_fields=("name",),
                identity_fields=("id",),
            )
        )
        assert isinstance(page, PageResult)
        assert [item.name for item in page.items] == ["alpha"]
        assert page.total_count == 1

        rolled_back, rollback_context = await execute(
            executor,
            factory,
            GeneratedCrudRequest.update_partial(
                created.identity,
                GeneratedInput(
                    values={"name": "rolled-back"},
                    present_fields=frozenset({"name"}),
                ),
            ),
            success=False,
        )
        assert rolled_back.record.name == "rolled-back"
        assert rollback_context.durable_commit_completed is False
        stable = cast(Widget, await runtime.data_source.detail(created.identity))
        assert stable.name == "alpha"

        updated, update_context = await execute(
            executor,
            factory,
            GeneratedCrudRequest.update_partial(
                created.identity,
                GeneratedInput(
                    values={"score": 2},
                    present_fields=frozenset({"score"}),
                ),
            ),
            success=True,
        )
        assert update_context.durable_commit_completed is True
        assert updated.record.score == 2

        _, delete_context = await execute(
            executor,
            factory,
            GeneratedCrudRequest.delete(created.identity),
            success=True,
        )
        assert delete_context.durable_commit_completed is True
        assert await Widget.count() == 0
    finally:
        await drop_db_tables(Widget)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        if os.path.exists(_PATH):
            os.unlink(_PATH)
