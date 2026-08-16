from dataclasses import dataclass
from enum import StrEnum

from .fields import FieldDefinition
from .query import FilterOperator


class ApiExposure(StrEnum):
    NONE = "none"
    READ_ONLY = "read_only"
    CRUD = "crud"


class GeneratedCrudOperation(StrEnum):
    LIST = "list"
    DETAIL = "detail"
    CREATE = "create"
    UPDATE_PARTIAL = "update_partial"
    DELETE = "delete"


_READ_ONLY_OPERATIONS = (
    GeneratedCrudOperation.LIST,
    GeneratedCrudOperation.DETAIL,
)
_CRUD_OPERATIONS = (
    *_READ_ONLY_OPERATIONS,
    GeneratedCrudOperation.CREATE,
    GeneratedCrudOperation.UPDATE_PARTIAL,
    GeneratedCrudOperation.DELETE,
)


def _validate_unique_strings(name: str, values: tuple[str, ...]) -> None:
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError(f"{name} entries must be non-empty strings")
    if len(set(values)) != len(values):
        raise ValueError(f"{name} entries must be unique")


@dataclass(frozen=True, slots=True)
class ApiFilterDefinition:
    name: str
    field: str
    operators: tuple[FilterOperator, ...] = (FilterOperator.EQ,)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Filter name must be non-empty")
        if not self.field:
            raise ValueError("Filter field must be non-empty")
        if not self.operators:
            raise ValueError("Filter operators must not be empty")
        if len(set(self.operators)) != len(self.operators):
            raise ValueError("Filter operators must be unique")


@dataclass(frozen=True, slots=True)
class ResourceApiDefinition:
    exposure: ApiExposure = ApiExposure.NONE
    read_fields: tuple[str, ...] = ()
    create_fields: tuple[str, ...] = ()
    update_fields: tuple[str, ...] = ()
    filters: tuple[ApiFilterDefinition, ...] = ()
    create_schema: type[object] | None = None
    update_schema: type[object] | None = None

    def __post_init__(self) -> None:
        _validate_unique_strings("read_fields", self.read_fields)
        _validate_unique_strings("create_fields", self.create_fields)
        _validate_unique_strings("update_fields", self.update_fields)
        filter_names = tuple(item.name for item in self.filters)
        if len(set(filter_names)) != len(filter_names):
            raise ValueError("Filter names must be unique")

    @property
    def operations(self) -> tuple[GeneratedCrudOperation, ...]:
        if self.exposure is ApiExposure.NONE:
            return ()
        if self.exposure is ApiExposure.READ_ONLY:
            return _READ_ONLY_OPERATIONS
        return _CRUD_OPERATIONS


@dataclass(frozen=True, slots=True)
class CompiledResourceApi:
    resource_id: str
    definition: ResourceApiDefinition
    operations: tuple[GeneratedCrudOperation, ...]
    read_fields: tuple[str, ...]
    create_fields: tuple[str, ...]
    update_fields: tuple[str, ...]
    identity_fields: tuple[str, ...]
    filters: tuple[ApiFilterDefinition, ...]
    field_definitions: tuple[FieldDefinition, ...] = ()


__all__ = [
    "ApiExposure",
    "ApiFilterDefinition",
    "CompiledResourceApi",
    "GeneratedCrudOperation",
    "ResourceApiDefinition",
]
