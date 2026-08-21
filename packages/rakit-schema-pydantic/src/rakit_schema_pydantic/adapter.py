from collections.abc import Mapping
from typing import Annotated

from pydantic import BaseModel, TypeAdapter, ValidationError
from rakit_core.schema import SchemaField, SchemaValidationError, SchemaValidationIssue

from .capabilities import PYDANTIC_SCHEMA_CAPABILITIES
from .discovery import PYDANTIC_INTEGRATION


class PydanticSchemaAdapter:
    provider = PYDANTIC_SCHEMA_CAPABILITIES
    rakit_integration = PYDANTIC_INTEGRATION

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
        validated: dict[str, object] = {}
        issues: list[SchemaValidationIssue] = []

        for name, value in values.items():
            field = model.model_fields.get(name)
            if field is None:
                issues.append(
                    SchemaValidationIssue(
                        location=(name,),
                        code="extra_forbidden",
                        message="Field is not declared by the schema",
                    )
                )
                continue

            annotation: object = field.annotation
            if field.metadata:
                annotation = Annotated[field.annotation, *field.metadata]
            adapter = TypeAdapter(annotation)
            try:
                field_value = adapter.validate_python(value)
            except ValidationError as exc:
                issues.extend(self._issues(exc, prefix=(name,)))
                continue
            validated[name] = adapter.dump_python(field_value, mode="json")

        if issues:
            raise SchemaValidationError(tuple(issues))
        return validated

    def serialize_output(self, schema: type[object], value: object) -> object:
        model = self._model_type(schema)
        try:
            validated = model.model_validate(value)
        except ValidationError as exc:
            raise SchemaValidationError(self._issues(exc)) from exc
        return validated.model_dump(mode="json")

    @staticmethod
    def _issues(
        exc: ValidationError,
        *,
        prefix: tuple[str, ...] = (),
    ) -> tuple[SchemaValidationIssue, ...]:
        return tuple(
            SchemaValidationIssue(
                location=prefix + tuple(str(part) for part in error.get("loc", ())),
                code=str(error.get("type", "invalid")),
                message=str(error.get("msg", "Invalid value")),
            )
            for error in exc.errors(
                include_url=False,
                include_context=False,
                include_input=False,
            )
        )


__all__ = ["PydanticSchemaAdapter"]
