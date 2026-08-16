from collections.abc import Mapping

from pydantic import BaseModel, ValidationError
from rakit_core.adapter_capabilities import (
    SCHEMA_FIELD_INTROSPECTION,
    SCHEMA_INPUT_VALIDATION,
    SCHEMA_OUTPUT_SERIALIZATION,
    SCHEMA_PARTIAL_UPDATE,
)
from rakit_core.capabilities import CapabilityProvider, CapabilitySet
from rakit_core.schema import SchemaField, SchemaValidationError, SchemaValidationIssue

PYDANTIC_SCHEMA_CAPABILITIES = CapabilityProvider(
    provider_id="schema.pydantic",
    capabilities=CapabilitySet.of(
        SCHEMA_FIELD_INTROSPECTION,
        SCHEMA_INPUT_VALIDATION,
        SCHEMA_OUTPUT_SERIALIZATION,
        SCHEMA_PARTIAL_UPDATE,
    ),
)


class PydanticSchemaAdapter:
    provider = PYDANTIC_SCHEMA_CAPABILITIES

    @staticmethod
    def _model_type(schema: type[object]) -> type[BaseModel]:
        if not isinstance(schema, type) or not issubclass(schema, BaseModel):
            raise TypeError("PydanticSchemaAdapter requires a pydantic BaseModel schema")
        return schema

    def fields(self, schema: type[object]) -> tuple[SchemaField, ...]:
        model = self._model_type(schema)
        return tuple(
            SchemaField(
                name=name,
                title=field.title,
                description=field.description,
            )
            for name, field in model.model_fields.items()
        )

    def field_names(self, schema: type[object]) -> tuple[str, ...]:
        return tuple(field.name for field in self.fields(schema))

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

    def validate_partial_input(
        self,
        schema: type[object],
        values: Mapping[str, object],
    ) -> Mapping[str, object]:
        model = self._model_type(schema)
        try:
            validated = model.model_validate(dict(values))
        except ValidationError as exc:
            raise SchemaValidationError(self._issues(exc)) from exc
        return validated.model_dump(mode="json", exclude_unset=True)

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
