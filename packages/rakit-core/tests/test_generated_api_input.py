from collections.abc import Mapping

import pytest
from rakit_core.capabilities import CapabilityProvider, CapabilitySet
from rakit_core.errors import RakitError
from rakit_core.fields import FieldDefinition
from rakit_core.generated_api import (
    ApiExposure,
    CompiledResourceApi,
    GeneratedCrudOperation,
    ResourceApiDefinition,
)
from rakit_core.generated_input import validate_generated_input
from rakit_core.schema import SchemaField, SchemaValidationError, SchemaValidationIssue

FIELDS = (
    FieldDefinition("id", int, readable=True, writable=False),
    FieldDefinition("email", str, required=True, nullable=False),
    FieldDefinition("nickname", str, required=False, nullable=True),
    FieldDefinition("version", int, readable=True, writable=False),
)


def _compiled(*, create_schema=None, update_schema=None) -> CompiledResourceApi:
    definition = ResourceApiDefinition(
        exposure=ApiExposure.CRUD,
        read_fields=("id", "email", "nickname", "version"),
        create_fields=("email", "nickname"),
        update_fields=("email", "nickname"),
        create_schema=create_schema,
        update_schema=update_schema,
    )
    return CompiledResourceApi(
        resource_id="users",
        definition=definition,
        operations=definition.operations,
        read_fields=definition.read_fields,
        create_fields=definition.create_fields,
        update_fields=definition.update_fields,
        identity_fields=("id",),
        filters=(),
    )


def test_create_rejects_unknown_and_disallowed_fields() -> None:
    with pytest.raises(RakitError) as captured:
        validate_generated_input(
            _compiled(),
            GeneratedCrudOperation.CREATE,
            {"email": "user@example.com", "id": 10, "extra": "no"},
            FIELDS,
        )

    assert captured.value.status_code == 422
    assert captured.value.details["reason"] == "generated_api_input_fields_not_allowed"
    assert captured.value.details["fields"] == ["extra", "id"]


def test_create_requires_required_writable_fields() -> None:
    with pytest.raises(RakitError) as captured:
        validate_generated_input(
            _compiled(),
            GeneratedCrudOperation.CREATE,
            {"nickname": "neo"},
            FIELDS,
        )

    assert captured.value.details == {
        "resource_id": "users",
        "operation": "create",
        "reason": "generated_api_required_fields_missing",
        "fields": ["email"],
    }


def test_partial_update_preserves_presence_and_does_not_require_absent_fields() -> None:
    parsed = validate_generated_input(
        _compiled(),
        GeneratedCrudOperation.UPDATE_PARTIAL,
        {"nickname": "neo"},
        FIELDS,
    )

    assert dict(parsed.values) == {"nickname": "neo"}
    assert parsed.present_fields == frozenset({"nickname"})


def test_explicit_null_is_distinct_from_absent_and_respects_nullability() -> None:
    parsed = validate_generated_input(
        _compiled(),
        GeneratedCrudOperation.UPDATE_PARTIAL,
        {"nickname": None},
        FIELDS,
    )
    assert dict(parsed.values) == {"nickname": None}
    assert parsed.present_fields == frozenset({"nickname"})

    with pytest.raises(RakitError) as captured:
        validate_generated_input(
            _compiled(),
            GeneratedCrudOperation.UPDATE_PARTIAL,
            {"email": None},
            FIELDS,
        )
    assert captured.value.details["reason"] == "generated_api_null_not_allowed"
    assert captured.value.details["fields"] == ["email"]


def test_default_contract_rejects_wrong_python_value_type() -> None:
    with pytest.raises(RakitError) as captured:
        validate_generated_input(
            _compiled(),
            GeneratedCrudOperation.CREATE,
            {"email": 123},
            FIELDS,
        )
    assert captured.value.details["reason"] == "generated_api_invalid_field_type"
    assert captured.value.details["fields"] == ["email"]


class CreateSchema:
    pass


class CustomSchemaAdapter:
    provider = CapabilityProvider(
        "schema.custom",
        CapabilitySet.of(
            "schema.field-introspection",
            "schema.input-validation",
            "schema.output-serialization",
        ),
    )

    def fields(self, schema: type[object]) -> tuple[SchemaField, ...]:
        return (SchemaField("email"), SchemaField("nickname"))

    def field_names(self, schema: type[object]) -> tuple[str, ...]:
        return ("email", "nickname")

    def validate_input(self, schema: type[object], values: Mapping[str, object]) -> object:
        if values.get("email") == "bad":
            raise SchemaValidationError(
                (SchemaValidationIssue(("email",), "invalid", "Invalid email"),)
            )
        return {**values, "email": str(values["email"]).lower()}

    def serialize_output(self, schema: type[object], value: object) -> object:
        assert isinstance(value, dict)
        return value


def test_custom_schema_runs_after_field_policy_and_cannot_widen_it() -> None:
    parsed = validate_generated_input(
        _compiled(create_schema=CreateSchema),
        GeneratedCrudOperation.CREATE,
        {"email": "USER@EXAMPLE.COM"},
        FIELDS,
        schema_adapter=CustomSchemaAdapter(),
    )
    assert dict(parsed.values) == {"email": "user@example.com"}

    with pytest.raises(RakitError) as captured:
        validate_generated_input(
            _compiled(create_schema=CreateSchema),
            GeneratedCrudOperation.CREATE,
            {"email": "user@example.com", "id": 99},
            FIELDS,
            schema_adapter=CustomSchemaAdapter(),
        )
    assert captured.value.details["reason"] == "generated_api_input_fields_not_allowed"
