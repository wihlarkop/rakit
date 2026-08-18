from dataclasses import dataclass
from typing import cast

import pytest
from rakit_core.datasource import DataSource, DataSourceCapabilities
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.identity import RecordIdentity
from rakit_core.pagination import PagePagination, PageResult, ResourceListResult
from rakit_core.query import ResourceQuery
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


@dataclass(frozen=True)
class LegacyPage:
    items: tuple[dict[str, object], ...]
    page: int
    per_page: int
    has_previous: bool
    has_next: bool
    total_count: int | None


class LegacyPageDataSource:
    capabilities = DataSourceCapabilities(read=True)
    fields = ("id", "name")
    identity_fields = ("id",)

    async def list(self, query: ResourceQuery) -> ResourceListResult:
        pagination = query.pagination
        assert isinstance(pagination, PagePagination)
        legacy = LegacyPage(
            items=({"id": 1, "name": "Ada"},),
            page=pagination.page,
            per_page=pagination.per_page,
            has_previous=False,
            has_next=False,
            total_count=1,
        )
        return cast(ResourceListResult, legacy)

    async def count(self, query: ResourceQuery) -> int:
        del query
        return 1

    async def detail(self, identity: RecordIdentity):
        return {"id": identity.values["id"], "name": "Ada"}


async def test_resource_service_reads() -> None:
    service = ResourceService(FakeDataSource())
    result = await service.list(ResourceQuery())
    assert isinstance(result, PageResult)
    assert result.total_count == 1
    assert await service.detail(RecordIdentity(values={"id": 1})) == {"id": 1, "name": "Ada"}


async def test_resource_service_normalizes_legacy_structural_page_result() -> None:
    service = ResourceService(cast(DataSource, LegacyPageDataSource()))
    result = await service.list(ResourceQuery(pagination=PagePagination(page=1, per_page=25)))

    assert isinstance(result, PageResult)
    assert result.items == ({"id": 1, "name": "Ada"},)
    assert result.page == 1
    assert result.per_page == 25
    assert result.total_count == 1


async def test_resource_service_detail_not_found() -> None:
    service = ResourceService(MissingDataSource())
    with pytest.raises(RakitError) as exc_info:
        await service.detail(RecordIdentity(values={"id": 1}))

    error = exc_info.value
    assert error.code == ErrorCode.RESOURCE_NOT_FOUND
    assert error.status_code == 404
