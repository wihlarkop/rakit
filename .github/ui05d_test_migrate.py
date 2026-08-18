from __future__ import annotations

from pathlib import Path


def replace(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text()
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"missing migration anchor in {path}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1))


# Public advanced facade: keep the historical OffsetPagination alias and expose
# the canonical page request type used by capability-aware adapters/examples.
replace(
    "packages/rakit/src/rakit/core.py",
    "    OffsetPagination,\n    PageResult,\n",
    "    OffsetPagination,\n    PagePagination,\n    PageResult,\n",
)
replace(
    "packages/rakit/src/rakit/core.py",
    '    "OffsetPagination",\n    "OperationAuthorization",\n',
    '    "OffsetPagination",\n    "PagePagination",\n    "OperationAuthorization",\n',
)

# Official relationship review fixture is page-number only.
replace(
    "examples/fastapi_sqlalchemy/relationship_review.py",
    "from rakit_core.query import PageResult, ResourceQuery\n",
    "from rakit_core.query import PagePagination, PageResult, ResourceQuery\n",
)
replace(
    "examples/fastapi_sqlalchemy/relationship_review.py",
    "        start = query.pagination.offset\n"
    "        page = visible[start : start + query.pagination.per_page]\n"
    "        return PageResult(\n"
    "            items=page,\n"
    "            page=query.pagination.page,\n"
    "            per_page=query.pagination.per_page,\n"
    "            has_previous=query.pagination.page > 1,\n",
    "        pagination = query.pagination\n"
    "        if not isinstance(pagination, PagePagination):\n"
    '            raise ValueError("Candidates supports page-number pagination only")\n'
    "        start = pagination.offset\n"
    "        page = visible[start : start + pagination.per_page]\n"
    "        return PageResult(\n"
    "            items=page,\n"
    "            page=pagination.page,\n"
    "            per_page=pagination.per_page,\n"
    "            has_previous=pagination.page > 1,\n",
)

# Core query tests now narrow the strategy before asserting page-only metadata.
replace(
    "packages/rakit-core/tests/test_query.py",
    "    PageResult,\n    ResourceQuery,\n",
    "    PagePagination,\n    PageResult,\n    ResourceQuery,\n",
)
replace(
    "packages/rakit-core/tests/test_query.py",
    "    assert [(item.field, item.direction) for item in query.identity_tie_breakers] == [\n"
    '        ("id", SortDirection.ASC),\n'
    "    ]\n"
    "    assert query.pagination.offset == 25\n",
    "    assert [(item.field, item.direction) for item in query.identity_tie_breakers] == [\n"
    '        ("id", SortDirection.ASC),\n'
    "    ]\n"
    "    assert isinstance(query.pagination, PagePagination)\n"
    "    assert query.pagination.offset == 25\n",
)
replace(
    "packages/rakit-core/tests/test_query.py",
    "    assert query.filters == ()\n"
    "    assert query.search is None\n"
    "    assert query.pagination.page == 1\n",
    "    assert query.filters == ()\n"
    "    assert query.search is None\n"
    "    assert isinstance(query.pagination, PagePagination)\n"
    "    assert query.pagination.page == 1\n",
)

# ResourceService.list() intentionally returns the strategy union; the legacy
# fake returns a PageResult, so make that expectation explicit.
replace(
    "packages/rakit-core/tests/test_resource_service.py",
    "async def test_resource_service_reads() -> None:\n"
    "    service = ResourceService(FakeDataSource())\n"
    "    assert (await service.list(ResourceQuery())).total_count == 1\n",
    "async def test_resource_service_reads() -> None:\n"
    "    service = ResourceService(FakeDataSource())\n"
    "    result = await service.list(ResourceQuery())\n"
    "    assert isinstance(result, PageResult)\n"
    "    assert result.total_count == 1\n",
)

# Reusable contract-suite fakes are page-only by design.
replace(
    "packages/rakit-core/tests/testing/test_datasource_contract.py",
    "    FilterOperator,\n    PageResult,\n",
    "    FilterOperator,\n    PagePagination,\n    PageResult,\n",
)
replace(
    "packages/rakit-core/tests/testing/test_datasource_contract.py",
    "    async def list(self, query: ResourceQuery) -> PageResult:\n"
    "        rows = self._sorted(self._filtered(query), query)\n"
    "        offset = query.pagination.offset\n"
    "        per_page = query.pagination.per_page\n",
    "    async def list(self, query: ResourceQuery) -> PageResult:\n"
    "        rows = self._sorted(self._filtered(query), query)\n"
    "        pagination = query.pagination\n"
    "        if not isinstance(pagination, PagePagination):\n"
    '            raise ValueError("MemoryDataSource supports page-number pagination only")\n'
    "        offset = pagination.offset\n"
    "        per_page = pagination.per_page\n",
)
replace(
    "packages/rakit-core/tests/testing/test_datasource_contract.py",
    "            page=query.pagination.page,\n"
    "            per_page=per_page,\n"
    "            has_previous=query.pagination.page > 1,\n",
    "            page=pagination.page,\n"
    "            per_page=per_page,\n"
    "            has_previous=pagination.page > 1,\n",
)
replace(
    "packages/rakit-core/tests/testing/test_datasource_contract.py",
    "    async def list(self, query: ResourceQuery) -> PageResult:\n"
    "        page = query.pagination.page\n"
    "        per_page = query.pagination.per_page\n",
    "    async def list(self, query: ResourceQuery) -> PageResult:\n"
    "        pagination = query.pagination\n"
    "        if not isinstance(pagination, PagePagination):\n"
    '            raise ValueError("BrokenDataSource supports page-number pagination only")\n'
    "        page = pagination.page\n"
    "        per_page = pagination.per_page\n",
)
replace(
    "packages/rakit-core/tests/testing/test_datasource_contract.py",
    "        offset = query.pagination.offset\n"
    "        items = tuple(rows[offset : offset + per_page])\n",
    "        offset = pagination.offset\n"
    "        items = tuple(rows[offset : offset + per_page])\n",
)

# Generated query fixtures now use the normalized compiled filter contract.
replace(
    "packages/rakit-core/tests/test_generated_api_query.py",
    "    ApiFilterDefinition,\n    CompiledResourceApi,\n",
    "    ApiFilterDefinition,\n    CompiledApiFilterDefinition,\n    CompiledResourceApi,\n",
)
replace(
    "packages/rakit-core/tests/test_generated_api_query.py",
    "from rakit_core.generated_query import GeneratedFilterValue, build_generated_resource_query\n"
    "from rakit_core.query import FilterOperator, SortDirection\n",
    "from rakit_core.filters import LegacyFieldFilter\n"
    "from rakit_core.generated_query import GeneratedFilterValue, build_generated_resource_query\n"
    "from rakit_core.query import FilterOperator, PagePagination, SortDirection\n",
)
replace(
    "packages/rakit-core/tests/test_generated_api_query.py",
    "    return CompiledResourceApi(\n"
    '        resource_id="users",\n'
    "        definition=definition,\n"
    "        operations=definition.operations,\n"
    "        read_fields=definition.read_fields,\n"
    "        create_fields=(),\n"
    "        update_fields=(),\n"
    '        identity_fields=("id",),\n'
    "        filters=definition.filters,\n"
    "    )\n",
    "    filter_definition = LegacyFieldFilter(\n"
    '        filter_id="status",\n'
    '        label="Status",\n'
    '        field="status",\n'
    "        operators=(FilterOperator.EQ, FilterOperator.IN),\n"
    "        strip_in_values=True,\n"
    "    )\n"
    "    return CompiledResourceApi(\n"
    '        resource_id="users",\n'
    "        definition=definition,\n"
    "        operations=definition.operations,\n"
    "        read_fields=definition.read_fields,\n"
    "        create_fields=(),\n"
    "        update_fields=(),\n"
    '        identity_fields=("id",),\n'
    "        filters=(\n"
    "            CompiledApiFilterDefinition(\n"
    '                name="status",\n'
    "                filter=filter_definition,\n"
    "                operators=filter_definition.operators,\n"
    "            ),\n"
    "        ),\n"
    "    )\n",
)
replace(
    "packages/rakit-core/tests/test_generated_api_query.py",
    "    assert tuple(item.field for item in query.identity_tie_breakers) == (\"id\",)\n"
    "    assert query.pagination.page == 2\n",
    "    assert tuple(item.field for item in query.identity_tie_breakers) == (\"id\",)\n"
    "    assert isinstance(query.pagination, PagePagination)\n"
    "    assert query.pagination.page == 2\n",
)
