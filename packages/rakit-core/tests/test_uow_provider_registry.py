from __future__ import annotations

from contextlib import AbstractAsyncContextManager

from rakit_core.compiler import ApplicationBuilder, compile_application
from rakit_core.datasource import DataSourceCapabilities
from rakit_core.definitions import ResourceDefinition, ResourceFieldPolicy
from rakit_core.events import EventPublisher
from rakit_core.identity import RecordIdentity
from rakit_core.operations import OperationContext
from rakit_core.pagination import PageResult, ResourceListResult
from rakit_core.query import ResourceQuery
from rakit_core.transactions import OperationUnitOfWork, TransactionPolicy


class StubDataSource:
    capabilities = DataSourceCapabilities()
    fields = ("id", "name")
    identity_fields = ("id",)

    async def list(self, query: ResourceQuery) -> ResourceListResult[object]:
        return PageResult(
            items=(),
            page=1,
            per_page=25,
            has_previous=False,
            has_next=False,
            total_count=0,
        )

    async def count(self, query: ResourceQuery) -> int:
        return 0

    async def detail(self, identity: RecordIdentity) -> object:
        raise LookupError(identity)


class StubFactory:
    def open(
        self,
        *,
        policy: TransactionPolicy,
        event_publisher: EventPublisher | None,
        operation_context: OperationContext,
    ) -> AbstractAsyncContextManager[OperationUnitOfWork]:
        raise AssertionError("registry tests do not open transactions")


def _resource(resource_id: str) -> ResourceDefinition:
    return ResourceDefinition(
        resource_id=resource_id,
        path=f"/{resource_id}",
        label=resource_id.title(),
        singular_label=resource_id,
        field_policy=ResourceFieldPolicy(
            list_fields=("id", "name"),
            detail_fields=("id", "name"),
        ),
    )


def test_multiple_uow_providers_can_be_registered_without_global_di_collision() -> None:
    builder = ApplicationBuilder()
    first = StubFactory()
    second = StubFactory()

    builder.register_unit_of_work_factory("persistence.first", first)
    builder.register_unit_of_work_factory("persistence.second", second)

    assert dict(builder.unit_of_work_factories) == {
        "persistence.first": first,
        "persistence.second": second,
    }


def test_resource_uow_provider_binding_survives_compilation() -> None:
    builder = ApplicationBuilder()
    first = StubFactory()
    second = StubFactory()
    builder.register_unit_of_work_factory("persistence.first", first)
    builder.register_unit_of_work_factory("persistence.second", second)

    builder.add_resource(
        _resource("first_items"),
        StubDataSource(),
        unit_of_work_provider_id="persistence.first",
    )
    builder.add_resource(
        _resource("second_items"),
        StubDataSource(),
        unit_of_work_provider_id="persistence.second",
    )

    compiled = compile_application(builder)

    assert dict(compiled.unit_of_work_factories) == {
        "persistence.first": first,
        "persistence.second": second,
    }
    assert dict(compiled.resource_unit_of_work_provider_ids) == {
        "first_items": "persistence.first",
        "second_items": "persistence.second",
    }
