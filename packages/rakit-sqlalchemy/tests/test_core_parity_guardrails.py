from __future__ import annotations

from collections.abc import Mapping

import pytest
from rakit_core.concurrency import ConcurrencyTokenService
from rakit_core.config import SecretValue
from rakit_core.crypto import TokenService
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.generated_input import GeneratedInput
from rakit_core.generated_operations import GeneratedCrudRequest
from rakit_core.generated_runtime import GeneratedResourceExecutorContext, ResourceWriteServiceContext
from rakit_core.identity import RecordIdentity
from rakit_core.operations import CancellationContext, OperationContext
from rakit_core.transactions import TransactionPolicy
from rakit_sqlalchemy.core_datasource import SQLAlchemyCoreDataSource
from rakit_sqlalchemy.core_generated import SQLAlchemyCoreGeneratedResourceExecutor
from rakit_sqlalchemy.core_plugin import SQLAlchemyCorePlugin
from rakit_sqlalchemy.core_uow import SQLAlchemyCoreUnitOfWork
from sqlalchemy import Column, Integer, MetaData, String, Table, select
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


class EmptyPredicateProvider:
    def version_for(self, record: object) -> object:
        assert isinstance(record, Mapping)
        return record["version"]

    def predicate_values_for(self, record: object) -> Mapping[str, object]:
        del record
        return {}

    def next_values_for(self, record: object) -> Mapping[str, object]:
        assert isinstance(record, Mapping)
        return {"version": int(record["version"]) + 1}


class EmptyNextValuesProvider:
    def version_for(self, record: object) -> object:
        assert isinstance(record, Mapping)
        return record["version"]

    def predicate_values_for(self, record: object) -> Mapping[str, object]:
        assert isinstance(record, Mapping)
        return {"version": record["version"]}

    def next_values_for(self, record: object) -> Mapping[str, object]:
        del record
        return {}


def _token_service() -> TokenService:
    return TokenService.single_key(
        key_id="test",
        value=SecretValue("core-parity-guardrail-secret-value"),
        admin_id="test",
    )


def _tokens() -> ConcurrencyTokenService:
    return ConcurrencyTokenService(_token_service())


def _table(metadata: MetaData) -> Table:
    return Table(
        "core_parity_guardrails",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String(100), nullable=False),
        Column("version", Integer, nullable=False),
    )


def _source(table: Table, engine: AsyncEngine) -> SQLAlchemyCoreDataSource:
    return SQLAlchemyCoreDataSource(
        table=table,
        engine=engine,
        field_policy=ResourceFieldPolicy(
            list_fields=("id", "name", "version"),
            detail_fields=("id", "name", "version"),
        ),
    )


async def _execute(
    engine: AsyncEngine,
    executor: SQLAlchemyCoreGeneratedResourceExecutor,
    request: GeneratedCrudRequest,
) -> None:
    context = OperationContext(
        deadline=None,
        cancellation=CancellationContext(),
        resource_id="items",
    )
    async with SQLAlchemyCoreUnitOfWork(
        engine,
        policy=TransactionPolicy.AUTO,
        operation_context=context,
    ) as uow:
        object.__setattr__(context, "unit_of_work", uow)
        try:
            await executor.execute(context, request)
            await uow.mark_success()
        finally:
            object.__setattr__(context, "unit_of_work", None)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("provider", "operation", "reason"),
    (
        (
            EmptyPredicateProvider(),
            "update",
            "generated_api_sqlalchemy_core_concurrency_predicate_required",
        ),
        (
            EmptyPredicateProvider(),
            "delete",
            "generated_api_sqlalchemy_core_concurrency_predicate_required",
        ),
        (
            EmptyNextValuesProvider(),
            "update",
            "generated_api_sqlalchemy_core_concurrency_next_values_required",
        ),
    ),
)
async def test_core_atomic_concurrency_fails_closed_before_unguarded_mutation(
    provider: object,
    operation: str,
    reason: str,
) -> None:
    metadata = MetaData()
    table = _table(metadata)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    source = _source(table, engine)
    tokens = _tokens()
    identity = RecordIdentity(values={"id": 1})
    executor = SQLAlchemyCoreGeneratedResourceExecutor(
        resource_id="items",
        data_source=source,
        concurrency_provider=provider,  # type: ignore[arg-type]
        concurrency_tokens=tokens,
    )
    try:
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
            await connection.execute(table.insert().values(id=1, name="before", version=1))

        token = tokens.issue("items", identity, 1)
        request = (
            GeneratedCrudRequest.update_partial(
                identity,
                GeneratedInput(values={"name": "after"}, present_fields=frozenset({"name"})),
                concurrency_token=token,
            )
            if operation == "update"
            else GeneratedCrudRequest.delete(identity, concurrency_token=token)
        )
        with pytest.raises(RakitError) as raised:
            await _execute(engine, executor, request)
        assert raised.value.code == ErrorCode.CONFIG_INVALID
        assert raised.value.details["reason"] == reason

        async with engine.connect() as connection:
            row = (await connection.execute(select(table))).mappings().one()
        assert dict(row) == {"id": 1, "name": "before", "version": 1}
    finally:
        await engine.dispose()


def test_core_adapter_exposes_public_write_service_provider_for_graph_writes() -> None:
    metadata = MetaData()
    table = _table(metadata)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    plugin = SQLAlchemyCorePlugin(engine=engine)
    runtime = plugin._claim(
        table,
        ResourceFieldPolicy(
            list_fields=("id", "name", "version"),
            detail_fields=("id", "name", "version"),
        ),
    )
    assert runtime is not None
    assert runtime.write_service_provider is not None

    # The public compiler consumes this exact provider seam. The concrete
    # service must be graph-capable; relationship forms reject anything else.
    from rakit_core.admin_types import ResourceWriteDefinition
    from rakit_core.fields import FieldDefinition
    from rakit_core.forms import FormSchema

    definition = ResourceWriteDefinition(
        form_schema=FormSchema(
            fields=(FieldDefinition(field_id="name", python_type=str, required=True),)
        ),
        writable_fields=("name",),
        version_field="version",
    )
    service = runtime.write_service_provider.build(
        ResourceWriteServiceContext(
            admin_id="admin",
            resource_id="items",
            definition=definition,
            token_service=_token_service(),
        )
    )
    assert callable(getattr(service, "create_graph", None))
    assert callable(getattr(service, "update_graph", None))
