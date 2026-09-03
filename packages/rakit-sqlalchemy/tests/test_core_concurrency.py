from __future__ import annotations

import pytest
from rakit_core.concurrency import ConcurrencyTokenService
from rakit_core.config import SecretValue
from rakit_core.crypto import TokenService
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.generated_input import GeneratedInput
from rakit_core.generated_operations import GeneratedCrudRequest
from rakit_core.generated_runtime import GeneratedResourceExecutorContext
from rakit_core.identity import RecordIdentity
from rakit_core.operations import CancellationContext, OperationContext
from rakit_core.transactions import TransactionPolicy
from rakit_sqlalchemy.core_concurrency import MappingVersionProvider
from rakit_sqlalchemy.core_datasource import SQLAlchemyCoreDataSource
from rakit_sqlalchemy.core_generated import (
    SQLAlchemyCoreGeneratedResourceExecutor,
    SQLAlchemyCoreGeneratedResourceExecutorProvider,
)
from rakit_sqlalchemy.core_uow import SQLAlchemyCoreUnitOfWork
from sqlalchemy import Column, Integer, MetaData, String, Table, select
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def _identity(value: int) -> RecordIdentity:
    return RecordIdentity(values={"id": value})


def _tokens() -> ConcurrencyTokenService:
    return ConcurrencyTokenService(
        TokenService.single_key(
            key_id="test",
            value=SecretValue("core-atomic-concurrency-secret-value"),
            admin_id="test",
        )
    )


def _table(metadata: MetaData) -> Table:
    return Table(
        "core_atomic_items",
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
            sort_fields=("name",),
        ),
    )


def _executor(
    source: SQLAlchemyCoreDataSource,
    tokens: ConcurrencyTokenService,
) -> SQLAlchemyCoreGeneratedResourceExecutor:
    built = SQLAlchemyCoreGeneratedResourceExecutorProvider(source).build(
        GeneratedResourceExecutorContext(
            resource_id="items",
            data_source=source,
            concurrency_provider=MappingVersionProvider("version"),
            concurrency_tokens=tokens,
        )
    )
    assert isinstance(built, SQLAlchemyCoreGeneratedResourceExecutor)
    return built


async def _execute(
    engine: AsyncEngine,
    executor: SQLAlchemyCoreGeneratedResourceExecutor,
    request: GeneratedCrudRequest,
    *,
    success: bool = True,
):
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
            result = await executor.execute(context, request)
            if success:
                await uow.mark_success()
            return result
        finally:
            object.__setattr__(context, "unit_of_work", None)


@pytest.mark.anyio
async def test_core_atomic_update_increments_version_and_rejects_stale_token() -> None:
    metadata = MetaData()
    table = _table(metadata)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    tokens = _tokens()
    source = _source(table, engine)
    executor = _executor(source, tokens)
    identity = _identity(1)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
            await connection.execute(table.insert().values(id=1, name="before", version=1))

        stale_token = tokens.issue("items", identity, 1)
        result = await _execute(
            engine,
            executor,
            GeneratedCrudRequest.update_partial(
                identity,
                GeneratedInput(values={"name": "after"}, present_fields=frozenset({"name"})),
                concurrency_token=stale_token,
            ),
        )
        assert result.record == {"id": 1, "name": "after", "version": 2}

        with pytest.raises(RakitError) as raised:
            await _execute(
                engine,
                executor,
                GeneratedCrudRequest.update_partial(
                    identity,
                    GeneratedInput(
                        values={"name": "stale-overwrite"},
                        present_fields=frozenset({"name"}),
                    ),
                    concurrency_token=stale_token,
                ),
            )
        assert raised.value.code == ErrorCode.RESOURCE_CONFLICT
        assert raised.value.status_code == 409

        async with engine.connect() as connection:
            row = (await connection.execute(select(table))).mappings().one()
        assert dict(row) == {"id": 1, "name": "after", "version": 2}
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_core_atomic_delete_requires_current_version_and_deletes_once() -> None:
    metadata = MetaData()
    table = _table(metadata)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    tokens = _tokens()
    source = _source(table, engine)
    executor = _executor(source, tokens)
    identity = _identity(1)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
            await connection.execute(table.insert().values(id=1, name="delete-me", version=3))

        with pytest.raises(RakitError) as stale:
            await _execute(
                engine,
                executor,
                GeneratedCrudRequest.delete(
                    identity,
                    concurrency_token=tokens.issue("items", identity, 2),
                ),
            )
        assert stale.value.code == ErrorCode.RESOURCE_CONFLICT

        deleted = await _execute(
            engine,
            executor,
            GeneratedCrudRequest.delete(
                identity,
                concurrency_token=tokens.issue("items", identity, 3),
            ),
        )
        assert deleted.identity == identity
        assert deleted.record is None

        async with engine.connect() as connection:
            assert (await connection.scalar(select(table.c.id))) is None

        with pytest.raises(RakitError) as missing:
            await _execute(
                engine,
                executor,
                GeneratedCrudRequest.delete(
                    identity,
                    concurrency_token=tokens.issue("items", identity, 3),
                ),
            )
        assert missing.value.code == ErrorCode.RESOURCE_NOT_FOUND
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_core_atomic_delete_rechecks_scope_at_final_write_boundary() -> None:
    metadata = MetaData()
    table = Table(
        "core_scoped_atomic_items",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("tenant_id", Integer, nullable=False),
        Column("name", String(100), nullable=False),
        Column("version", Integer, nullable=False),
    )
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    tokens = _tokens()
    scope_calls = 0

    class ChangingScopeDataSource(SQLAlchemyCoreDataSource):
        def scoped_statement(self):
            nonlocal scope_calls
            scope_calls += 1
            tenant_id = 1 if scope_calls == 1 else 999
            return select(self._table).where(self._table.c.tenant_id == tenant_id)

    source = ChangingScopeDataSource(
        table=table,
        engine=engine,
        field_policy=ResourceFieldPolicy(
            list_fields=("id", "tenant_id", "name", "version"),
            detail_fields=("id", "tenant_id", "name", "version"),
        ),
    )
    executor = _executor(source, tokens)
    identity = _identity(1)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
            await connection.execute(
                table.insert().values(id=1, tenant_id=1, name="protected", version=1)
            )

        with pytest.raises(RakitError) as raised:
            await _execute(
                engine,
                executor,
                GeneratedCrudRequest.delete(
                    identity,
                    concurrency_token=tokens.issue("items", identity, 1),
                ),
            )
        assert raised.value.code == ErrorCode.RESOURCE_CONFLICT
        assert scope_calls == 2

        async with engine.connect() as connection:
            row = (await connection.execute(select(table))).mappings().one()
        assert dict(row) == {"id": 1, "tenant_id": 1, "name": "protected", "version": 1}
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_core_atomic_runtime_fails_closed_for_managed_input_and_missing_token() -> None:
    metadata = MetaData()
    table = _table(metadata)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    tokens = _tokens()
    source = _source(table, engine)
    executor = _executor(source, tokens)
    identity = _identity(1)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
            await connection.execute(table.insert().values(id=1, name="before", version=1))

        with pytest.raises(RakitError) as missing_token:
            await _execute(
                engine,
                executor,
                GeneratedCrudRequest.update_partial(
                    identity,
                    GeneratedInput(values={"name": "after"}, present_fields=frozenset({"name"})),
                ),
            )
        assert missing_token.value.code == ErrorCode.RESOURCE_CONFLICT

        with pytest.raises(RakitError) as managed:
            await _execute(
                engine,
                executor,
                GeneratedCrudRequest.update_partial(
                    identity,
                    GeneratedInput(
                        values={"version": 9},
                        present_fields=frozenset({"version"}),
                    ),
                    concurrency_token=tokens.issue("items", identity, 1),
                ),
            )
        assert managed.value.code == ErrorCode.CONFIG_INVALID
        assert managed.value.details["reason"] == (
            "generated_api_sqlalchemy_core_concurrency_field_writable"
        )
    finally:
        await engine.dispose()


def test_core_atomic_provider_requires_complete_runtime_pair() -> None:
    metadata = MetaData()
    table = _table(metadata)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    source = _source(table, engine)
    provider = SQLAlchemyCoreGeneratedResourceExecutorProvider(source)

    with pytest.raises(RakitError) as raised:
        provider.build(
            GeneratedResourceExecutorContext(
                resource_id="items",
                data_source=source,
                concurrency_provider=MappingVersionProvider("version"),
            )
        )
    assert raised.value.code == ErrorCode.CONFIG_INVALID
    assert raised.value.details["reason"] == "generated_api_sqlalchemy_core_concurrency_incomplete"


def test_core_atomic_rowcount_gate_fails_closed() -> None:
    metadata = MetaData()
    table = _table(metadata)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    executor = _executor(_source(table, engine), _tokens())

    class UnsaneResult:
        rowcount = 1

        @staticmethod
        def supports_sane_rowcount() -> bool:
            return False

    class MissingRowcountResult:
        rowcount = -1

        @staticmethod
        def supports_sane_rowcount() -> bool:
            return True

    with pytest.raises(RakitError) as unsane:
        executor._require_sane_atomic_rowcount(UnsaneResult())
    assert unsane.value.details["reason"] == "generated_api_sqlalchemy_core_rowcount_not_sane"

    with pytest.raises(RakitError) as unavailable:
        executor._require_sane_atomic_rowcount(MissingRowcountResult())
    assert (
        unavailable.value.details["reason"] == "generated_api_sqlalchemy_core_rowcount_unavailable"
    )
