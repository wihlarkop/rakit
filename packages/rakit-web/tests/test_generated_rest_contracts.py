from datetime import UTC, datetime
from uuid import UUID

import pytest
from rakit_core.capabilities import CapabilityProvider, CapabilitySet
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.generated_api import (
    ApiExposure,
    ApiFilterDefinition,
    CompiledResourceApi,
    GeneratedCrudOperation,
    ResourceApiDefinition,
)
from rakit_core.query import FilterOperator, SortDirection
from rakit_core.schema import SchemaField
from rakit_web.generated_rest import (
    generated_error_payload,
    parse_generated_rest_query,
    serialize_generated_record,
    validate_generated_rest_payload,
)
from starlette.datastructures import QueryParams

POLICY = ResourceFieldPolicy(
    list_fields=("id", "email"),
    detail_fields=("id", "email", "status", "created_at"),
    filter_fields=("status",),
    search_fields=("email",),
    sort_fields=("email", "created_at"),
)


def _api(*, output_schema: type[object] | None = None) -> CompiledResourceApi:
    definition = ResourceApiDefinition(
        exposure=ApiExposure.CRUD,
        read_fields=("id", "email", "status", "created_at"),
        create_fields=("email",),
        update_fields=("email", "status"),
        filters=(
            ApiFilterDefinition(
                name="status",
                field="status",
                operators=(FilterOperator.EQ, FilterOperator.IN),
            ),
        ),
        output_schema=output_schema,
    )
    return CompiledResourceApi(
        resource_id="users",
        definition=definition,
        operations=definition.operations,
        read_fields=definition.read_fields,
        create_fields=definition.create_fields,
        update_fields=definition.update_fields,
        identity_fields=("id",),
        filters=definition.filters,
    )


def test_strict_query_parser_builds_resource_query_from_bracket_filters() -> None:
    query = parse_generated_rest_query(
        _api(),
        POLICY,
        QueryParams(
            "page=2&per_page=20&sort=-created_at,email&search=example.com&filter%5Bstatus%5D=active"
        ),
    )

    assert query.pagination.page == 2
    assert query.pagination.per_page == 20
    assert query.search == "example.com"
    assert [(item.field, item.direction) for item in query.sorting] == [
        ("created_at", SortDirection.DESC),
        ("email", SortDirection.ASC),
    ]
    assert [(item.field, item.operator, item.value) for item in query.filters] == [
        ("status", FilterOperator.EQ, "active")
    ]


def test_strict_query_parser_supports_declared_in_operator() -> None:
    query = parse_generated_rest_query(
        _api(),
        POLICY,
        QueryParams("filter%5Bstatus%5D%5Bin%5D=active,pending"),
    )

    assert query.filters[0].operator is FilterOperator.IN
    assert query.filters[0].value == ("active", "pending")


@pytest.mark.parametrize(
    "raw,reason",
    [
        ("unknown=value", "generated_api_query_parameter_not_allowed"),
        ("page=1&page=2", "generated_api_query_parameter_duplicated"),
        ("page=nope", "generated_api_invalid_pagination"),
        ("per_page=0", "generated_api_query_not_allowed"),
        ("sort=status", "generated_api_query_not_allowed"),
        ("filter%5Bprivate%5D=x", "generated_api_filter_not_allowed"),
        (
            "filter%5Bstatus%5D%5Bcontains%5D=act",
            "generated_api_filter_operator_not_allowed",
        ),
        ("filter%5Bstatus%5D=active&filter%5Bstatus%5D=pending", "generated_api_filter_duplicated"),
    ],
)
def test_strict_query_parser_rejects_ambiguous_or_unknown_input(raw: str, reason: str) -> None:
    with pytest.raises(RakitError) as captured:
        parse_generated_rest_query(_api(), POLICY, QueryParams(raw))

    assert captured.value.status_code == 400
    assert captured.value.details["reason"] == reason


def test_search_is_rejected_when_resource_has_no_search_surface() -> None:
    with pytest.raises(RakitError) as captured:
        parse_generated_rest_query(
            _api(),
            POLICY.model_copy(update={"search_fields": ()}),
            QueryParams("search=edo"),
        )

    assert captured.value.details["reason"] == "generated_api_search_not_allowed"


def test_json_payload_must_be_an_object_with_string_keys() -> None:
    with pytest.raises(RakitError) as captured:
        validate_generated_rest_payload(
            _api(),
            GeneratedCrudOperation.CREATE,
            ["not", "an", "object"],
            (),
        )

    assert captured.value.status_code == 400
    assert captured.value.details["reason"] == "generated_api_json_object_required"


def test_default_output_projection_is_read_field_bounded_and_json_safe() -> None:
    record = {
        "id": UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        "email": "user@example.com",
        "status": "active",
        "created_at": datetime(2026, 8, 16, 12, 30, tzinfo=UTC),
        "secret": "must-not-leak",
    }

    serialized = serialize_generated_record(_api(), record)

    assert serialized == {
        "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "email": "user@example.com",
        "status": "active",
        "created_at": "2026-08-16T12:30:00+00:00",
    }


def test_default_output_rejects_unknown_non_json_domain_objects() -> None:
    class Unsafe:
        pass

    with pytest.raises(RakitError) as captured:
        serialize_generated_record(
            _api(),
            {
                "id": 1,
                "email": "user@example.com",
                "status": Unsafe(),
                "created_at": "now",
            },
        )

    assert captured.value.details["reason"] == "generated_api_output_not_serializable"


class OutputSchema:
    pass


class OutputSchemaAdapter:
    provider = CapabilityProvider(
        "schema.output-test",
        CapabilitySet.of("schema.output-serialization"),
    )

    def fields(self, schema: type[object]) -> tuple[SchemaField, ...]:
        return ()

    def field_names(self, schema: type[object]) -> tuple[str, ...]:
        return ()

    def validate_input(self, schema: type[object], values):
        return values

    def serialize_output(self, schema: type[object], value: object) -> object:
        return {"id": 1, "email": "normalized@example.com", "secret": "no"}


def test_output_schema_cannot_widen_read_field_policy() -> None:
    with pytest.raises(RakitError) as captured:
        serialize_generated_record(
            _api(output_schema=OutputSchema),
            {"id": 1, "email": "raw@example.com", "status": "active", "created_at": "now"},
            schema_adapter=OutputSchemaAdapter(),
        )

    assert captured.value.details["reason"] == "generated_api_output_schema_widened_field_policy"


def test_error_payload_wraps_public_error_and_request_id() -> None:
    error = RakitError(
        code=ErrorCode.VALIDATION_FAILED,
        message="Invalid query",
        status_code=400,
        details={"reason": "bad"},
    )

    assert generated_error_payload(error, request_id="req-123") == {
        "error": {
            "code": "validation.failed",
            "message": "Invalid query",
            "details": {"reason": "bad"},
        },
        "request_id": "req-123",
    }
