import pytest
from rakit_core.query import CountPolicy, PageResult, ResourceQuery, SortDirection


def test_query_appends_identity_tie_breaker() -> None:
    query = ResourceQuery.from_params(
        sort="-created_at,status",
        page=2,
        per_page=25,
        allowed_sort_fields={"created_at", "status", "id"},
        identity_fields=("id",),
    )
    assert [(item.field, item.direction) for item in query.sorting] == [
        ("created_at", SortDirection.DESC),
        ("status", SortDirection.ASC),
        ("id", SortDirection.ASC),
    ]
    assert query.pagination.offset == 25


def test_unlisted_sort_is_rejected() -> None:
    with pytest.raises(ValueError):
        ResourceQuery.from_params(
            sort="password_hash",
            allowed_sort_fields={"id"},
            identity_fields=("id",),
        )


def test_default_query_has_sensible_defaults() -> None:
    query = ResourceQuery()
    assert query.sorting == ()
    assert query.filters == ()
    assert query.search is None
    assert query.pagination.page == 1
    assert query.pagination.per_page == 25
    assert query.count_policy == CountPolicy.EXACT


def test_identity_tie_breaker_not_duplicated_when_already_sorted() -> None:
    query = ResourceQuery.from_params(
        sort="id,-created_at",
        allowed_sort_fields={"created_at", "id"},
        identity_fields=("id",),
    )
    assert [(item.field, item.direction) for item in query.sorting] == [
        ("id", SortDirection.ASC),
        ("created_at", SortDirection.DESC),
    ]


def test_empty_sort_still_appends_identity_tie_breakers() -> None:
    query = ResourceQuery.from_params(
        sort=None,
        allowed_sort_fields={"id"},
        identity_fields=("id",),
    )
    assert [(item.field, item.direction) for item in query.sorting] == [
        ("id", SortDirection.ASC),
    ]


def test_page_result_holds_arbitrary_items() -> None:
    result = PageResult(
        items=({"id": 1, "name": "Ada"},),
        page=1,
        per_page=25,
        has_previous=False,
        has_next=False,
    )
    assert result.items == ({"id": 1, "name": "Ada"},)
    assert result.total_count is None
