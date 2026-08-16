from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from .errors import ErrorCode, RakitError
from .fields import FieldDefinition
from .generated_api import CompiledResourceApi, GeneratedCrudOperation
from .schema import SchemaAdapter, SchemaValidationError


@dataclass(frozen=True, slots=True)
class GeneratedInput:
    values: Mapping[str, object]
    present_fields: frozenset[str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))
        object.__setattr__(self, "present_fields", frozenset(self.present_fields))


def _input_error(
    api: CompiledResourceApi,
    operation: GeneratedCrudOperation,
    reason: str,
    fields: list[str],
) -> RakitError:
    return RakitError(
        code=ErrorCode.VALIDATION_FAILED,
        message="Generated API input validation failed.",
        status_code=422,
        details={
            "resource_id": api.resource_id,
            "operation": operation.value,
            "reason": reason,
            "fields": sorted(fields),
        },
    )


def _allowed_fields(api: CompiledResourceApi, operation: GeneratedCrudOperation) -> tuple[str, ...]:
    if operation is GeneratedCrudOperation.CREATE:
        return api.create_fields
    if operation is GeneratedCrudOperation.UPDATE_PARTIAL:
        return api.update_fields
    raise ValueError("Generated input is supported only for create and partial update")


def _schema_for(api: CompiledResourceApi, operation: GeneratedCrudOperation) -> type[object] | None:
    if operation is GeneratedCrudOperation.CREATE:
        return api.definition.create_schema
    if operation is GeneratedCrudOperation.UPDATE_PARTIAL:
        return api.definition.update_schema
    return None


def _value_matches_type(value: object, expected: type[object]) -> bool:
    if expected is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if expected is float:
        return isinstance(value, int | float) and not isinstance(value, bool)
    return isinstance(value, expected)


def validate_generated_input(
    api: CompiledResourceApi,
    operation: GeneratedCrudOperation,
    submitted: Mapping[str, object],
    field_definitions: tuple[FieldDefinition, ...],
    *,
    schema_adapter: SchemaAdapter | None = None,
) -> GeneratedInput:
    allowed = set(_allowed_fields(api, operation))
    submitted_fields = set(submitted)
    disallowed = submitted_fields.difference(allowed)
    if disallowed:
        raise _input_error(
            api,
            operation,
            "generated_api_input_fields_not_allowed",
            list(disallowed),
        )

    definitions = {field.field_id: field for field in field_definitions}
    missing_definitions = allowed.difference(definitions)
    if missing_definitions:
        raise _input_error(
            api,
            operation,
            "generated_api_field_metadata_missing",
            list(missing_definitions),
        )

    if operation is GeneratedCrudOperation.CREATE:
        required = {
            field_name
            for field_name in allowed
            if definitions[field_name].required and not definitions[field_name].nullable
        }
        missing = required.difference(submitted_fields)
        if missing:
            raise _input_error(
                api,
                operation,
                "generated_api_required_fields_missing",
                list(missing),
            )

    null_not_allowed = {
        field_name
        for field_name, value in submitted.items()
        if value is None and not definitions[field_name].nullable
    }
    if null_not_allowed:
        raise _input_error(
            api,
            operation,
            "generated_api_null_not_allowed",
            list(null_not_allowed),
        )

    values: Mapping[str, object] = dict(submitted)
    schema = _schema_for(api, operation)
    if schema is not None:
        if schema_adapter is None:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Generated API custom input schema requires a schema adapter.",
                status_code=500,
                details={
                    "resource_id": api.resource_id,
                    "operation": operation.value,
                    "reason": "generated_api_schema_adapter_missing",
                },
            )
        try:
            validated = schema_adapter.validate_input(schema, values)
            serialized = schema_adapter.serialize_output(schema, validated)
        except SchemaValidationError as exc:
            fields = sorted({issue.location[0] for issue in exc.issues if issue.location})
            raise _input_error(
                api,
                operation,
                "generated_api_schema_validation_failed",
                fields,
            ) from exc
        if not isinstance(serialized, Mapping):
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Generated API schema serialization must produce a mapping.",
                status_code=500,
                details={
                    "resource_id": api.resource_id,
                    "operation": operation.value,
                    "reason": "generated_api_schema_output_not_mapping",
                },
            )
        widened = set(serialized).difference(allowed)
        if widened:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Generated API schema widened the configured field policy.",
                status_code=500,
                details={
                    "resource_id": api.resource_id,
                    "operation": operation.value,
                    "reason": "generated_api_schema_widened_field_policy",
                    "fields": sorted(widened),
                },
            )
        values = dict(serialized)
    else:
        invalid_types = [
            field_name
            for field_name, value in values.items()
            if value is not None
            and not _value_matches_type(value, definitions[field_name].python_type)
        ]
        if invalid_types:
            raise _input_error(
                api,
                operation,
                "generated_api_invalid_field_type",
                invalid_types,
            )

    return GeneratedInput(values=values, present_fields=frozenset(submitted_fields))


__all__ = ["GeneratedInput", "validate_generated_input"]
