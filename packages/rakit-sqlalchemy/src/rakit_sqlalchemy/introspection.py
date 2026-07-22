from dataclasses import dataclass
from typing import Any

from sqlalchemy import Integer, String, Uuid, inspect
from sqlalchemy.sql.type_api import TypeEngine
from sqlalchemy.types import TypeDecorator


class UnsupportedIdentityError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class FieldMetadata:
    attribute_name: str
    database_name: str
    column_type: TypeEngine[Any]


@dataclass(frozen=True)
class ModelMetadata:
    identity_field: str
    fields: tuple[str, ...]
    field_metadata: tuple[FieldMetadata, ...]


def _unwrap_type(type_: TypeEngine[Any]) -> TypeEngine[Any]:
    while isinstance(type_, TypeDecorator):
        implementation = type_.impl
        if not isinstance(implementation, TypeEngine):
            raise UnsupportedIdentityError("unsupported_type")
        type_ = implementation
    return type_


def _validate_identity_type(type_: TypeEngine[Any]) -> None:
    base_type = _unwrap_type(type_)
    if not isinstance(base_type, Integer | String | Uuid):
        raise UnsupportedIdentityError("unsupported_type")


def inspect_model(model: type[object]) -> ModelMetadata:
    mapper = inspect(model)
    # `inspect()` raises on failure by default (raiseerr=True), but its return
    # type is `Any | None` regardless of the input; assert to narrow it for
    # the type checker rather than silencing the whole function.
    assert mapper is not None
    primary_keys = tuple(mapper.primary_key)
    if len(primary_keys) != 1:
        raise UnsupportedIdentityError("composite_identity")
    identity_column = primary_keys[0]
    _validate_identity_type(identity_column.type)
    identity_field = mapper.get_property_by_column(identity_column).key

    field_metadata = tuple(
        FieldMetadata(
            attribute_name=property_.key,
            database_name=property_.columns[0].name,
            column_type=property_.columns[0].type,
        )
        for property_ in mapper.column_attrs
    )
    return ModelMetadata(
        identity_field=identity_field,
        fields=tuple(field.attribute_name for field in field_metadata),
        field_metadata=field_metadata,
    )
