from __future__ import annotations

import asyncio

from rakit_core.compiler import ApplicationBuilder, compile_application
from rakit_core.definitions import ResourceDefinition, ResourceFieldPolicy
from rakit_core.generated_api import ApiExposure, ResourceApiDefinition
from rakit_sqlalchemy.core_plugin import SQLAlchemyCorePlugin
from sqlalchemy import Column, Integer, MetaData, String, Table
from sqlalchemy.ext.asyncio import create_async_engine

metadata = MetaData()
items = Table(
    "core_generated_compile_items",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(100), nullable=False),
)

POLICY = ResourceFieldPolicy(
    list_fields=("id", "name"),
    detail_fields=("id", "name"),
)


def test_core_table_generated_crud_compiles_with_resource_owned_uow() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        builder = ApplicationBuilder()
        plugin = SQLAlchemyCorePlugin(engine=engine)
        builder.install(plugin)
        runtime = plugin._claim(items, POLICY)
        assert runtime is not None
        assert runtime.generated_executor_provider is not None
        assert runtime.unit_of_work_provider_id == "persistence.sqlalchemy-core"

        builder.add_resource(
            ResourceDefinition(
                resource_id="items",
                path="/items",
                label="Items",
                singular_label="Item",
                field_policy=POLICY,
                api=ResourceApiDefinition(
                    exposure=ApiExposure.CRUD,
                    read_fields=("id", "name"),
                    create_fields=("name",),
                    update_fields=("name",),
                ),
            ),
            runtime.data_source,
            generated_executor_provider=runtime.generated_executor_provider,
            unit_of_work_provider_id=runtime.unit_of_work_provider_id,
        )

        compiled = compile_application(builder)

        assert tuple(
            requirement.requirement_id for requirement in compiled.capability_requirements
        ) == ("generated-api:items:write",)
        report = compiled.capability_reports[0]
        assert report.requirement.requirement_id == "generated-api:items:write"
        assert report.satisfied is True
        assert report.missing.names == ()
        assert dict(compiled.resource_unit_of_work_provider_ids) == {
            "items": "persistence.sqlalchemy-core"
        }
        assert "items" in dict(compiled.generated_resource_executor_providers)
        assert "persistence.sqlalchemy-core" in dict(compiled.unit_of_work_factories)
        assert tuple(item.integration_id for item in compiled.configured_integrations) == (
            "persistence.sqlalchemy-core",
        )
    finally:
        asyncio.run(engine.dispose())
