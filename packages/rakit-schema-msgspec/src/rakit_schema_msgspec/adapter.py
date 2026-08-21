from collections.abc import Mapping
import re

import msgspec
from rakit_core.schema import SchemaField, SchemaValidationError, SchemaValidationIssue

from .capabilities import MSGSPEC_SCHEMA_CAPABILITIES
from .discovery import MSGSPEC_INTEGRATION

_PATH_RE = re.compile(r" - at \$(?P<path>(?:\.[^.\[]+|\[[^\]]+\])*)$")


class MsgspecSchemaAdapter:
    provider = MSGSPEC_SCHEMA_CAPABILITIES
    rakit_integration = MSGSPEC_INTEGRATION

    @staticmethod
    def _struct_type(schema: type[object]) -> type[msgspec.Struct]:
        if not isinstance(schema, type) or not issubclass(schema, msgspec.Struct):
            raise TypeError("MsgspecSchemaAdapter requires a msgspec.Struct schema")
        return schema

    @staticmethod
    def _struct_fields(schema: type[msgspec.Struct]) -> tuple[msgspec.structs.FieldInfo, ...]:
        return msgspec.structs.fields(schema)

    def fields(self, schema: type[object]) -> tuple[SchemaField, ...]:
        struct = self._struct_type(schema)
        return tuple(SchemaField(name=field.name) for field in self._struct_fields(struct))

    def field_names(self, schema: type[object]) -> tuple[str, ...]:
        return tuple(field.name for field in self.fields(schema))

    def validate_input(
        self,
        schema: type[object],
        values: Mapping[str, object],
    ) -> object:
        struct = self._struct_type(schema)
        try:
            return msgspec.convert(dict(values), type=struct, strict=True)
        except msgspec.ValidationError as exc:
            raise SchemaValidationError((self._issue(exc),)) from exc

    def validate_partial_input(
        self,
        schema: type[object],
        values: Mapping[str, object],
    ) -> Mapping[str, object]:
        struct = self._struct_type(schema)
        fields = {field.name: field for field in self._struct_fields(struct)}
        validated: dict[str, object] = {}
        issues: list[SchemaValidationIssue] = []

        for name, value in values.items():
            field = fields.get(name)
            if field is None:
                issues.append(
                    SchemaValidationIssue(
                        location=(name,),
                        code="extra_forbidden",
                        message="Field is not declared by the schema",
                    )
                )
                continue
            try:
                field_value = msgspec.convert(value, type=field.type, strict=True)
            except msgspec.ValidationError as exc:
                issues.append(self._issue(exc, prefix=(name,)))
                continue
            validated[name] = msgspec.to_builtins(field_value)

        if issues:
            raise SchemaValidationError(tuple(issues))
        return validated

    def serialize_output(self, schema: type[object], value: object) -> object:
        struct = self._struct_type(schema)
        try:
            validated = msgspec.convert(value, type=struct, strict=True)
        except msgspec.ValidationError as exc:
            raise SchemaValidationError((self._issue(exc),)) from exc
        return msgspec.to_builtins(validated)

    @classmethod
    def _issue(
        cls,
        exc: msgspec.ValidationError,
        *,
        prefix: tuple[str, ...] = (),
    ) -> SchemaValidationIssue:
        message = str(exc)
        match = _PATH_RE.search(message)
        location = prefix + cls._location(match.group("path") if match else "")
        if match:
            message = message[: match.start()]
        return SchemaValidationIssue(
            location=location,
            code="validation_error",
            message=message,
        )

    @staticmethod
    def _location(path: str) -> tuple[str, ...]:
        if not path:
            return ()
        parts: list[str] = []
        for token in re.findall(r"\.([^.\[]+)|\[([^\]]+)\]", path):
            part = token[0] or token[1]
            parts.append(part.strip("'\""))
        return tuple(parts)


__all__ = ["MsgspecSchemaAdapter"]
