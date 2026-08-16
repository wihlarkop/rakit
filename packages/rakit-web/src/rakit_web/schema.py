from collections.abc import Mapping

from pydantic import BaseModel, ValidationError
from rakit_core.adapter_capabilities import (
    SCHEMA_FIELD_INTROSPECTION,
    SCHEMA_INPUT_VALIDATION,
    SCHEMA_OUTPUT_SERIALIZATION,
)
from rakit_core.capabilities import CapabilityProvider, CapabilitySet
from rakit_core.schema import SchemaValidationError, SchemaValidationIssue

PYDANTIC_SCHEMA_CAPABILITIES = CapabilityProvider(
    provider_id="schema.pydantic",
    capabilities=CapabilitySet.of(
        SCHEMA_FIELD_INTROSPECTION,
        SCHEMA_INPUT_VALIDATION,
        SCHEMA_OUTPUT_SERIALIZATION,
    ),
)


class PydanticSchemaAdapter:
    provider = PYDANTIC_SCHEMA_CAPABILITIES

    @staticmethod
    def _model_type(schema: type[object]) -> type[BaseModel]:
        if not isinstance(schema, type) or not issubclass(schema, BaseModel):
            raise TypeError("PydanticSchemaAdapter requires a pydantic BaseModel schema")
        return schema

    def field_names(self, schema: type[object]) -> tuple[str, ...]:
        model = self._model_type(schema)
        return tuple(model.model_fields)

    def validate_input(
        self,
        schema: type[object],
        values: Mapping[str, object],
    ) -> object:
        model = self._model_type(schema)
        try:
            return model.model_validate(dict(values))
        except ValidationError as exc:
            raise SchemaValidationError(self._issues(exc)) from exc

    def serialize_output(self, schema: type[object], value: object) -> object:
        model = self._model_type(schema)
        try:
            validated = model.model_validate(value)
        except ValidationError as exc:
            raise SchemaValidationError(self._issues(exc)) from exc
        return validated.model_dump(mode="json")

    @staticmethod
    def _issues(exc: ValidationError) -> tuple[SchemaValidationIssue, ...]:
        return tuple(
            SchemaValidationIssue(
                location=tuple(str(part) for part in error.get("loc", ())),
                code=str(error.get("type", "invalid")),
                message=str(error.get("msg", "Invalid value")),
            )
            for error in exc.errors(
                include_url=False,
                include_context=False,
                include_input=False,
            )
        )


__all__ = [
    "PYDANTIC_SCHEMA_CAPABILITIES",
    "PydanticSchemaAdapter",
]
