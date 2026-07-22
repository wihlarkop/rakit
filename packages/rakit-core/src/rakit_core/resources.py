from rakit_core.datasource import DataSource
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.identity import RecordIdentity
from rakit_core.query import PageResult, ResourceQuery


class ResourceService:
    """Thin read-only pass-through over a `DataSource`.

    Query translation and whitelisting happen upstream (`ResourceQuery.from_params()`),
    and actually executing the query is the data source's responsibility. This service
    only forwards calls and normalizes `detail()`'s "not found" case into a `RakitError`.
    """

    def __init__(self, data_source: DataSource) -> None:
        self._data_source = data_source

    @property
    def data_source(self) -> DataSource:
        return self._data_source

    async def list(self, query: ResourceQuery) -> PageResult:
        return await self._data_source.list(query)

    async def count(self, query: ResourceQuery) -> int:
        return await self._data_source.count(query)

    async def detail(self, identity: RecordIdentity) -> object:
        record = await self._data_source.detail(identity)
        if record is None:
            raise RakitError(
                code=ErrorCode.RESOURCE_NOT_FOUND,
                message=f"Resource with identity {identity.values!r} was not found.",
                status_code=404,
                details={"identity": identity.values},
            )
        return record
