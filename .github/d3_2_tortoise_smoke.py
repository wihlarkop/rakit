from __future__ import annotations

import asyncio

from rakit_core.compiler import ApplicationBuilder
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.events import EventBus, EventPublisher
from rakit_core.generated_input import GeneratedInput
from rakit_core.generated_operations import GeneratedCrudRequest, GeneratedMutationResult
from rakit_core.generated_runtime import GeneratedResourceExecutorContext
from rakit_core.operations import CancellationContext, OperationContext
from rakit_core.transactions import TransactionPolicy
from rakit_tortoise.plugin import TortoisePlugin
from tortoise import Tortoise, fields
from tortoise.models import Model


class Widget(Model):
    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=100)
    score = fields.IntField(null=True)


async def main() -> None:
    await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["__main__"]})
    await Tortoise.generate_schemas()
    try:
        builder = ApplicationBuilder()
        plugin = TortoisePlugin()
        builder.install(plugin)
        runtime = plugin._claim(
            Widget,
            ResourceFieldPolicy(
                list_fields=("id", "name", "score"),
                detail_fields=("id", "name", "score"),
                filter_fields=("name", "score"),
                search_fields=("name",),
                sort_fields=("name", "score"),
            ),
        )
        assert runtime is not None
        assert runtime.generated_executor_provider is not None
        assert runtime.unit_of_work_provider_id == "persistence.tortoise"

        executor = runtime.generated_executor_provider.build(
            GeneratedResourceExecutorContext(
                resource_id="widgets",
                data_source=runtime.data_source,
            )
        )
        factory = dict(builder.unit_of_work_factories)["persistence.tortoise"]

        observed: list[str] = []
        bus = EventBus()

        async def observe_created(_event: object) -> None:
            observed.append("created")

        from rakit_core.mutations import ResourceCreated

        bus.subscribe(ResourceCreated, observe_created)
        publisher = EventPublisher(bus)
        create_context = OperationContext(
            deadline=None,
            cancellation=CancellationContext(),
            operation_id="create-widget",
            events=publisher,
        )
        async with factory.open(
            policy=TransactionPolicy.AUTO,
            event_publisher=publisher,
            operation_context=create_context,
        ) as uow:
            object.__setattr__(create_context, "unit_of_work", uow)
            created = await executor.execute(
                create_context,
                GeneratedCrudRequest.create(
                    GeneratedInput(
                        values={"name": "Alpha", "score": 10},
                        present_fields=frozenset({"name", "score"}),
                    )
                ),
            )
            assert isinstance(created, GeneratedMutationResult)
            assert observed == []
            await uow.mark_success()
        object.__setattr__(create_context, "unit_of_work", None)
        assert create_context.durable_commit_completed is True
        assert observed == ["created"]
        identity = created.identity
        row = await Widget.get(id=identity.values["id"])
        assert (row.name, row.score) == ("Alpha", 10)

        rollback_context = OperationContext(
            deadline=None,
            cancellation=CancellationContext(),
            operation_id="rollback-widget",
        )
        async with factory.open(
            policy=TransactionPolicy.AUTO,
            event_publisher=None,
            operation_context=rollback_context,
        ) as uow:
            object.__setattr__(rollback_context, "unit_of_work", uow)
            await executor.execute(
                rollback_context,
                GeneratedCrudRequest.update_partial(
                    identity,
                    GeneratedInput(
                        values={"name": "Rolled back"},
                        present_fields=frozenset({"name"}),
                    ),
                ),
            )
        object.__setattr__(rollback_context, "unit_of_work", None)
        row = await Widget.get(id=identity.values["id"])
        assert row.name == "Alpha"

        update_context = OperationContext(
            deadline=None,
            cancellation=CancellationContext(),
            operation_id="update-widget",
        )
        async with factory.open(
            policy=TransactionPolicy.AUTO,
            event_publisher=None,
            operation_context=update_context,
        ) as uow:
            object.__setattr__(update_context, "unit_of_work", uow)
            await executor.execute(
                update_context,
                GeneratedCrudRequest.update_partial(
                    identity,
                    GeneratedInput(
                        values={"name": "Updated"},
                        present_fields=frozenset({"name"}),
                    ),
                ),
            )
            await uow.mark_success()
        object.__setattr__(update_context, "unit_of_work", None)
        row = await Widget.get(id=identity.values["id"])
        assert row.name == "Updated"

        delete_context = OperationContext(
            deadline=None,
            cancellation=CancellationContext(),
            operation_id="delete-widget",
        )
        async with factory.open(
            policy=TransactionPolicy.AUTO,
            event_publisher=None,
            operation_context=delete_context,
        ) as uow:
            object.__setattr__(delete_context, "unit_of_work", uow)
            await executor.execute(delete_context, GeneratedCrudRequest.delete(identity))
            await uow.mark_success()
        object.__setattr__(delete_context, "unit_of_work", None)
        assert await Widget.filter(id=identity.values["id"]).count() == 0
    finally:
        await Tortoise.close_connections()


asyncio.run(main())
