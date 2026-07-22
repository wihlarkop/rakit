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

    async def list(self, query: ResourceQuery) -> PageResult: ...

    async def detail(self, identity: RecordIdentity) -> object: ...
