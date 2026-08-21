from __future__ import annotations

import asyncio

from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.filters import Filter, FilterOperator
from rakit_core.identity import RecordIdentity
from rakit_core.query import ResourceQuery
from rakit_tortoise.datasource import TortoiseDataSource
from rakit_tortoise.introspection import UnsupportedTortoiseFieldPolicyError
from tortoise import Tortoise, fields
from tortoise.models import Model


class Widget(Model):
    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=100)
    age = fields.IntField()


async def main() -> None:
    await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["__main__"]})
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
        assert source.fields == ("id", "name", "age")
        assert source.identity_fields == ("id",)

        page = await source.list(
            ResourceQuery.from_params(
                sort="name",
                page=1,
                per_page=2,
                allowed_sort_fields=("name",),
                identity_fields=("id",),
            )
        )
        assert [item.name for item in page.items] == ["alpha", "bravo"]
        assert page.has_next is True
        assert page.total_count == 3

        filtered = await source.list(
            ResourceQuery.from_params(
                page=1,
                per_page=25,
                allowed_sort_fields=("name",),
                identity_fields=("id",),
                filters=(Filter(field="age", operator=FilterOperator.GTE, value=2),),
                search="a",
            )
        )
        assert [item.name for item in filtered.items] == ["bravo", "charlie"]

        record = await source.detail(RecordIdentity(values={"id": 2}))
        assert record.name == "alpha"

        try:
            TortoiseDataSource(
                model=Widget,
                field_policy=ResourceFieldPolicy(search_fields=("age",)),
            )
        except UnsupportedTortoiseFieldPolicyError:
            pass
        else:
            raise AssertionError("non-text search field must fail closed")
    finally:
        await Tortoise.close_connections()


asyncio.run(main())
