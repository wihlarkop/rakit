import pytest
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.errors import RakitError
from rakit_core.generated_api import (
    ApiExposure,
    ApiFilterDefinition,
    CompiledResourceApi,
    ResourceApiDefinition,
)
from rakit_core.generated_query import GeneratedFilterValue, build_generated_resource_query
from rakit_core.query import FilterOperator, SortDirection


def _compiled() -> CompiledResourceApi:
    definition = ResourceApiDefinition(
        exposure=ApiExposure.READ_ONLY,
        read_fields=("id", "email", "status", "created_at"),
        filters=(
            ApiFilterDefinition(
                name="status",
                field="status",
                operators=(FilterOperator.EQ, FilterOperator.IN),
            ),
        ),
    )
    return CompiledResourceApi(
        resource_id="users",
        definition=definition,
        operations=definition.operations,
        read_fields=definition.read_fields,
        create_fields=(),
        update_fields=(),
        identity_fields=("id",),
        filters=definition.filters,
    )


POLICY = ResourceFieldPolicy(
    list_fields=("id", "email"),
    detail_fields=("id", "email", "status", "created_at"),
    filter_fields=("status",),
    search_fields=("email",),
    sort_fields=("email", "created_at"),
)


def test_query_projection_reuses_resource_query_and_stable_identity_ordering() -> None:
    query = build_generated_resource_query(
        _compiled(),
        POLICY,
        sort="-created_at,email",
        page=2,
        per_page=20,
        search="  example.com  ",
        filters=(GeneratedFilterValue("status", FilterOperator.EQ, "active"),),
    )

    assert [(item.field, item.direction) for item in query.sorting] == [
        ("created_at", SortDirection.DESC),
        ("email", SortDirection.ASC),
    ]
    assert tuple(item.field for item in query.identity_tie_breakers) == ("id",)
    assert query.pagination.page == 2
    assert query.pagination.per_page == 20
    assert query.search == "example.com"
    assert [(item.field, item.operator, item.value) for item in query.filters] == [
        ("status", FilterOperator.EQ, "active")
    ]


def test_query_projection_rejects_unknown_filter_name() -> None:
    with pytest.raises(RakitError) as captured:
        build_generated_resource_query(
            _compiled(),
            POLICY,
            filters=(GeneratedFilterValue("private", FilterOperator.EQ, "x"),),
        )

    assert captured.value.status_code == 400
    assert captured.value.details["reason"] == "generated_api_filter_not_allowed"


def test_query_projection_rejects_operator_not_declared_for_filter() -> None:
    with pytest.raises(RakitError) as captured:
        build_generated_resource_query(
            _compiled(),
            POLICY,
            filters=(GeneratedFilterValue("status", FilterOperator.CONTAINS, "act"),),
        )

    assert captured.value.details["reason"] == "generated_api_filter_operator_not_allowed"


def test_query_projection_reuses_sort_whitelist() -> None:
    with pytest.raises(RakitError) as captured:
        build_generated_resource_query(_compiled(), POLICY, sort="status")

    assert captured.value.status_code == 400
    assert captured.value.details["reason"] == "generated_api_query_not_allowed"
