from typing import Protocol

from pydantic import BaseModel, ConfigDict

from rakit_core.fields import FieldDefinition
from rakit_core.identity import RecordIdentity
from rakit_core.query import PageResult, ResourceQuery


class DataSourceCapabilities(BaseModel):
    model_config = ConfigDict(frozen=True)
    read: bool = True
    create: bool = False
    update: bool = False
    delete: bool = False
    transactions: bool = False
    optimistic_concurrency: bool = False


class DataSource(Protocol):
    capabilities: DataSourceCapabilities

    # Read-only (property) members so implementers may satisfy them with either a
    # plain class attribute (test doubles) or a computed property (SQLAlchemy), and
    # so narrower literal tuple types match covariantly.
    @property
    def fields(self) -> tuple[str, ...]: ...

    @property
    def identity_fields(self) -> tuple[str, ...]: ...

    async def list(self, query: ResourceQuery) -> PageResult: ...

    async def count(self, query: ResourceQuery) -> int: ...

    async def detail(self, identity: RecordIdentity) -> object: ...


class ResourceFieldDefinitionProvider(Protocol):
    """Optional richer resource metadata used by generated mutation surfaces.

    Read-only data sources are not required to implement this protocol. A generated
    create/PATCH surface opts into the stronger contract explicitly and fails closed
    at compile time when the selected persistence adapter cannot provide it.
    """

    @property
    def field_definitions(self) -> tuple[FieldDefinition, ...]: ...


def resolve_resource_field_definitions(data_source: object) -> tuple[FieldDefinition, ...] | None:
    value = getattr(data_source, "field_definitions", None)
    if not isinstance(value, tuple) or not all(isinstance(item, FieldDefinition) for item in value):
        return None
    return value


__all__ = [
    "DataSource",
    "DataSourceCapabilities",
    "ResourceFieldDefinitionProvider",
    "resolve_resource_field_definitions",
]
