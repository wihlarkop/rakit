from rakit_core.datasource import DataSource
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.identity import RecordIdentity
from rakit_core.pagination import PagePagination, PageResult, ResourceListResult
from rakit_core.query import ResourceQuery


def _normalize_legacy_page_result(
    query: ResourceQuery,
    result: ResourceListResult,
) -> ResourceListResult:
    """Normalize the historical structural PAGE result shape.

    Before pagination strategies became explicit, custom data sources could
    return any page-shaped object exposing the six public page attributes. Keep
    that structural contract working for the default PAGE strategy only. New
    limit/offset and cursor strategies remain strict so Rakit never invents
    metadata that an adapter did not actually return.
    """
    if isinstance(result, PageResult) or not isinstance(query.pagination, PagePagination):
        return result

    try:
        items = tuple(getattr(result, "items"))
        page = getattr(result, "page")
        per_page = getattr(result, "per_page")
        has_previous = getattr(result, "has_previous")
        has_next = getattr(result, "has_next")
        total_count = getattr(result, "total_count")
    except (AttributeError, TypeError):
        return result

    if (
        not isinstance(page, int)
        or isinstance(page, bool)
        or page != query.pagination.page
        or not isinstance(per_page, int)
        or isinstance(per_page, bool)
        or per_page != query.pagination.per_page
        or not isinstance(has_previous, bool)
        or not isinstance(has_next, bool)
    ):
        return result
    if total_count is not None and (
        not isinstance(total_count, int) or isinstance(total_count, bool) or total_count < 0
    ):
        return result

    return PageResult(
        items=items,
        page=page,
        per_page=per_page,
        has_previous=has_previous,
        has_next=has_next,
        total_count=total_count,
    )


class ResourceService:
    """Read-only resource service over a `DataSource`.

    Query translation and whitelisting happen upstream (`ResourceQuery`), and
    actually executing the query is the data source's responsibility. The
    service preserves the historical structural page-result contract for PAGE
    pagination and normalizes `detail()`'s "not found" case into a `RakitError`.
    """

    def __init__(self, data_source: DataSource) -> None:
        self._data_source = data_source

    @property
    def data_source(self) -> DataSource:
        return self._data_source

    async def list(self, query: ResourceQuery) -> ResourceListResult:
        result = await self._data_source.list(query)
        return _normalize_legacy_page_result(query, result)

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
