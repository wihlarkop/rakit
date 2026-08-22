from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from peewee import (
    AutoField,
    BigAutoField,
    BigIntegerField,
    BooleanField,
    CharField,
    DateField,
    DateTimeField,
    DecimalField,
    DoubleField,
    Field,
    FixedCharField,
    FloatField,
    ForeignKeyField,
    IdentityField,
    IntegerField,
    Model,
    SmallIntegerField,
    TextField,
    UUIDField,
)
from playhouse.pwasyncio import AsyncDatabaseMixin
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.fields import FieldDefinition, infer_field_security

_PORTABLE_QUERY_TYPES = (str, int, float, bool, date, datetime, Decimal, UUID)
_SUPPORTED_IDENTITY_TYPES = (str, int, UUID)


class UnsupportedPeeweeIdentityError(ValueError):
    pass


class UnsupportedPeeweeAsyncDatabaseError(ValueError):
    pass


class MismatchedPeeweeDatabaseError(ValueError):
    pass


class UnsupportedPeeweeFieldPolicyError(ValueError):
    def __init__(self, field: str, policy: str) -> None:
        super().__init__(f"Unsupported Peewee field policy: {policy}={field}")
        self.field = field
        self.policy = policy


@dataclass(frozen=True, slots=True)
class PeeweeFieldMetadata:
    name: str
    field: Field
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
        return self.writable and not self.nullable and self.default is None

    @property
    def text_searchable(self) -> bool:
        return self.python_type is str

    @property
    def queryable(self) -> bool:
        return self.portable_scalar


@dataclass(frozen=True, slots=True)
class PeeweeModelMetadata:
    model: type[Model]
    database: AsyncDatabaseMixin
    identity_field: str
    fields: tuple[PeeweeFieldMetadata, ...]

    @property
    def field_names(self) -> tuple[str, ...]:
        return tuple(field.name for field in self.fields)


def is_peewee_model(subject: object) -> bool:
    return isinstance(subject, type) and issubclass(subject, Model) and subject is not Model


def _field_python_type(field: Field) -> type[Any]:
    if isinstance(field, (CharField, FixedCharField, TextField)):
        return str
    if isinstance(field, BooleanField):
        return bool
    if isinstance(
        field,
        (AutoField, BigAutoField, IdentityField, IntegerField, BigIntegerField, SmallIntegerField),
    ):
        return int
    if isinstance(field, (FloatField, DoubleField)):
        return float
    if isinstance(field, DecimalField):
        return Decimal
    if isinstance(field, DateTimeField):
        return datetime
    if isinstance(field, DateField):
        return date
    if isinstance(field, UUIDField):
        return UUID
    return object


def inspect_model(
    subject: object,
    *,
    database: AsyncDatabaseMixin | None = None,
) -> PeeweeModelMetadata:
    if not is_peewee_model(subject):
        raise TypeError("Peewee resources must subclass peewee.Model")

    model = cast(type[Model], subject)
    model_database = model._meta.database
    if not isinstance(model_database, AsyncDatabaseMixin):
        raise UnsupportedPeeweeAsyncDatabaseError(
            "Peewee resources must be bound to playhouse.pwasyncio async databases"
        )
    if database is not None and model_database is not database:
        raise MismatchedPeeweeDatabaseError(
            "Peewee resource database does not match the configured PeeweePlugin database"
        )

    primary_key = model._meta.primary_key
    if not isinstance(primary_key, Field) or isinstance(primary_key, ForeignKeyField):
        raise UnsupportedPeeweeIdentityError(
            "Peewee resources require one scalar int, str, or UUID primary key"
        )

    fields: list[PeeweeFieldMetadata] = []
    for field in model._meta.fields.values():
        if isinstance(field, ForeignKeyField):
            continue
        python_type = _field_python_type(field)
        fields.append(
            PeeweeFieldMetadata(
                name=field.name,
                field=field,
                python_type=python_type,
                nullable=bool(field.null),
                generated=isinstance(field, (AutoField, BigAutoField, IdentityField)),
                primary_key=bool(field.primary_key),
                default=field.default,
            )
        )

    by_name = {field.name: field for field in fields}
    identity = by_name.get(primary_key.name)
    if identity is None or identity.python_type not in _SUPPORTED_IDENTITY_TYPES:
        raise UnsupportedPeeweeIdentityError(
            "Peewee resources require one scalar int, str, or UUID primary key"
        )

    return PeeweeModelMetadata(
        model=model,
        database=model_database,
        identity_field=identity.name,
        fields=tuple(fields),
    )


def validate_field_policy(
    metadata: PeeweeModelMetadata,
    field_policy: ResourceFieldPolicy,
) -> None:
    fields = {field.name: field for field in metadata.fields}
    for field_name in field_policy.search_fields:
        field = fields.get(field_name)
        if field is None or not field.text_searchable:
            raise UnsupportedPeeweeFieldPolicyError(field_name, "search_fields")
    for policy_name, declared in (
        ("filter_fields", field_policy.filter_fields),
        ("sort_fields", field_policy.sort_fields),
    ):
        for field_name in declared:
            field = fields.get(field_name)
            if field is None or not field.queryable:
                raise UnsupportedPeeweeFieldPolicyError(field_name, policy_name)


def field_definitions(
    metadata: PeeweeModelMetadata,
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
    "MismatchedPeeweeDatabaseError",
    "PeeweeFieldMetadata",
    "PeeweeModelMetadata",
    "UnsupportedPeeweeAsyncDatabaseError",
    "UnsupportedPeeweeFieldPolicyError",
    "UnsupportedPeeweeIdentityError",
    "field_definitions",
    "inspect_model",
    "is_peewee_model",
    "validate_field_policy",
]
