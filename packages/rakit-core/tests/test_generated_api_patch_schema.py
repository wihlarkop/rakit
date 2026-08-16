from collections.abc import Mapping

from rakit_core.capabilities import CapabilityProvider, CapabilitySet
from rakit_core.fields import FieldDefinition
from rakit_core.generated_api import (
    ApiExposure,
    CompiledResourceApi,
    GeneratedCrudOperation,
    ResourceApiDefinition,
)
from rakit_core.generated_input import validate_generated_input
from rakit_core.schema import SchemaField


class UpdateSchema:
    pass


class DefaultExpandingSchemaAdapter:
    provider = CapabilityProvider(
        "schema.defaults",
        CapabilitySet.of(
            "schema.input-validation",
            "schema.output-serialization",
        ),
    )

    def fields(self, schema: type[object]) -> tuple[SchemaField, ...]:
        return (SchemaField("email"), SchemaField("nickname"))

    def field_names(self, schema: type[object]) -> tuple[str, ...]:
        return ("email", "nickname")

    def validate_input(self, schema: type[object], values: Mapping[str, object]) -> object:
        return dict(values)

    def serialize_output(self, schema: type[object], value: object) -> object:
        assert isinstance(value, dict)
        return {"email": "schema-default@example.com", **value}


def test_partial_update_does_not_materialize_schema_defaults_for_absent_fields() -> None:
    definition = ResourceApiDefinition(
        exposure=ApiExposure.CRUD,
        read_fields=("email", "nickname"),
        create_fields=("email", "nickname"),
        update_fields=("email", "nickname"),
        update_schema=UpdateSchema,
    )
    api = CompiledResourceApi(
        resource_id="users",
        definition=definition,
        operations=definition.operations,
        read_fields=definition.read_fields,
        create_fields=definition.create_fields,
        update_fields=definition.update_fields,
        identity_fields=("id",),
        filters=(),
    )
    fields = (
        FieldDefinition("email", str, required=True, nullable=False),
        FieldDefinition("nickname", str, nullable=True),
    )

    parsed = validate_generated_input(
        api,
        GeneratedCrudOperation.UPDATE_PARTIAL,
        {"nickname": "neo"},
        fields,
        schema_adapter=DefaultExpandingSchemaAdapter(),
    )

    assert dict(parsed.values) == {"nickname": "neo"}
    assert parsed.present_fields == frozenset({"nickname"})
