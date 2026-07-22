from typing import Any, cast

import pytest
from rakit_core.query import (
    CountPolicy,
    Filter,
    FilterOperator,
    PageResult,
    ResourceQuery,
    SortDirection,
)


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
    ]
    assert [(item.field, item.direction) for item in query.identity_tie_breakers] == [
        ("id", SortDirection.ASC),
    ]
    assert query.pagination.offset == 25


def test_identity_tie_breaker_composes_with_narrower_sort_whitelist() -> None:
    """Regression: identity tie-breakers must not require the identity field
    to be in `allowed_sort_fields` -- they are internal stable ordering, not
    user-requested sorting, and a datasource may validate `sorting` (but not
    `identity_tie_breakers`) against a narrower `sort_fields` policy."""
    query = ResourceQuery.from_params(
        sort="name",
        allowed_sort_fields={"name"},
        identity_fields=("id",),
    )
    assert [(item.field, item.direction) for item in query.sorting] == [
        ("name", SortDirection.ASC),
    ]
    assert [(item.field, item.direction) for item in query.identity_tie_breakers] == [
        ("id", SortDirection.ASC),
    ]


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
    assert query.identity_tie_breakers == ()
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
    assert query.identity_tie_breakers == ()


def test_empty_sort_still_appends_identity_tie_breakers() -> None:
    query = ResourceQuery.from_params(
        sort=None,
        allowed_sort_fields={"id"},
        identity_fields=("id",),
    )
    assert query.sorting == ()
    assert [(item.field, item.direction) for item in query.identity_tie_breakers] == [
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


def test_filter_values_are_copied_deeply_frozen_and_still_serialize_and_compare() -> None:
    caller_value = {"groups": [["admin", "operator"]]}
    filter_ = Filter(field="metadata", operator=FilterOperator.EQ, value=caller_value)
    equivalent = Filter(
        field="metadata",
        operator=FilterOperator.EQ,
        value={"groups": (("admin", "operator"),)},
    )

    caller_value["groups"][0].append("auditor")

    assert filter_ == equivalent
    assert filter_.model_dump() == {
        "field": "metadata",
        "operator": FilterOperator.EQ,
        "value": {"groups": (("admin", "operator"),)},
    }
    assert '"auditor"' not in filter_.model_dump_json()
    frozen_value = cast(Any, filter_.value)
    with pytest.raises(TypeError, match="immutable"):
        frozen_value["groups"] = ()
    with pytest.raises(TypeError):
        frozen_value["groups"][0][0] = "owner"


def test_in_filter_sequence_is_canonical_immutable_tuple() -> None:
    caller_value = ["active", "pending"]
    filter_ = Filter(field="status", operator=FilterOperator.IN, value=caller_value)

    caller_value.append("disabled")

    assert filter_.value == ("active", "pending")
    frozen_value = cast(Any, filter_.value)
    with pytest.raises(TypeError):
        frozen_value[0] = "disabled"


def test_duplicate_sort_field_with_same_direction_is_deduplicated() -> None:
    query = ResourceQuery.from_params(
        sort="name,name",
        allowed_sort_fields={"id", "name"},
        identity_fields=("id",),
    )

    assert [(item.field, item.direction) for item in query.sorting] == [
        ("name", SortDirection.ASC),
    ]
    assert [(item.field, item.direction) for item in query.identity_tie_breakers] == [
        ("id", SortDirection.ASC),
    ]


def test_duplicate_sort_field_with_contradictory_direction_is_rejected() -> None:
    with pytest.raises(ValueError, match="Contradictory sort field"):
        ResourceQuery.from_params(
            sort="id,-id",
            allowed_sort_fields={"id"},
            identity_fields=("id",),
        )
