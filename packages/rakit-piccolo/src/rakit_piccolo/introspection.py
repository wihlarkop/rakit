from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from piccolo.columns.base import Column
from piccolo.columns.column_types import BigSerial, ForeignKey, Serial
from piccolo.engine.base import Engine
from piccolo.table import Table
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.fields import FieldDefinition, infer_field_security

_PORTABLE_QUERY_TYPES = (str, int, float, bool, date, datetime, Decimal, UUID)
_SUPPORTED_IDENTITY_TYPES = (str, int, UUID)


class UnsupportedPiccoloIdentityError(ValueError):
    pass


class UnsupportedPiccoloEngineError(ValueError):
    pass


class MismatchedPiccoloEngineError(ValueError):
    pass


class UnsupportedPiccoloFieldPolicyError(ValueError):
    def __init__(self, field: str, policy: str) -> None:
        super().__init__(f"Unsupported Piccolo field policy: {policy}={field}")
        self.field = field
        self.policy = policy


@dataclass(frozen=True, slots=True)
class PiccoloFieldMetadata:
    name: str
    column: Column
    python_type: type[Any]
    nullable: bool
    generated: bool
    primary_key: bool
    default: object

    @property
    def portable_scalar(self) -> bool:
        return self.python_type in _PORTABLE_QUERY_TYPES

    @property
    def writable(self) -> bool:
        return not self.primary_key and not self.generated and self.portable_scalar

    @property
    def required(self) -> bool:
        return self.writable and bool(self.column._meta.required)

    @property
    def text_searchable(self) -> bool:
        return self.python_type is str

    @property
    def queryable(self) -> bool:
        return self.portable_scalar


@dataclass(frozen=True, slots=True)
class PiccoloModelMetadata:
    model: type[Table]
    engine: Engine[Any]
    identity_field: str
    fields: tuple[PiccoloFieldMetadata, ...]

    @property
    def field_names(self) -> tuple[str, ...]:
        return tuple(field.name for field in self.fields)


def is_piccolo_model(subject: object) -> bool:
    return isinstance(subject, type) and issubclass(subject, Table) and subject is not Table


def inspect_model(
    subject: object,
    *,
    engine: Engine[Any] | None = None,
) -> PiccoloModelMetadata:
    if not is_piccolo_model(subject):
        raise TypeError("Piccolo resources must subclass piccolo.table.Table")

    model = cast(type[Table], subject)
    try:
        model_engine = model._meta.db
    except Exception as exc:
        raise UnsupportedPiccoloEngineError(
            "Piccolo resources require a configured Engine"
        ) from exc
    if not isinstance(model_engine, Engine):
        raise UnsupportedPiccoloEngineError("Piccolo resources require a configured Engine")
    if engine is not None and model_engine is not engine:
        raise MismatchedPiccoloEngineError(
            "Piccolo resource engine does not match the configured PiccoloPlugin engine"
        )

    primary_key = model._meta.primary_key
    if isinstance(primary_key, ForeignKey):
        raise UnsupportedPiccoloIdentityError(
            "Piccolo resources require one scalar int, str, or UUID primary key"
        )

    fields: list[PiccoloFieldMetadata] = []
    for column in model._meta.columns:
        if isinstance(column, ForeignKey):
            continue
        python_type = column.value_type if isinstance(column.value_type, type) else object
        fields.append(
            PiccoloFieldMetadata(
                name=column._meta.name,
                column=column,
                python_type=python_type,
                nullable=bool(column._meta.null),
                generated=isinstance(column, Serial | BigSerial),
                primary_key=bool(column._meta.primary_key),
                default=getattr(column, "default", None),
            )
        )

    by_name = {field.name: field for field in fields}
    identity = by_name.get(primary_key._meta.name)
    if identity is None or identity.python_type not in _SUPPORTED_IDENTITY_TYPES:
        raise UnsupportedPiccoloIdentityError(
            "Piccolo resources require one scalar int, str, or UUID primary key"
        )

    return PiccoloModelMetadata(
        model=model,
        engine=model_engine,
        identity_field=identity.name,
        fields=tuple(fields),
    )


def validate_field_policy(
    metadata: PiccoloModelMetadata,
    field_policy: ResourceFieldPolicy,
) -> None:
    fields = {field.name: field for field in metadata.fields}
    for field_name in field_policy.search_fields:
        field = fields.get(field_name)
        if field is None or not field.text_searchable:
            raise UnsupportedPiccoloFieldPolicyError(field_name, "search_fields")
    for policy_name, declared in (
        ("filter_fields", field_policy.filter_fields),
        ("sort_fields", field_policy.sort_fields),
    ):
        for field_name in declared:
            field = fields.get(field_name)
            if field is None or not field.queryable:
                raise UnsupportedPiccoloFieldPolicyError(field_name, policy_name)


def field_definitions(
    metadata: PiccoloModelMetadata,
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
    "MismatchedPiccoloEngineError",
    "PiccoloFieldMetadata",
    "PiccoloModelMetadata",
    "UnsupportedPiccoloEngineError",
    "UnsupportedPiccoloFieldPolicyError",
    "UnsupportedPiccoloIdentityError",
    "field_definitions",
    "inspect_model",
    "is_piccolo_model",
    "validate_field_policy",
]
