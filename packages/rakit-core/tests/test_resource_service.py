import pytest
from rakit_core.datasource import DataSourceCapabilities
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.identity import RecordIdentity
from rakit_core.query import PageResult, ResourceQuery
from rakit_core.resources import ResourceService


class FakeDataSource:
    capabilities = DataSourceCapabilities(read=True)
    fields = ("id", "name")
    identity_fields = ("id",)

    async def list(self, query: ResourceQuery) -> PageResult:
        return PageResult(
            items=({"id": 1, "name": "Ada"},),
            page=1,
            per_page=25,
            has_previous=False,
            has_next=False,
            total_count=1,
        )

    async def count(self, query: ResourceQuery) -> int:
        return 1

    async def detail(self, identity: RecordIdentity):
        return {"id": identity.values["id"], "name": "Ada"}


class MissingDataSource:
    capabilities = DataSourceCapabilities(read=True)
    fields = ("id", "name")
    identity_fields = ("id",)

    async def list(self, query: ResourceQuery) -> PageResult:
        return PageResult(
            items=(),
            page=1,
            per_page=25,
            has_previous=False,
            has_next=False,
            total_count=0,
        )

    async def count(self, query: ResourceQuery) -> int:
        return 0

    async def detail(self, identity: RecordIdentity):
        return None


async def test_resource_service_reads() -> None:
    service = ResourceService(FakeDataSource())
    result = await service.list(ResourceQuery())
    assert isinstance(result, PageResult)
    assert result.total_count == 1
    assert await service.detail(RecordIdentity(values={"id": 1})) == {"id": 1, "name": "Ada"}


async def test_resource_service_detail_not_found() -> None:
    service = ResourceService(MissingDataSource())
    with pytest.raises(RakitError) as exc_info:
        await service.detail(RecordIdentity(values={"id": 1}))

    error = exc_info.value
    assert error.code == ErrorCode.RESOURCE_NOT_FOUND
    assert error.status_code == 404
