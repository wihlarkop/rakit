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


def _effective_identity_python_type(type_: TypeEngine[Any]) -> type | None:
    """The `TypeDecorator`'s own declared effective Python type, if any.

    `TypeDecorator.python_type` raises `NotImplementedError` when a decorator
    does not override it -- SQLAlchemy does not implicitly delegate to the
    unwrapped `impl`'s python_type. That omission means the decorator makes
    no explicit claim about its Python value differing from `impl`'s, so it
    is treated as "no override" (`None`), not as evidence of an unsafe type:
    the already-performed `impl`-unwrap check remains the source of truth for
    that case. Only a decorator that *does* override `python_type` to
    something other than int/str/UUID is rejected here.
    """
    try:
        return type_.python_type
    except NotImplementedError:
        return None


def _validate_identity_type(type_: TypeEngine[Any]) -> None:
    """Reject any identity whose effective Python value isn't int/str/UUID.

    `sqlalchemy.Enum` is a `String` subclass, so an `isinstance(type_, String)`
    check alone would wrongly accept an Enum primary key -- its persisted
    Python value is an `enum.Enum` member (or a bare string with no case
    mapping back to one), which `RecordIdentity`/the web identity codec
    cannot encode into a stable, roundtrippable URL token. `Enum` is
    therefore rejected unconditionally, both when it *is* backed by a Python
    `enum.Enum` class and when it persists a plain string.

    A `TypeDecorator` gets the same treatment plus one extra check: even if
    its declared `impl` unwraps to a supported base type, the decorator may
    override `process_result_value`/`python_type` to hand back a domain
    object instead of a plain int/str/UUID (e.g. a `TypeDecorator[String]`
    that returns a custom value object) -- that failure mode is caught by
    checking the type's own effective `python_type`, not just its `impl`.

    A `TypeDecorator` may opt out of both checks by declaring an explicit
    `rakit_identity_codec` attribute (mirroring the `rakit_coerce_filter_value`
    filter-value hook): this is a deliberate, explicit contract for a genuine
    custom identity type, never an inferred one -- no constructor is called
    and no arbitrary Python type is trusted implicitly.
    """
    if isinstance(type_, TypeDecorator):
        if getattr(type_, "rakit_identity_codec", None) is not None:
            return
        implementation = _unwrap_type(type_)
        if isinstance(implementation, Enum) or not isinstance(
            implementation, Integer | String | Uuid
        ):
            raise UnsupportedIdentityError("unsupported_type")
        effective_type = _effective_identity_python_type(type_)
        if effective_type is not None and effective_type not in _SUPPORTED_IDENTITY_PYTHON_TYPES:
            raise UnsupportedIdentityError("unsupported_type")
        return

    if isinstance(type_, Enum) or not isinstance(type_, Integer | String | Uuid):
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
