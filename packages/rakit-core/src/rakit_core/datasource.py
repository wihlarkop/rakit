from typing import Protocol

from pydantic import BaseModel, ConfigDict

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
