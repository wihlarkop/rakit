from typing import cast
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from rakit_core.datasource import DataSourceCapabilities
from rakit_core.definitions import ResourceDefinition, ResourceFieldPolicy
from rakit_core.filters import LegacyFieldFilter
from rakit_core.identity import RecordIdentity
from rakit_core.query import CountPolicy, PagePagination, PageResult, ResourceQuery
from rakit_core.resources import ResourceService
from rakit_web.resource_query_ui import builder_selections
from rakit_web.resource_routes import (
    ResourceBinding,
    build_resource_routes,
    build_templates,
)
from starlette.applications import Starlette
from starlette.datastructures import QueryParams
from starlette.types import ASGIApp


class _DataSource:
    capabilities = DataSourceCapabilities(read=True)
    fields = ("id", "name", "status", "optional")
    identity_fields = ("id",)

    def __init__(self, *, empty: bool = False) -> None:
        self._items = (
            ()
            if empty
            else tuple(
                {
                    "id": index,
                    "name": f"Order {index:03d}",
                    "status": "pending" if index % 2 else "paid",
                    "optional": None if index == 1 else "present",
                }
                for index in range(1, 61)
            )
        )

    async def list(self, query: ResourceQuery) -> PageResult[dict[str, object]]:
        items = list(self._items)
        if query.search:
            needle = query.search.casefold()
            items = [item for item in items if needle in str(item["name"]).casefold()]
        for filter_ in query.filters:
            if filter_.operator.value == "eq":
                items = [
                    item for item in items if str(item.get(filter_.field)) == str(filter_.value)
                ]
        pagination = query.pagination
        if not isinstance(pagination, PagePagination):
            raise ValueError("_DataSource supports page-number pagination only")
        start = pagination.offset
        end = start + pagination.per_page
        page_items = tuple(items[start:end])
        return PageResult(
            items=page_items,
            page=pagination.page,
            per_page=pagination.per_page,
            has_previous=pagination.page > 1,
            has_next=end < len(items),
            total_count=len(items) if query.count_policy is CountPolicy.EXACT else None,
        )

    async def count(self, query: ResourceQuery) -> int:
        page = await self.list(query.model_copy(update={"count_policy": CountPolicy.EXACT}))
        assert page.total_count is not None
        return page.total_count

    async def detail(self, identity: RecordIdentity) -> object:
        wanted = int(cast(int | str, identity.values["id"]))
        return next(item for item in self._items if item["id"] == wanted)

    def identity_for(self, record: object) -> RecordIdentity:
        assert isinstance(record, dict)
        value = cast(dict[str, object], record)["id"]
        assert isinstance(value, int | str) and not isinstance(value, bool)
        return RecordIdentity(values={"id": value})


def _app(*, empty: bool = False, resource_id: str = "orders", label: str = "Orders") -> ASGIApp:
    definition = ResourceDefinition(
        resource_id=resource_id,
        path=f"/{resource_id}",
        label=label,
        singular_label=label.removesuffix("s"),
        field_policy=ResourceFieldPolicy(
            list_fields=("id", "name", "status", "optional"),
            detail_fields=("id", "name", "status", "optional"),
            filter_fields=("status", "optional"),
            search_fields=("name",),
            sort_fields=("id", "name", "status"),
        ),
    )
    service = ResourceService(_DataSource(empty=empty))
    binding = ResourceBinding(definition=definition, service=service, templates=build_templates(()))
    return Starlette(routes=build_resource_routes(binding))


@pytest.mark.anyio
async def test_filter_builder_redirects_to_canonical_validated_query() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        response = await client.get(
            "/orders",
            params={
                "filter_field": "status",
                "filter_operator": "eq",
                "filter_value": "pending",
                "search": "Order",
                "sort": "-name",
                "per_page": "50",
                "page": "3",
            },
        )

    assert response.status_code == 303
    location = response.headers["location"]
    parsed = urlsplit(location)
    query = parse_qs(parsed.query)
    assert parsed.path == "/orders"
    assert query["filter"] == ["status:eq:pending"]
    assert query["search"] == ["Order"]
    assert query["sort"] == ["-name"]
    assert query["per_page"] == ["50"]
    assert "page" not in query
    assert "filter_field" not in query
    assert "filter_operator" not in query
    assert "filter_value" not in query


def test_filter_builder_rejects_unapproved_or_malformed_state() -> None:
    definitions = (
        LegacyFieldFilter(
            filter_id="status",
            label="Status",
            field="status",
        ),
    )
    assert (
        builder_selections(
            QueryParams("filter_field=secret&filter_operator=eq&filter_value=value"),
            definitions,
        )
        == ()
    )
    assert (
        builder_selections(
            QueryParams("filter_field=status&filter_operator=eq"),
            definitions,
        )
        == ()
    )
    assert (
        builder_selections(
            QueryParams("filter_field=status&filter_operator=is_null&filter_value=maybe"),
            definitions,
        )
        == ()
    )


@pytest.mark.anyio
async def test_search_and_active_filters_render_validated_server_state() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/orders",
            params=[
                ("search", "Order"),
                ("filter", "status:eq:pending"),
                ("sort", "-name"),
                ("per_page", "50"),
            ],
        )

    assert response.status_code == 200
    assert 'role="search"' in response.text
    assert 'aria-label="Search Orders"' in response.text
    assert ">Search</button>" not in response.text
    assert 'data-rakit-filter-ui="orders"' in response.text
    assert "data-rakit-filter-rail" in response.text
    assert 'data-rakit-filter-group="status"' in response.text
    assert "data-rakit-filter-panel" not in response.text
    assert "Status = pending" in response.text
    assert "Clear all filters" in response.text
    assert 'aria-label="Clear search"' in response.text
    assert 'name="filter" value="status:eq:pending"' in response.text
    assert 'name="sort" value="-name"' in response.text
    assert 'name="per_page" value="50"' in response.text


@pytest.mark.anyio
async def test_invalid_canonical_filter_is_not_reflected_as_active_state() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()),
        base_url="http://test",
    ) as client:
        response = await client.get("/orders", params={"filter": "secret:eq:hidden"})

    assert response.status_code == 200
    assert "Filters 1" not in response.text
    assert "secret equals hidden" not in response.text
    assert "data-rakit-active-filters" not in response.text


@pytest.mark.anyio
async def test_exact_count_pagination_renders_range_numbered_pages_and_policy_size() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()),
        base_url="http://test",
    ) as client:
        page_two = await client.get("/orders", params={"page": "2", "per_page": "25"})
        custom = await client.get("/orders", params={"per_page": "17"})

    assert page_two.status_code == 200
    assert "Showing 26\u201350 of 60" in page_two.text
    assert 'aria-current="page">2</a>' in page_two.text
    assert ">1</a>" in page_two.text
    assert ">3</a>" in page_two.text
    assert 'aria-label="Previous results"' in page_two.text
    assert 'aria-label="Next results"' in page_two.text

    assert custom.status_code == 200
    assert '<option value="17"' not in custom.text
    assert '<option value="25" selected>25</option>' in custom.text
    for size in (50, 100):
        assert f'<option value="{size}">{size}</option>' in custom.text


@pytest.mark.anyio
async def test_non_exact_count_does_not_fabricate_numbered_total_pages() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()),
        base_url="http://test",
    ) as client:
        deferred = await client.get(
            "/orders",
            params={"page": "2", "per_page": "25", "count_policy": "deferred"},
        )
        disabled = await client.get(
            "/orders",
            params={"page": "2", "per_page": "25", "count_policy": "disabled"},
        )

    assert deferred.status_code == 200
    assert "Page 2 · total calculating" in deferred.text
    assert "data-rakit-total-deferred" in deferred.text
    assert "Calculating" in deferred.text
    assert 'aria-current="page">2</span>' in deferred.text

    assert disabled.status_code == 200
    assert "Page 2 · total unavailable" in disabled.text
    assert "Total unavailable" in disabled.text
    assert 'aria-current="page">2</span>' in disabled.text


@pytest.mark.anyio
async def test_resource_list_distinguishes_missing_value_empty_and_no_results() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()),
        base_url="http://test",
    ) as client:
        normal = await client.get("/orders")
        no_results = await client.get("/orders", params={"search": "does-not-exist"})

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(empty=True, resource_id="returns", label="Returns")),
        base_url="http://test",
    ) as client:
        empty = await client.get("/returns")

    assert normal.status_code == 200
    assert "—" in normal.text
    assert "No matching orders" in no_results.text
    assert "Try changing your search or removing filters." in no_results.text
    assert "No returns yet" in empty.text
    assert "Records will appear here when they are available." in empty.text


@pytest.mark.anyio
async def test_sorting_and_page_size_forms_preserve_validated_state_without_page() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/orders",
            params=[
                ("filter", "status:eq:pending"),
                ("search", "Order"),
                ("sort", "name"),
                ("per_page", "50"),
                ("page", "2"),
            ],
        )

    assert response.status_code == 200
    assert 'aria-sort="ascending"' in response.text
    assert 'form="rakit-sort-orders"' in response.text
    assert "data-rakit-page-size" in response.text
    assert 'name="filter" value="status:eq:pending"' in response.text
    assert 'name="search" value="Order"' in response.text
    assert 'name="sort" value="name"' in response.text
    assert 'name="page"' not in response.text
