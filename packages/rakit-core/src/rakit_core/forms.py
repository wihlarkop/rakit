"""Small immutable form state over Pydantic field validation."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from pydantic import TypeAdapter, ValidationError

from rakit_core.fields import FieldDefinition, infer_field_security


def _frozen_mapping(values: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(values))


@dataclass(frozen=True)
class FormIssue:
    field_id: str | None
    message: str


@dataclass(frozen=True)
class FormState:
    initial: Mapping[str, Any]
    submitted: Mapping[str, Any]
    normalized: Mapping[str, Any]
    issues: tuple[FormIssue, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.issues


class FormValidationError(ValueError):
    def __init__(self, state: FormState) -> None:
        super().__init__("Form validation failed")
        self.state = state


@dataclass(frozen=True)
class FormSchema:
    fields: tuple[FieldDefinition, ...]

    def __post_init__(self) -> None:
        secured = tuple(infer_field_security(field) for field in self.fields)
        field_ids = tuple(field.field_id for field in secured)
        if len(set(field_ids)) != len(field_ids):
            raise ValueError("Form field ids must be unique")
        object.__setattr__(self, "fields", secured)

    def parse(
        self,
        submitted: Mapping[str, Any],
        *,
        initial: Mapping[str, Any] | None = None,
    ) -> FormState:
        known = {field.field_id: field for field in self.fields}
        unknown = set(submitted).difference(known)
        if unknown:
            raise ValueError("Unknown form field")

        values: dict[str, Any] = {}
        issues: list[FormIssue] = []
        for field in self.fields:
            if not field.writable and field.field_id in submitted:
                issues.append(FormIssue(field.field_id, "This field is read-only."))
                continue
            raw = submitted.get(field.field_id)
            if raw is None or raw == "":
                if field.required and not field.nullable:
                    issues.append(FormIssue(field.field_id, "This field is required."))
                elif field.nullable:
                    values[field.field_id] = None
                continue
            try:
                values[field.field_id] = TypeAdapter(field.python_type).validate_python(raw)
            except ValidationError:
                issues.append(FormIssue(field.field_id, "Invalid value."))

        state = FormState(
            initial=_frozen_mapping(initial or {}),
            submitted=_frozen_mapping(submitted),
            normalized=_frozen_mapping(values),
            issues=tuple(issues),
        )
        if state.issues:
            raise FormValidationError(state)
        return state
