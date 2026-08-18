from __future__ import annotations

from urllib.parse import parse_qsl, urlsplit

from rakit_core.definitions import ResourceDefinition, ResourceFieldPolicy
from rakit_core.filters import (
    BooleanFilter,
    ChoiceFilter,
    FilterChoice,
    FilterOperator,
    NumberFilter,
    TextFilter,
)
from rakit_core.pagination import (
    CursorPageResult,
    CursorPagination,
    LimitOffsetPagination,
    LimitOffsetResult,
    PagePagination,
    PageResult,
    PageSizePolicy,
    PaginationStrategy,
    ResourcePaginationPolicy,
)
from rakit_core.query import CountPolicy, ResourceQuery, Sort
from rakit_web.resource_query_ui import (
    filter_groups,
    filter_presentations,
    page_size_options,
    pagination_controls,
    parse_resource_query,
    resource_filter_definitions,
    sort_headers,
)
from starlette.datastructures import QueryParams


def _definition(
    *,
    pagination: ResourcePaginationPolicy | None = None,
    filters=(),
) -> ResourceDefinition:
    return ResourceDefinition(
        resource_id="orders",
        path="/orders",
        label="Orders",
        singular_label="Order",
        field_policy=ResourceFieldPolicy(
            list_fields=("id", "status", "total", "active"),
            detail_fields=("id", "status", "total", "active"),
            filter_fields=("legacy",),
            search_fields=("status",),
            sort_fields=("id", "status"),
        ),
        filters=filters,
        pagination=pagination or ResourcePaginationPolicy(),
    )


def _filters():
    return (
        ChoiceFilter(
            filter_id="status",
            label="Status",
            field="status",
            choices=(
                FilterChoice(value="paid", label="Paid"),
                FilterChoice(value="pending", label="Pending"),
            ),
        ),
        BooleanFilter(filter_id="active", label="Active", field="active"),
        NumberFilter(
            filter_id="total",
            label="Total",
            field="total",
            operators=(FilterOperator.GTE, FilterOperator.LTE),
        ),
        TextFilter(
            filter_id="note",
            label="Note",
            field="status",
            operators=(FilterOperator.CONTAINS,),
        ),
    )


def test_definition_driven_groups_expose_direct_choices_and_only_approved_operators() -> None:
    definition = _definition(filters=_filters())
    query = parse_resource_query(
        definition,
        ("id",),
        QueryParams("filter=status:eq:paid&filter=active:eq:true"),
    )
    groups = filter_groups(
        query,
        (),
        "/orders",
        resource_filter_definitions(definition),
    )
    by_id = {group["filter_id"]: group for group in groups}

    status = by_id["status"]
    assert status["control"] == "choice"
    assert [choice["label"] for choice in status["choices"]] == ["Paid", "Pending"]
    assert any(choice["selected"] for choice in status["choices"])

    active = by_id["active"]
    assert active["control"] == "boolean"
    assert [choice["label"] for choice in active["choices"]] == ["Yes", "No"]

    assert [item["value"] for item in by_id["total"]["operators"]] == ["gte", "lte"]
    assert [item["value"] for item in by_id["note"]["operators"]] == ["contains"]
    assert by_id["legacy"]["control"] == "legacy"


def test_active_chip_uses_semantic_label_and_remove_url_preserves_validated_state() -> None:
    definition = _definition(filters=_filters())
    query = parse_resource_query(
        definition,
        ("id",),
        QueryParams(
            "filter=status:eq:paid&search=paid&sort=-status&per_page=50&count_policy=disabled&page=3"
        ),
    )
    explicit = (Sort(field="status", direction="desc"),)
    presentations = filter_presentations(
        query,
        explicit,
        "/orders",
        resource_filter_definitions(definition),
    )

    assert presentations[0]["chip_label"] == "Status: Paid"
    pairs = parse_qsl(urlsplit(presentations[0]["remove_url"]).query)
    assert ("search", "paid") in pairs
    assert ("sort", "-status") in pairs
    assert ("per_page", "50") in pairs
    assert ("count_policy", "disabled") in pairs
    assert not any(name == "filter" for name, _ in pairs)
    assert not any(name == "page" for name, _ in pairs)


def test_malformed_or_unknown_web_filters_are_ignored_without_widening_query() -> None:
    definition = _definition(filters=_filters())
    query = parse_resource_query(
        definition,
        ("id",),
        QueryParams("filter=secret:eq:hidden&filter=status:drop:paid&filter=status:eq:unknown"),
    )
    assert query.filters == ()
    assert query.filter_selections == ()


def test_sort_headers_advertise_sortability_without_faking_non_sortable_state() -> None:
    definition = _definition(filters=_filters())
    query = parse_resource_query(definition, ("id",), QueryParams())
    headers = sort_headers(
        ("id", "status", "total"),
        query,
        "/orders",
        (),
        {"id", "status"},
        resource_filter_definitions(definition),
    )
    by_field = {item["field"]: item for item in headers}
    assert by_field["id"]["state"] == "unsorted"
    assert by_field["id"]["sort_value"] == "id"
    assert by_field["status"]["state"] == "unsorted"
    assert by_field["total"]["state"] == "none"
    assert by_field["total"]["sort_value"] == ""


def test_page_size_policy_normalizes_disallowed_values_and_controls_show_only_allowed_sizes() -> (
    None
):
    policy = ResourcePaginationPolicy(size=PageSizePolicy(default=20, allowed=(20, 40, 80)))
    definition = _definition(pagination=policy, filters=_filters())
    query = parse_resource_query(definition, ("id",), QueryParams("per_page=17"))
    assert isinstance(query.pagination, PagePagination)
    assert query.pagination.per_page == 20
    assert [item["value"] for item in page_size_options(query, policy)] == [20, 40, 80]


def test_page_navigation_is_numbered_only_when_exact_total_is_truthful() -> None:
    definition = _definition(filters=_filters())
    definitions = resource_filter_definitions(definition)
    exact = ResourceQuery(
        pagination=PagePagination(page=2, per_page=25),
        count_policy=CountPolicy.EXACT,
    )
    exact_result = PageResult(
        items=tuple(range(25)),
        page=2,
        per_page=25,
        has_previous=True,
        has_next=True,
        total_count=80,
    )
    controls = pagination_controls(exact, exact_result, "/orders", (), definitions)
    assert controls["strategy"] == "page"
    assert controls["current_page"] == 2
    assert controls["total_pages"] == 4
    assert controls["items"]

    disabled = exact.model_copy(update={"count_policy": CountPolicy.DISABLED})
    disabled_result = PageResult(
        items=tuple(range(25)),
        page=2,
        per_page=25,
        has_previous=True,
        has_next=True,
        total_count=None,
    )
    disabled_controls = pagination_controls(disabled, disabled_result, "/orders", (), definitions)
    assert disabled_controls["total_pages"] is None
    assert disabled_controls["items"] == []


def test_limit_offset_navigation_never_fabricates_page_numbers() -> None:
    definition = _definition(
        pagination=ResourcePaginationPolicy(strategy=PaginationStrategy.LIMIT_OFFSET),
        filters=_filters(),
    )
    query = ResourceQuery(
        pagination=LimitOffsetPagination(offset=25, limit=25),
        count_policy=CountPolicy.EXACT,
    )
    result = LimitOffsetResult(
        items=tuple(range(25)),
        offset=25,
        limit=25,
        has_previous=True,
        has_next=True,
        total_count=80,
    )
    controls = pagination_controls(
        query,
        result,
        "/orders",
        (),
        resource_filter_definitions(definition),
    )
    assert controls["strategy"] == "limit_offset"
    assert controls["current_page"] is None
    assert controls["items"] == []
    assert "offset=0" in controls["previous_url"]
    assert "offset=50" in controls["next_url"]


def test_cursor_navigation_uses_only_returned_cursors_and_no_fake_totals() -> None:
    definition = _definition(
        pagination=ResourcePaginationPolicy(strategy=PaginationStrategy.CURSOR),
        filters=_filters(),
    )
    query = ResourceQuery(pagination=CursorPagination(cursor="current", limit=25))
    result = CursorPageResult(
        items=(1, 2),
        limit=25,
        previous_cursor="prev-token",
        next_cursor="next-token",
    )
    controls = pagination_controls(
        query,
        result,
        "/orders",
        (),
        resource_filter_definitions(definition),
    )
    assert controls["strategy"] == "cursor"
    assert controls["current_page"] is None
    assert controls["total_pages"] is None
    assert controls["total_count"] is None
    assert "cursor=prev-token" in controls["previous_url"]
    assert "cursor=next-token" in controls["next_url"]
