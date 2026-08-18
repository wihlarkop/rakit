"""Tests for the reusable DataSource contract suite.

These tests prove the suite itself is sound:

- a well-behaved reference adapter passes the entire suite (including the
  write, transaction, concurrency, relationship, and cancellation branches),
- an intentionally broken fake that drops the identity tie-breaker is
  detected by :meth:`assert_stable_pagination`.

The reference adapter is an ordinary in-memory implementation of the public
``DataSource`` protocol -- it is deliberately not a Rakit framework class, so
this also proves the suite has no hidden coupling to adapter internals.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from copy import deepcopy
from typing import Any, ClassVar, cast

import pytest
from rakit_core.datasource import DataSourceCapabilities
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.identity import RecordIdentity
from rakit_core.query import (
    CountPolicy,
    Filter,
    FilterOperator,
    PagePagination,
    PageResult,
    ResourceQuery,
    Sort,
    SortDirection,
)
from rakit_core.relationships import RelationshipCardinality, RelationshipKind, RelationshipMetadata
from rakit_core.testing import DataSourceContractSuite

# Module-level alias: the ``MemoryDataSource`` class below has a method named
# ``list`` which would otherwise shadow the builtin inside class-body type
# annotations. Creating the alias here (where ``list`` is still the builtin)
# keeps the annotations resolvable.
Records = list[dict[str, Any]]

FIXTURE = (
    {
        "id": 1,
        "email": "ada@example.com",
        "name": "Ada Lovelace",
        "group": "engineering",
        "score": 10,
        "version": 1,
    },
    {
        "id": 2,
        "email": "grace@example.com",
        "name": "Grace Hopper",
        "group": "engineering",
        "score": 20,
        "version": 1,
    },
    {
        "id": 3,
        "email": "alan@example.com",
        "name": "Alan Turing",
        "group": "science",
        "score": 30,
        "version": 1,
    },
    {
        "id": 4,
        "email": "linus@example.com",
        "name": "Linus Torvalds",
        "group": "science",
        "score": 40,
        "version": 1,
    },
    {
        "id": 5,
        "email": "mary@example.com",
        "name": "Mary Jackson",
        "group": "operations",
        "score": 50,
        "version": 1,
    },
    {
        "id": 6,
        "email": "katherine@example.com",
        "name": "Katherine Johnson",
        "group": "engineering",
        "score": 60,
        "version": 1,
    },
    {
        "id": 7,
        "email": "dorothy@example.com",
        "name": "Dorothy Vaughan",
        "group": "operations",
        "score": 70,
        "version": 1,
    },
)


def _coercible(value: object) -> bool:
    return isinstance(value, str | int | float | bool | type(None))


class MemoryDataSource:
    """A full-featured in-memory reference implementation of ``DataSource``.

    Supports filtering, search, deterministic sorting with identity
    tie-breakers, offset pagination, exact/deferred/disabled counts, writes,
    rollback-on-exception transactions, and optimistic concurrency.
    """

    capabilities: DataSourceCapabilities
    identity_fields = ("id",)
    fields = ("id", "email", "name", "group", "score", "version")
    relationship_metadata: ClassVar[Mapping[str, RelationshipMetadata]] = {
        "manager": RelationshipMetadata(
            relationship_id="manager",
            kind=RelationshipKind.MANY_TO_ONE,
            cardinality=RelationshipCardinality.TO_ONE,
            nullable=True,
            ordered=False,
            self_referential=False,
            view_only=False,
            has_secondary=False,
            cascade_delete=False,
            delete_orphan=False,
        )
    }
    cancellation_declaration = "cooperative"

    def __init__(self, records: Sequence[Mapping[str, Any]]) -> None:
        self._records = [dict(record) for record in records]
        self._next_id = max(int(record["id"]) for record in self._records) + 1
        self.capabilities = DataSourceCapabilities(
            read=True,
            create=True,
            update=True,
            delete=True,
            transactions=True,
            optimistic_concurrency=True,
        )

    # -- query translation ---------------------------------------------------

    def _matches_filter(self, record: Mapping[str, Any], filter_: Filter) -> bool:
        value = record.get(filter_.field)
        if not _coercible(filter_.value) or not _coercible(value):
            raise RakitError(
                code=ErrorCode.VALIDATION_FAILED,
                message="Query field is not allowed",
                status_code=400,
            )
        operator = filter_.operator
        if operator is FilterOperator.EQ:
            return value == filter_.value
        if operator is FilterOperator.NEQ:
            return value != filter_.value
        if operator is FilterOperator.LT:
            return value is not None and value < filter_.value
        if operator is FilterOperator.LTE:
            return value is not None and value <= filter_.value
        if operator is FilterOperator.GT:
            return value is not None and value > filter_.value
        if operator is FilterOperator.GTE:
            return value is not None and value >= filter_.value
        if operator is FilterOperator.CONTAINS:
            return (
                isinstance(value, str) and isinstance(filter_.value, str) and filter_.value in value
            )
        if operator is FilterOperator.IN:
            values = filter_.value if isinstance(filter_.value, list | tuple | set) else ()
            return value in values
        if operator is FilterOperator.IS_NULL:
            return (value is None) == bool(filter_.value)
        return False

    def _filtered(self, query: ResourceQuery) -> Records:
        rows = list(self._records)
        for filter_ in query.filters:
            rows = [row for row in rows if self._matches_filter(row, filter_)]
        if query.search:
            term = query.search.lower()
            rows = [
                row
                for row in rows
                if any(isinstance(value, str) and term in value.lower() for value in row.values())
            ]
        return rows

    def _sorted(self, rows: Records, query: ResourceQuery) -> Records:
        specs = [*query.sorting, *query.identity_tie_breakers]
        sorted_fields = {spec.field for spec in specs}
        for field in self.identity_fields:
            if field not in sorted_fields:
                specs.append(Sort(field=field))
        result = rows
        for spec in reversed(specs):
            result = sorted(
                result,
                key=lambda row: row.get(spec.field),
                reverse=spec.direction is SortDirection.DESC,
            )
        return result

    # -- DataSource protocol --------------------------------------------------

    async def list(self, query: ResourceQuery) -> PageResult:
        rows = self._sorted(self._filtered(query), query)
        pagination = query.pagination
        if not isinstance(pagination, PagePagination):
            raise ValueError("MemoryDataSource supports page-number pagination only")
        offset = pagination.offset
        per_page = pagination.per_page
        items = tuple(rows[offset : offset + per_page])
        has_next = offset + per_page < len(rows)
        total_count = len(rows) if query.count_policy is CountPolicy.EXACT else None
        return PageResult(
            items=items,
            page=pagination.page,
            per_page=per_page,
            has_previous=pagination.page > 1,
            has_next=has_next,
            total_count=total_count,
        )

    async def count(self, query: ResourceQuery) -> int:
        return len(self._filtered(query))

    def _validate_identity(self, identity: RecordIdentity) -> None:
        for field in identity.values:
            if field not in self.identity_fields:
                raise RakitError(
                    code=ErrorCode.VALIDATION_FAILED,
                    message="Invalid identity",
                    status_code=400,
                )
        for field in self.identity_fields:
            if field not in identity.values:
                raise RakitError(
                    code=ErrorCode.VALIDATION_FAILED,
                    message="Invalid identity",
                    status_code=400,
                )

    async def detail(self, identity: RecordIdentity) -> object | None:
        self._validate_identity(identity)
        for record in self._records:
            if all(record[field] == identity.values[field] for field in self.identity_fields):
                return deepcopy(record)
        return None

    # -- write / transaction / concurrency support ----------------------------

    async def create_record(self, values: Mapping[str, Any]) -> RecordIdentity:
        record = dict(values)
        if self.identity_fields[0] not in record:
            record[self.identity_fields[0]] = self._next_id
            self._next_id += 1
        record.setdefault("version", 1)
        if any(record[field] == record[self.identity_fields[0]] for field in self.identity_fields):
            existing = [
                row
                for row in self._records
                if row[self.identity_fields[0]] == record[self.identity_fields[0]]
            ]
            if existing:
                raise RakitError(
                    code=ErrorCode.RESOURCE_CONFLICT,
                    message="Record already exists",
                    status_code=409,
                )
        self._records.append(record)
        return RecordIdentity(values={field: record[field] for field in self.identity_fields})

    def _find(self, identity: RecordIdentity) -> dict[str, Any]:
        self._validate_identity(identity)
        for record in self._records:
            if all(record[field] == identity.values[field] for field in self.identity_fields):
                return record
        raise RakitError(
            code=ErrorCode.RESOURCE_NOT_FOUND,
            message="Record not found",
            status_code=404,
        )

    async def update_record(
        self,
        identity: RecordIdentity,
        values: Mapping[str, Any],
        *,
        expected_version: object = None,
    ) -> None:
        record = self._find(identity)
        if expected_version is not None and record["version"] != expected_version:
            raise RakitError(
                code=ErrorCode.RESOURCE_CONFLICT,
                message="Stale record version",
                status_code=409,
            )
        for field, value in values.items():
            if field not in self.identity_fields and field != "version":
                record[field] = value
        record["version"] = int(record.get("version", 1)) + 1

    async def delete_record(
        self,
        identity: RecordIdentity,
        *,
        expected_version: object = None,
    ) -> None:
        record = self._find(identity)
        if expected_version is not None and record["version"] != expected_version:
            raise RakitError(
                code=ErrorCode.RESOURCE_CONFLICT,
                message="Stale record version",
                status_code=409,
            )
        self._records.remove(record)

    async def record_version(self, record: object) -> object:
        return cast(dict[str, Any], record)["version"]

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        snapshot = deepcopy(self._records)
        try:
            yield
        except BaseException:
            self._records = snapshot
            raise


class FullContract(DataSourceContractSuite):
    capabilities = DataSourceCapabilities(
        read=True,
        create=True,
        update=True,
        delete=True,
        transactions=True,
        optimistic_concurrency=True,
    )
    field_policy = ResourceFieldPolicy(
        list_fields=("id", "email", "name", "group", "score", "version"),
        detail_fields=("id", "email", "name", "group", "score", "version"),
        filter_fields=("email", "group", "score"),
        search_fields=("email", "name"),
        sort_fields=("email", "name", "group", "score"),
    )
    identity_fields = ("id",)
    sort_group_field = "group"
    cancellation_declaration = "cooperative"
    requires_transactions = True
    requires_writes = True
    requires_concurrency = True

    def __init__(self) -> None:
        self._source = MemoryDataSource([deepcopy(dict(record)) for record in FIXTURE])

    async def make_datasource(self) -> MemoryDataSource:
        return self._source

    async def fixture_records(self) -> tuple[Mapping[str, object], ...]:
        return tuple(FIXTURE)

    async def create_record(self, values: Mapping[str, object]) -> RecordIdentity:
        return await self._source.create_record(values)

    async def update_record(
        self,
        identity: RecordIdentity,
        values: Mapping[str, object],
        *,
        expected_version: object = None,
    ) -> None:
        await self._source.update_record(identity, values, expected_version=expected_version)

    async def delete_record(
        self,
        identity: RecordIdentity,
        *,
        expected_version: object = None,
    ) -> None:
        await self._source.delete_record(identity, expected_version=expected_version)

    async def record_version(self, record: object) -> object:
        return await self._source.record_version(record)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        async with self._source.transaction():
            yield


@pytest.mark.anyio
async def test_reference_adapter_passes_the_entire_contract_suite() -> None:
    await FullContract().run_all()


@pytest.mark.anyio
async def test_read_only_capabilities_skip_write_branches() -> None:
    class ReadOnly(DataSourceContractSuite):
        identity_fields = ("id",)

        async def make_datasource(self) -> MemoryDataSource:
            return MemoryDataSource([deepcopy(dict(record)) for record in FIXTURE])

        async def fixture_records(self) -> tuple[Mapping[str, object], ...]:
            return tuple(FIXTURE)

    suite = ReadOnly()
    assert await suite.datasource() is not None
    with pytest.raises(pytest.skip.Exception):
        await suite.assert_writes()
    with pytest.raises(pytest.skip.Exception):
        await suite.assert_transactions()
    with pytest.raises(pytest.skip.Exception):
        await suite.assert_concurrency()


class BrokenDataSourceThatDropsIdentityTieBreaker:
    """Simulates the classic adapter bug: sorting only by the user-requested
    field and dropping the identity tie-breaker, so equal sort values resolve
    to a different order on different pages and offset pagination repeats or
    loses records across page boundaries."""

    identity_fields = ("id",)
    fields = ("id", "name")
    capabilities: DataSourceCapabilities

    def __init__(self) -> None:
        self.capabilities = DataSourceCapabilities(read=True)
        self._records = [
            {"id": 1, "name": "a"},
            {"id": 3, "name": "a"},
            {"id": 2, "name": "b"},
            {"id": 4, "name": "b"},
            {"id": 5, "name": "c"},
            {"id": 6, "name": "c"},
        ]

    async def list(self, query: ResourceQuery) -> PageResult:
        pagination = query.pagination
        if not isinstance(pagination, PagePagination):
            raise ValueError("BrokenDataSource supports page-number pagination only")
        page = pagination.page
        per_page = pagination.per_page
        if query.sorting:
            rows = sorted(self._records, key=lambda row: row[query.sorting[0].field])
            if page % 2 == 0:
                rows = rows[1:] + rows[:1]
        else:
            rows = sorted(self._records, key=lambda row: row["id"])
        offset = pagination.offset
        items = tuple(rows[offset : offset + per_page])
        total = len(self._records)
        return PageResult(
            items=items,
            page=page,
            per_page=per_page,
            has_previous=page > 1,
            has_next=offset + per_page < total,
            total_count=None,
        )

    async def count(self, query: ResourceQuery) -> int:
        return len(self._records)

    async def detail(self, identity: RecordIdentity) -> object | None:
        for record in self._records:
            if record["id"] == identity.values["id"]:
                return record
        return None


class BrokenDataSourceContract(DataSourceContractSuite):
    identity_fields = ("id",)
    sort_group_field = "name"

    async def make_datasource(self) -> BrokenDataSourceThatDropsIdentityTieBreaker:
        return BrokenDataSourceThatDropsIdentityTieBreaker()

    async def fixture_records(self) -> tuple[Mapping[str, object], ...]:
        return tuple(
            dict(record) for record in BrokenDataSourceThatDropsIdentityTieBreaker()._records
        )


@pytest.mark.anyio
async def test_broken_source_fails_stable_pagination_contract() -> None:
    suite = BrokenDataSourceContract()
    with pytest.raises(AssertionError):
        await suite.assert_stable_pagination()


@pytest.mark.anyio
async def test_broken_source_still_passes_basic_pagination_bounds() -> None:
    suite = BrokenDataSourceContract()
    await suite.assert_pagination()
