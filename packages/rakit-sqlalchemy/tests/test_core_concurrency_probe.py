from __future__ import annotations

from rakit_core.concurrency import AttributeVersionProvider
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.generated_runtime import GeneratedResourceExecutorContext
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

    executor = provider.build(
        GeneratedResourceExecutorContext(
            resource_id="items",
            data_source=data_source,
            concurrency_provider=AttributeVersionProvider("version"),
            concurrency_tokens=object(),  # type: ignore[arg-type]
        )
    )

    assert executor.capabilities.atomic_concurrency is True
