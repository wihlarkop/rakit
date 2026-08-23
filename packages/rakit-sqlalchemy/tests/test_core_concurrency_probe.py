from __future__ import annotations

from rakit_core.concurrency import ConcurrencyTokenService
from rakit_core.config import SecretValue
from rakit_core.crypto import TokenService
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.generated_runtime import GeneratedResourceExecutorContext
from rakit_sqlalchemy.core_concurrency import MappingVersionProvider
from rakit_sqlalchemy.core_datasource import SQLAlchemyCoreDataSource
from rakit_sqlalchemy.core_generated import SQLAlchemyCoreGeneratedResourceExecutorProvider
from sqlalchemy import Column, Integer, MetaData, String, Table
from sqlalchemy.ext.asyncio import create_async_engine


def test_core_generated_executor_accepts_complete_concurrency_runtime() -> None:
    metadata = MetaData()
    items = Table(
        "core_concurrency_probe",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String(100), nullable=False),
        Column("version", Integer, nullable=False),
    )
    policy = ResourceFieldPolicy(
        list_fields=("id", "name", "version"),
        detail_fields=("id", "name", "version"),
        sort_fields=("name",),
    )
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    data_source = SQLAlchemyCoreDataSource(table=items, engine=engine, field_policy=policy)
    provider = SQLAlchemyCoreGeneratedResourceExecutorProvider(data_source=data_source)
    token_service = ConcurrencyTokenService(
        TokenService.single_key(
            key_id="test",
            value=SecretValue("core-concurrency-probe-secret"),
            admin_id="test",
        )
    )
    concurrency_provider = MappingVersionProvider("version")

    executor = provider.build(
        GeneratedResourceExecutorContext(
            resource_id="items",
            data_source=data_source,
            concurrency_provider=concurrency_provider,
            concurrency_tokens=token_service,
        )
    )

    assert concurrency_provider.version_for({"version": 1}) == 1
    assert concurrency_provider.predicate_values_for({"version": 1}) == {"version": 1}
    assert concurrency_provider.next_values_for({"version": 1}) == {"version": 2}
    assert executor.capabilities.atomic_concurrency is True
