from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.fields import FieldDefinition, infer_field_security
from tortoise.models import Model

_PORTABLE_QUERY_TYPES = (str, int, float, bool, date, datetime, Decimal, UUID)
_SUPPORTED_IDENTITY_TYPES = (str, int, UUID)


class UnsupportedTortoiseIdentityError(ValueError):
    pass


class UnsupportedTortoiseFieldPolicyError(ValueError):
    def __init__(self, field: str, policy: str) -> None:
        super().__init__(f"Unsupported Tortoise field policy: {policy}={field}")
        self.field = field
        self.policy = policy


@dataclass(frozen=True, slots=True)
class TortoiseFieldMetadata:
    name: str
    python_type: type[Any]
    nullable: bool
    generated: bool
    primary_key: bool
    default: object

    @property
    def writable(self) -> bool:
        return not self.primary_key and not self.generated

    @property
    def required(self) -> bool:
        return self.writable and not self.nullable and self.default is None

    @property
    def text_searchable(self) -> bool:
        return self.python_type is str

    @property
    def queryable(self) -> bool:
        return self.python_type in _PORTABLE_QUERY_TYPES


@dataclass(frozen=True, slots=True)
class TortoiseModelMetadata:
    model: type[Model]
    identity_field: str
    fields: tuple[TortoiseFieldMetadata, ...]

    @property
    def field_names(self) -> tuple[str, ...]:
        return tuple(field.name for field in self.fields)


def is_tortoise_model(model: type[object]) -> bool:
    return isinstance(model, type) and issubclass(model, Model) and model is not Model


def _field_python_type(field: object) -> type[Any]:
    describe = getattr(field, "describe", None)
    if not callable(describe):
        return object
    description = describe(False)
    value = description.get("python_type") if isinstance(description, dict) else None
    return value if isinstance(value, type) else object


def inspect_model(model: type[object]) -> TortoiseModelMetadata:
    if not is_tortoise_model(model):
        raise TypeError("Tortoise resources must subclass tortoise.models.Model")

    concrete_model = cast(type[Model], model)
    meta = concrete_model._meta
    identity_field = meta.pk_attr
    fields_map = meta.fields_map
    concrete_names = tuple(meta.fields_db_projection)

    fields: list[TortoiseFieldMetadata] = []
    for name in concrete_names:
        field = fields_map[name]
        fields.append(
            TortoiseFieldMetadata(
                name=name,
                python_type=_field_python_type(field),
                nullable=bool(getattr(field, "null", False)),
                generated=bool(getattr(field, "generated", False)),
                primary_key=bool(getattr(field, "pk", False)),
                default=getattr(field, "default", None),
            )
        )

    by_name = {field.name: field for field in fields}
    identity = by_name.get(identity_field)
    if identity is None or identity.python_type not in _SUPPORTED_IDENTITY_TYPES:
        raise UnsupportedTortoiseIdentityError(
            "Tortoise resources require one int, str, or UUID primary key"
        )

    return TortoiseModelMetadata(
        model=concrete_model,
        identity_field=identity_field,
        fields=tuple(fields),
    )


def validate_field_policy(
    metadata: TortoiseModelMetadata,
    field_policy: ResourceFieldPolicy,
) -> None:
    fields = {field.name: field for field in metadata.fields}
    for field_name in field_policy.search_fields:
        field = fields.get(field_name)
        if field is None or not field.text_searchable:
            raise UnsupportedTortoiseFieldPolicyError(field_name, "search_fields")
    for policy_name, declared in (
        ("filter_fields", field_policy.filter_fields),
        ("sort_fields", field_policy.sort_fields),
    ):
        for field_name in declared:
            field = fields.get(field_name)
            if field is None or not field.queryable:
                raise UnsupportedTortoiseFieldPolicyError(field_name, policy_name)


def field_definitions(
    metadata: TortoiseModelMetadata,
    field_policy: ResourceFieldPolicy,
) -> tuple[FieldDefinition, ...]:
    search_fields = set(field_policy.search_fields)
    filter_fields = set(field_policy.filter_fields)
    sort_fields = set(field_policy.sort_fields)
    return tuple(
        infer_field_security(
            FieldDefinition(
                field_id=field.name,
                python_type=field.python_type,
                readable=True,
                writable=field.writable,
                searchable=field.name in search_fields and field.text_searchable,
                filterable=field.name in filter_fields and field.queryable,
                sortable=field.name in sort_fields and field.queryable,
                required=field.required,
                nullable=field.nullable,
            )
        )
        for field in metadata.fields
    )


__all__ = [
    "TortoiseFieldMetadata",
    "TortoiseModelMetadata",
    "UnsupportedTortoiseFieldPolicyError",
    "UnsupportedTortoiseIdentityError",
    "field_definitions",
    "inspect_model",
    "is_tortoise_model",
    "validate_field_policy",
]
