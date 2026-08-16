from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import Enum, Integer, String, Uuid, inspect
from sqlalchemy.sql.type_api import TypeEngine
from sqlalchemy.types import TypeDecorator

_SUPPORTED_IDENTITY_PYTHON_TYPES = (int, str, UUID)


class UnsupportedIdentityError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class UnsupportedFieldPolicyError(ValueError):
    """A resource's compiled `filter_fields`/`search_fields` policy names a
    field whose mapped type has no supported query semantics for that
    purpose (no built-in coercion path and no explicit adapter hook)."""

    def __init__(self, field: str, policy: str, reason: str) -> None:
        super().__init__(reason)
        self.field = field
        self.policy = policy
        self.reason = reason


@dataclass(frozen=True)
class FieldMetadata:
    attribute_name: str
    database_name: str
    column_type: TypeEngine[Any]
    python_type: type[object]
    nullable: bool
    required: bool
    writable: bool


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
    """Reject any identity whose effective Python value isn't exactly int
    (excluding bool), str, or UUID.

    `sqlalchemy.Enum` is a `String` subclass, so an `isinstance(type_, String)`
    check alone would wrongly accept an Enum primary key -- its persisted
    Python value is an `enum.Enum` member (or a bare string with no case
    mapping back to one), which `RecordIdentity`/the web identity codec
    cannot encode into a stable, roundtrippable URL token. `Enum` is
    therefore rejected unconditionally, both when it *is* backed by a Python
    `enum.Enum` class and when it persists a plain string.

    Plan 02 supports only int/str/UUID identities (the approved v0.1
    guarantee) -- it does not support custom identity domain objects, so
    there is no opt-in codec hook here. A `TypeDecorator` must therefore
    explicitly declare `python_type` as exactly `int`, `str`, or `UUID`:

    - a `TypeDecorator` that does not override `python_type` at all (SQLAlchemy
      raises `NotImplementedError` in that case, and does *not* implicitly
      delegate to the unwrapped `impl`'s `python_type`) is rejected -- an
      unstated Python type is not proof of safety, and a decorator overriding
      only `process_result_value()` without `python_type` would otherwise
      silently return an unencodable custom object;
    - a `TypeDecorator` whose `python_type` resolves to anything other than
      exactly `int`, `str`, or `UUID` (e.g. a genuine custom domain object) is
      rejected;
    - the decorator's declared `impl` must *also* unwrap to a supported base
      type (`Integer`/`String`/`Uuid`, never `Enum`) -- this is deliberate
      defence in depth alongside the `python_type` check, not a substitute
      for it.
    """
    if isinstance(type_, TypeDecorator):
        implementation = _unwrap_type(type_)
        if isinstance(implementation, Enum) or not isinstance(
            implementation, Integer | String | Uuid
        ):
            raise UnsupportedIdentityError("unsupported_type")
        try:
            effective_type = type_.python_type
        except NotImplementedError:
            raise UnsupportedIdentityError("unsupported_type") from None
        if effective_type not in _SUPPORTED_IDENTITY_PYTHON_TYPES:
            raise UnsupportedIdentityError("unsupported_type")
        return

    if isinstance(type_, Enum) or not isinstance(type_, Integer | String | Uuid):
        raise UnsupportedIdentityError("unsupported_type")


def _python_type(type_: TypeEngine[Any]) -> type[object]:
    try:
        value = type_.python_type
    except NotImplementedError:
        return object
    return value if isinstance(value, type) else object


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

    metadata: list[FieldMetadata] = []
    for property_ in mapper.column_attrs:
        column = property_.columns[0]
        writable = not column.primary_key and column.computed is None
        has_default = (
            column.default is not None
            or column.server_default is not None
            or column.identity is not None
        )
        metadata.append(
            FieldMetadata(
                attribute_name=property_.key,
                database_name=column.name,
                column_type=column.type,
                python_type=_python_type(column.type),
                nullable=bool(column.nullable),
                required=writable and not column.nullable and not has_default,
                writable=writable,
            )
        )
    field_metadata = tuple(metadata)
    return ModelMetadata(
        identity_field=identity_field,
        fields=tuple(field.attribute_name for field in field_metadata),
        field_metadata=field_metadata,
    )
