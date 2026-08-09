"""Typed field metadata used by forms and mutation plans.

The declaration is deliberately framework-neutral: adapters may construct it
from model metadata, while applications may declare it directly for custom
resources.  A sensitive field is fail-closed for every public capability.
"""

from dataclasses import dataclass, replace
from typing import Any

_SENSITIVE_NAME_PARTS = (
    "password",
    "password_hash",
    "secret",
    "token",
    "api_key",
    "private_key",
    "authorization",
    "cookie",
)


@dataclass(frozen=True)
class FieldDefinition:
    field_id: str
    python_type: type[Any]
    label: str | None = None
    readable: bool = True
    writable: bool = True
    searchable: bool = True
    filterable: bool = True
    sortable: bool = True
    required: bool = False
    nullable: bool = False
    widget: str = "text"
    sensitive: bool = False

    def __post_init__(self) -> None:
        if not self.field_id or not isinstance(self.field_id, str):
            raise ValueError("Field id must be a non-empty string")
        if not isinstance(self.python_type, type):
            raise ValueError("Field python_type must be a type")


def infer_field_security(field: FieldDefinition) -> FieldDefinition:
    """Return a fail-closed field definition for conventionally sensitive fields.

    Explicitly declaring ``sensitive=True`` is the durable policy mechanism;
    the name check is a secure default for adapter-generated fields.
    """

    normalized = field.field_id.lower()
    sensitive = field.sensitive or any(part in normalized for part in _SENSITIVE_NAME_PARTS)
    if not sensitive:
        return field
    return replace(
        field,
        sensitive=True,
        readable=False,
        writable=False,
        searchable=False,
        filterable=False,
        sortable=False,
    )
