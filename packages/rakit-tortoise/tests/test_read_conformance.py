from __future__ import annotations

import asyncio
from dataclasses import dataclass

from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.filters import Filter, FilterOperator
from rakit_core.identity import RecordIdentity
from rakit_core.pagination import LimitOffsetPagination, LimitOffsetResult, PageResult
from rakit_core.query import ResourceQuery
from rakit_core.conformance import run_integration_conformance
from rakit_core.testing.capability_conformance import CANONICAL_CONFORMANCE_SPEC_REGISTRY
from rakit_tortoise.datasource import TortoiseDataSource
from rakit_tortoise.discovery import TORTOISE_INTEGRATION
from tortoise import Tortoise, fields
from tortoise.models import Model


class Widget(Model):
    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=100)
    age = fields.IntField()


@dataclass(slots=True)
class TortoiseReadHarness:
    source: TortoiseDataSource

    async def assert_read_semantics(self) -> None:
        page = await self.source.list(
            ResourceQuery.from_params(
                sort="name",
                page=1,
                per_page=2,
                allowed_sort_fields=("name",),
                identity_fields=("id",),
            )
        )
        assert isinstance(page, PageResult)
        assert [getattr(item, "name") for item in page.items] == ["alpha", "bravo"]
        assert page.has_next is True
        assert page.total_count == 3

        filtered = await self.source.list(
            ResourceQuery.from_params(
                page=1,
                per_page=25,
                allowed_sort_fields=("name",),
                identity_fields=("id",),
                filters=(Filter(field="age", operator=FilterOperator.GTE, value=2),),
                search="a",
            )
        )
        assert [getattr(item, "name") for item in filtered.items] == ["bravo", "charlie"]

        offset = await self.source.list(
            ResourceQuery.from_components(
                pagination=LimitOffsetPagination(offset=1, limit=1),
                sort="name",
                allowed_sort_fields=("name",),
                identity_fields=("id",),
            )
        )
        assert isinstance(offset, LimitOffsetResult)
        assert [getattr(item, "name") for item in offset.items] == ["bravo"]
        assert offset.has_previous is True
        assert offset.has_next is True

        record = await self.source.detail(RecordIdentity(values={"id": 2}))
        assert getattr(record, "name") == "alpha"

        try:
            await self.source.detail(RecordIdentity(values={"id": 999}))
        except RakitError as exc:
            assert exc.code == str(ErrorCode.RESOURCE_NOT_FOUND)
            assert exc.status_code == 404
        else:
            raise AssertionError("missing identity must raise a portable not-found error")


async def _exercise_read_conformance() -> None:
    await Tortoise.init(db_url="sqlite://:memory:", modules={"models": [__name__]})
    await Tortoise.generate_schemas()
    try:
        await Widget.create(name="bravo", age=2)
        await Widget.create(name="alpha", age=1)
        await Widget.create(name="charlie", age=3)
        source = TortoiseDataSource(
            model=Widget,
            field_policy=ResourceFieldPolicy(
                list_fields=("id", "name", "age"),
                detail_fields=("id", "name", "age"),
                filter_fields=("age",),
                search_fields=("name",),
                sort_fields=("name",),
            ),
        )

        result = await run_integration_conformance(
            descriptor=TORTOISE_INTEGRATION,
            harnesses={"persistence.read": TortoiseReadHarness(source)},
            specs=CANONICAL_CONFORMANCE_SPEC_REGISTRY,
        )

        assert result.passed, result.failures
        assert tuple(item.capability for item in result.results) == ("persistence.read",)
    finally:
        await Tortoise.close_connections()


def test_tortoise_read_capability_conforms_with_real_sqlite() -> None:
    asyncio.run(_exercise_read_conformance())
