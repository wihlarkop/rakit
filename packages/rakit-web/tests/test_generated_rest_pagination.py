import pytest
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.errors import RakitError
from rakit_core.generated_api import ApiExposure, CompiledResourceApi, ResourceApiDefinition
from rakit_core.pagination import (
    CursorPagination,
    LimitOffsetPagination,
    PagePagination,
    PageSizePolicy,
    PaginationStrategy,
    ResourcePaginationPolicy,
)
from rakit_web.generated_rest import parse_generated_rest_query
from starlette.datastructures import QueryParams

POLICY = ResourceFieldPolicy(
    list_fields=("id", "name"),
    detail_fields=("id", "name"),
    search_fields=("name",),
    sort_fields=("id", "name"),
)


def _api(strategy: PaginationStrategy) -> CompiledResourceApi:
    definition = ResourceApiDefinition(
        exposure=ApiExposure.READ_ONLY,
        read_fields=("id", "name"),
    )
    return CompiledResourceApi(
        resource_id="records",
        definition=definition,
        operations=definition.operations,
        read_fields=definition.read_fields,
        create_fields=(),
        update_fields=(),
        identity_fields=("id",),
        filters=(),
        pagination=ResourcePaginationPolicy(
            strategy=strategy,
            size=PageSizePolicy(default=20, allowed=(20, 40, 80)),
        ),
    )


def test_generated_rest_page_strategy_accepts_only_page_parameters() -> None:
    query = parse_generated_rest_query(
        _api(PaginationStrategy.PAGE),
        POLICY,
        QueryParams("page=2&per_page=40&sort=-name&search=a"),
    )
    assert isinstance(query.pagination, PagePagination)
    assert query.pagination.page == 2
    assert query.pagination.per_page == 40

    for raw in ("offset=20", "limit=20", "cursor=opaque"):
        with pytest.raises(RakitError) as captured:
            parse_generated_rest_query(_api(PaginationStrategy.PAGE), POLICY, QueryParams(raw))
        assert captured.value.details["reason"] == "generated_api_query_parameter_not_allowed"


def test_generated_rest_limit_offset_strategy_is_strict_and_truthful() -> None:
    query = parse_generated_rest_query(
        _api(PaginationStrategy.LIMIT_OFFSET),
        POLICY,
        QueryParams("offset=20&limit=40"),
    )
    assert isinstance(query.pagination, LimitOffsetPagination)
    assert query.pagination.offset == 20
    assert query.pagination.limit == 40

    for raw in ("page=2", "per_page=20", "cursor=opaque"):
        with pytest.raises(RakitError) as captured:
            parse_generated_rest_query(
                _api(PaginationStrategy.LIMIT_OFFSET), POLICY, QueryParams(raw)
            )
        assert captured.value.details["reason"] == "generated_api_query_parameter_not_allowed"


def test_generated_rest_cursor_strategy_accepts_only_cursor_navigation() -> None:
    query = parse_generated_rest_query(
        _api(PaginationStrategy.CURSOR),
        POLICY,
        QueryParams("cursor=opaque-next&limit=20"),
    )
    assert isinstance(query.pagination, CursorPagination)
    assert query.pagination.cursor == "opaque-next"
    assert query.pagination.limit == 20

    for raw in ("page=2", "per_page=20", "offset=20"):
        with pytest.raises(RakitError) as captured:
            parse_generated_rest_query(_api(PaginationStrategy.CURSOR), POLICY, QueryParams(raw))
        assert captured.value.details["reason"] == "generated_api_query_parameter_not_allowed"

    with pytest.raises(RakitError) as captured:
        parse_generated_rest_query(
            _api(PaginationStrategy.CURSOR), POLICY, QueryParams("cursor=&limit=20")
        )
    assert captured.value.details["reason"] == "generated_api_invalid_pagination"


def test_generated_rest_rejects_page_sizes_outside_resource_policy() -> None:
    for strategy, raw in (
        (PaginationStrategy.PAGE, "per_page=25"),
        (PaginationStrategy.LIMIT_OFFSET, "limit=25"),
        (PaginationStrategy.CURSOR, "limit=25"),
    ):
        with pytest.raises(RakitError) as captured:
            parse_generated_rest_query(_api(strategy), POLICY, QueryParams(raw))
        assert captured.value.details["reason"] == "generated_api_invalid_pagination"
