from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from rakit_core.compiler import ApplicationBuilder
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.filters import Filter, FilterOperator
from rakit_core.pagination import LimitOffsetPagination, LimitOffsetResult, PageResult
from rakit_core.query import CountPolicy, ResourceQuery
from rakit_sqlalchemy.core_datasource import SQLAlchemyCoreDataSource
from rakit_sqlalchemy.core_plugin import SQLAlchemyCorePlugin
from sqlalchemy import Column, Integer, MetaData, String, Table
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

metadata = MetaData()
items = Table(
    "core_items",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(100), nullable=False),
    Column("score", Integer, nullable=True),
)


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    value = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with value.begin() as connection:
        await connection.run_sync(metadata.create_all)
        await connection.execute(
            items.insert(),
            [
                {"id": 1, "name": "Beta", "score": 20},
                {"id": 2, "name": "Alpha", "score": 10},
                {"id": 3, "name": "Alphabet", "score": None},
            ],
        )
    yield value
    await value.dispose()


def _policy() -> ResourceFieldPolicy:
    return ResourceFieldPolicy(
        list_fields=("id", "name", "score"),
        detail_fields=("id", "name", "score"),
        filter_fields=("name", "score"),
        search_fields=("name",),
        sort_fields=("name", "score"),
    )


@pytest.mark.anyio
async def test_core_plugin_claims_native_table_with_resource_owned_uow(engine) -> None:
    builder = ApplicationBuilder()
    plugin = SQLAlchemyCorePlugin(engine=engine)
    builder.install(plugin)

    runtime = plugin._claim(items, _policy())

    assert runtime is not None
    assert runtime.unit_of_work_provider_id == "persistence.sqlalchemy-core"
    assert runtime.generated_executor_provider is not None
    providers = {provider.provider_id: provider for provider in builder.capability_providers}
    assert tuple(providers) == ("persistence.sqlalchemy-core",)
    assert providers["persistence.sqlalchemy-core"].capabilities.names == (
        "persistence.read",
        "persistence.write",
        "transactions.root-uow",
    )
    assert tuple(dict(builder.unit_of_work_factories)) == ("persistence.sqlalchemy-core",)
    assert plugin._claim(object(), _policy()) is None


@pytest.mark.anyio
async def test_core_table_read_supports_page_filter_search_sort_and_detail(
    engine,
) -> None:
    plugin = SQLAlchemyCorePlugin(engine=engine)
    runtime = plugin._claim(items, _policy())
    assert runtime is not None
    source = runtime.data_source
    assert isinstance(source, SQLAlchemyCoreDataSource)

    assert source.fields == ("id", "name", "score")
    assert source.identity_fields == ("id",)

    page = await source.list(
        ResourceQuery.from_params(
            sort="name",
            page=1,
            per_page=2,
            allowed_sort_fields=("name", "score"),
            identity_fields=("id",),
            filters=(Filter(field="score", operator=FilterOperator.GTE, value="10"),),
            search="a",
        )
    )
    assert isinstance(page, PageResult)
    assert page.items == (
        {"id": 2, "name": "Alpha", "score": 10},
        {"id": 1, "name": "Beta", "score": 20},
    )
    assert page.total_count == 2
    assert page.has_next is False

    detail = await source.detail(source.identity_for(page.items[0]))
    assert detail == {"id": 2, "name": "Alpha", "score": 10}


@pytest.mark.anyio
async def test_core_table_read_supports_limit_offset_and_deferred_count(engine) -> None:
    plugin = SQLAlchemyCorePlugin(engine=engine)
    runtime = plugin._claim(items, _policy())
    assert runtime is not None
    source = runtime.data_source
    assert isinstance(source, SQLAlchemyCoreDataSource)

    result = await source.list(
        ResourceQuery.from_components(
            sort="-score",
            pagination=LimitOffsetPagination(offset=1, limit=1),
            allowed_sort_fields=("name", "score"),
            identity_fields=("id",),
            count_policy=CountPolicy.DEFERRED,
        )
    )

    assert isinstance(result, LimitOffsetResult)
    assert result.items == ({"id": 2, "name": "Alpha", "score": 10},)
    assert result.total_count is None
    assert result.has_previous is True
    assert result.has_next is True
    assert await source.count(ResourceQuery()) == 3
