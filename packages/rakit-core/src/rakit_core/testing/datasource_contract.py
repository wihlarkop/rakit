"""Reusable, capability-aware contract suite for third-party ``DataSource`` adapters.

The suite is backend-neutral: it drives a data source exclusively through the
public read contract in :mod:`rakit_core.datasource` (``list`` / ``count`` /
``detail``), the query model in :mod:`rakit_core.query`, and identities in
:mod:`rakit_core.identity`. It never imports adapter implementation classes.

An adapter author subclasses :class:`DataSourceContractSuite`, implements the
required hooks (:meth:`DataSourceContractSuite.make_datasource` and
:meth:`DataSourceContractSuite.fixture_records`), optionally declares
capabilities and a field policy, and then runs the suite from a normal pytest
test::

    class MyContract(DataSourceContractSuite):
        capabilities = DataSourceCapabilities(read=True)
        field_policy = ResourceFieldPolicy(
            list_fields=("id", "name"),
            detail_fields=("id", "name"),
            filter_fields=("name",),
            search_fields=("name",),
            sort_fields=("name",),
        )
        identity_fields = ("id",)

        async def make_datasource(self) -> DataSource:
            return MyDataSource()  # backend already contains fixture_records()

        async def fixture_records(self):
            return (
                {"id": 1, "name": "alpha"},
                {"id": 2, "name": "beta"},
            )

    @pytest.mark.anyio
    async def test_contract() -> None:
        await DataSourceContractSuiteSubclass().run_all()

Read-only features (list/detail/not-found/identity/filter/search/sort/
pagination/count/error translation) always run when the field policy declares
the required fields. Capability-gated features (writes, transactions,
optimistic concurrency, relationship metadata, cancellation declarations) run
only when the suite declares them, so a read-only adapter is never forced to
implement write machinery it does not provide.

``pytest`` is only required when the suite is actually used from tests; the
package imports cleanly without it.
"""

from __future__ import annotations

import hashlib
import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress
from typing import TYPE_CHECKING, Any, cast

from rakit_core.datasource import DataSource, DataSourceCapabilities
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.identity import RecordIdentity
from rakit_core.query import (
    CountPolicy,
    Filter,
    FilterOperator,
    OffsetPagination,
    ResourceQuery,
    Sort,
)

if TYPE_CHECKING:
    pass

with suppress(ImportError):  # pragma: no cover - exercised only without pytest installed
    import pytest as _pytest

_pytest_available = "_pytest" in globals()

_SKIP_EXCEPTION_TYPE: type[BaseException] = (
    cast(Any, _pytest).skip.Exception if _pytest_available else RuntimeError
)

__all__ = ["DataSourceContractSuite"]


def _skip(message: str) -> None:
    if _pytest_available:
        cast(Any, _pytest).skip(message)
    raise RuntimeError(f"{message} (install pytest to run Rakit contract suites)")


def _require(condition: bool, message: str) -> None:
    if not condition:
        _skip(message)


def _record_field(record: object, field: str) -> object:
    if isinstance(record, Mapping):
        return dict(record)[field]
    return getattr(record, field)


def _sha256_hex_digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class DataSourceContractSuite(ABC):
    """Backend-neutral assertion suite for a ``DataSource`` adapter.

    Subclasses implement the hooks and may declare the capability surface. The
    suite is *capability aware*: a feature is exercised only when both the
    declaration (capability or field policy) and the corresponding hook data
    are available.

    Required hooks
    --------------
    ``async make_datasource()``
        Build a new ``DataSource`` whose backend is already populated with
        exactly the records returned by :meth:`fixture_records`. Called once
        per suite instance and cached.
    ``async fixture_records()``
        Return the deterministic expected dataset as a tuple of mappings whose
        keys are field names. Every mapping must contain all ``identity_fields``
        plus every field the field policy and feature flags reference.

    Declared configuration (class attributes)
    -----------------------------------------
    ``capabilities``
        :class:`DataSourceCapabilities`. Defaults to read-only.
    ``field_policy``
        :class:`ResourceFieldPolicy`. Lists which fields filtering, search, and
        sorting may use. A feature is skipped when its field list is empty.
    ``identity_fields``
        Non-empty tuple of identity field names.
    ``sort_group_field``
        Optional sortable field that contains at least one duplicate value in
        the fixture. Required to exercise identity tie-breaker behavior.
    ``cancellation_declaration``
        Optional documented string declaring cooperative cancellation support.
        When set, the data source must expose the same attribute.
    ``version_field``
        Name of the optimistic-concurrency version column. Excluded from plain
        write updates (the adapter owns its advancement). Defaults to
        ``"version"``.
    ``requires_transactions`` / ``requires_writes`` / ``requires_concurrency``
        Set these to ``True`` when the adapter declares the corresponding
        capability and implement the associated write/transaction hooks.

    Optional read hooks
    -------------------
    ``record_field(record, field)``
        Defaults to ``record[field]`` for mappings and ``getattr`` otherwise.
    ``datasource_identity_for(record)``
        Returns the :class:`RecordIdentity` for a record. Defaults to
        ``None``; when implemented, identity round-trips are checked through
        it too.

    Write hooks (only invoked when the matching capability is enabled)
    -----------------------------------------------------------------
    ``async create_record(values) -> RecordIdentity``
    ``async update_record(identity, values, *, expected_version=None)``
    ``async delete_record(identity, *, expected_version=None)``
    ``async record_version(record)``
    ``transaction()``
        Async context manager whose ``__aexit__`` rolls back when the body
        raises.
    """

    capabilities: DataSourceCapabilities = DataSourceCapabilities()
    field_policy: ResourceFieldPolicy = ResourceFieldPolicy()
    identity_fields: tuple[str, ...] = ()
    sort_group_field: str | None = None
    cancellation_declaration: str | None = None
    version_field: str = "version"
    requires_transactions: bool = False
    requires_writes: bool = False
    requires_concurrency: bool = False

    _datasource: DataSource | None = None

    # ------------------------------------------------------------------
    # Hooks
    # ------------------------------------------------------------------

    @abstractmethod
    async def make_datasource(self) -> DataSource:
        """Return a ``DataSource`` whose backend contains the fixture records."""

    @abstractmethod
    async def fixture_records(self) -> tuple[Mapping[str, object], ...]:
        """Return the deterministic expected dataset for the contract run."""

    def record_field(self, record: object, field: str) -> object:
        return _record_field(record, field)

    def datasource_identity_for(self, record: object) -> RecordIdentity | None:
        identity_for = getattr(self._datasource_or_none(), "identity_for", None)
        if callable(identity_for):
            identity = identity_for(record)
            if isinstance(identity, RecordIdentity):
                return identity
        return None

    # Write hooks (raise NotImplementedError unless a capability is enabled).
    async def create_record(self, values: Mapping[str, object]) -> RecordIdentity:
        raise NotImplementedError("create_record hook required for write-capable suites")

    async def update_record(
        self,
        identity: RecordIdentity,
        values: Mapping[str, object],
        *,
        expected_version: object = None,
    ) -> None:
        raise NotImplementedError("update_record hook required for write-capable suites")

    async def delete_record(
        self,
        identity: RecordIdentity,
        *,
        expected_version: object = None,
    ) -> None:
        raise NotImplementedError("delete_record hook required for write-capable suites")

    async def record_version(self, record: object) -> object:
        raise NotImplementedError("record_version hook required for concurrency-capable suites")

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        raise NotImplementedError("transaction hook required for transaction-capable suites")
        yield

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _datasource_or_none(self) -> DataSource | None:
        return self._datasource

    async def datasource(self) -> DataSource:
        if self._datasource is None:
            if not self.identity_fields:
                raise RuntimeError("DataSourceContractSuite.identity_fields must be non-empty")
            self._datasource = await self.make_datasource()
        return self._datasource

    async def _records(self) -> tuple[Mapping[str, object], ...]:
        return tuple(await self.fixture_records())

    async def _identities(self) -> tuple[RecordIdentity, ...]:
        records = await self._records()
        return tuple(self._identity_for_values(self._values(record)) for record in records)

    def _values(self, record: Mapping[str, object]) -> Mapping[str, object]:
        return record

    def _identity_for_values(self, values: Mapping[str, object]) -> RecordIdentity:
        identity_values: dict[str, int | str | uuid.UUID] = {}
        for field in self.identity_fields:
            value = values[field]
            if isinstance(value, uuid.UUID) or (
                isinstance(value, int) and not isinstance(value, bool)
            ):
                identity_values[field] = value  # type: ignore[assignment]
            else:
                identity_values[field] = str(value)
        return RecordIdentity(values=identity_values)

    async def _identity_sequence(self, record: Mapping[str, object]) -> tuple[object, ...]:
        return tuple(record[field] for field in self.identity_fields)

    async def _bogus_identity(self) -> RecordIdentity:
        records = await self._records()
        values: dict[str, int | str | uuid.UUID] = {}
        for field in self.identity_fields:
            existing = [record[field] for record in records if record.get(field) is not None]
            if existing and all(isinstance(value, int) for value in existing):
                values[field] = max(existing, default=0) + 1  # type: ignore[arg-type]
            else:
                values[field] = uuid.uuid4()
        return RecordIdentity(values=values)

    async def _identity_ordering(
        self, records: Sequence[Mapping[str, object]]
    ) -> list[tuple[object, ...]]:
        return sorted(await self._identity_sequences(records))

    async def _identity_sequences(
        self, records: Sequence[Mapping[str, object]]
    ) -> list[tuple[object, ...]]:
        return [await self._identity_sequence(record) for record in records]

    def _field_identity_sort_key(self, record: Mapping[str, object]) -> tuple[object, ...]:
        group = record.get(self.sort_group_field) if self.sort_group_field is not None else None
        identity_values = tuple(record[field] for field in self.identity_fields)
        return (group, identity_values)

    # ------------------------------------------------------------------
    # Assertions
    # ------------------------------------------------------------------

    async def assert_list_detail_and_not_found(self) -> None:
        """List returns the whole fixture and detail resolves known and unknown identities."""
        ds = await self.datasource()
        records = await self._records()
        page = await ds.list(ResourceQuery(count_policy=CountPolicy.EXACT))
        assert page.items, "expected a non-empty fixture"
        assert len(page.items) == len(records), "list must return exactly the fixture records"
        listed = {
            tuple(self.record_field(item, field) for field in self.identity_fields)
            for item in page.items
        }
        expected = {await self._identity_sequence(record) for record in records}
        assert listed == expected, "list returned identities outside the fixture"

        first = records[0]
        identity = self._identity_for_values(first)
        detail = await ds.detail(identity)
        assert detail is not None, "detail must resolve a known identity"
        assert self.record_field(detail, self.identity_fields[0]) == first[self.identity_fields[0]]

        missing = await ds.detail(await self._bogus_identity())
        assert missing is None, "detail must return None for an unknown identity"

    async def assert_identity_round_trip(self) -> None:
        """Identities are stable and, when the adapter provides ``identity_for``, round-trip."""
        ds = await self.datasource()
        records = await self._records()
        for record in records:
            identity = self._identity_for_values(record)
            detail = await ds.detail(identity)
            assert detail is not None, f"detail must resolve identity {identity.values}"
            inferred = self.datasource_identity_for(detail)
            if inferred is not None:
                assert inferred.values == identity.values, (
                    "adapter identity_for must round-trip the identity it was resolved with"
                )

    async def assert_filtering(self) -> None:
        """Filters narrow the list to exactly the matching fixture records."""
        _require(bool(self.field_policy.filter_fields), "suite declares no filter_fields")
        ds = await self.datasource()
        records = await self._records()
        filter_field = self.field_policy.filter_fields[0]
        sample = next(record for record in records if record.get(filter_field) is not None)
        value = sample[filter_field]
        page = await ds.list(
            ResourceQuery(
                filters=(Filter(field=filter_field, operator=FilterOperator.EQ, value=value),)
            )
        )
        listed = {
            tuple(self.record_field(item, field) for field in self.identity_fields)
            for item in page.items
        }
        expected = {
            await self._identity_sequence(record)
            for record in records
            if record.get(filter_field) == value
        }
        assert listed == expected, "EQ filter must return exactly the matching fixture records"

    async def assert_search(self) -> None:
        """Free-text search matches the fixture's substring semantics."""
        _require(bool(self.field_policy.search_fields), "suite declares no search_fields")
        ds = await self.datasource()
        records = await self._records()
        search_field = self.field_policy.search_fields[0]

        def contains(term: str, value: object) -> bool:
            return isinstance(value, str) and term.lower() in value.lower()

        unique: set[str] = set()
        for record in records:
            value = record.get(search_field)
            if isinstance(value, str) and value:
                unique.add(value.lower())
        assert len(unique) >= 2, "fixture search field needs at least two distinct values"
        term = next(value for value in unique if value)
        page = await ds.list(ResourceQuery(search=term))
        listed = {
            tuple(self.record_field(item, field) for field in self.identity_fields)
            for item in page.items
        }
        expected = {
            await self._identity_sequence(record)
            for record in records
            if contains(term, record.get(search_field))
        }
        assert listed == expected, "search must return exactly the matching fixture records"

    async def assert_deterministic_sorting(self) -> None:
        """Repeated identical queries return a stable, deterministic order."""
        _require(bool(self.field_policy.sort_fields), "suite declares no sort_fields")
        ds = await self.datasource()
        sort_field = self.field_policy.sort_fields[0]
        query = ResourceQuery(
            sorting=(Sort(field=sort_field),),
            identity_tie_breakers=tuple(Sort(field=field) for field in self.identity_fields),
        )
        first = [
            tuple(self.record_field(item, field) for field in self.identity_fields)
            for item in (await ds.list(query)).items
        ]
        second = [
            tuple(self.record_field(item, field) for field in self.identity_fields)
            for item in (await ds.list(query)).items
        ]
        assert first == second, "identical queries must return an identical order"

    async def assert_identity_tie_breaker(self) -> None:
        """Sorting ties are broken by the identity field, not left unstable."""
        _require(self.sort_group_field is not None, "suite declares no sort_group_field")
        assert self.sort_group_field is not None
        ds = await self.datasource()
        records = await self._records()
        group_field = self.sort_group_field
        group_values = [record.get(group_field) for record in records]
        assert len(set(group_values)) < len(records), (
            "sort_group_field must have ties in the fixture"
        )

        query = ResourceQuery(
            sorting=(Sort(field=group_field),),
            identity_tie_breakers=tuple(Sort(field=field) for field in self.identity_fields),
        )
        page = await ds.list(query)
        listed = [
            tuple(self.record_field(item, field) for field in self.identity_fields)
            for item in page.items
        ]
        ordered = sorted(records, key=self._field_identity_sort_key)
        expected = [await self._identity_sequence(record) for record in ordered]
        assert listed == expected, "ties must be broken by the identity field in ascending order"

    async def assert_pagination(self) -> None:
        """Offset pagination returns complete, non-overlapping pages."""
        ds = await self.datasource()
        records = await self._records()
        total = len(records)
        assert total >= 3, "fixture needs at least three records for pagination"
        per_page = 2
        seen: list[tuple[object, ...]] = []
        page_number = 1
        while True:
            page = await ds.list(
                ResourceQuery(
                    pagination=OffsetPagination(page=page_number, per_page=per_page),
                    count_policy=CountPolicy.DISABLED,
                )
            )
            seen.extend(
                tuple(self.record_field(item, field) for field in self.identity_fields)
                for item in page.items
            )
            assert page.page == page_number
            assert page.has_previous == (page_number > 1)
            assert page.has_next == (page_number * per_page < total)
            if not page.has_next:
                break
            page_number += 1
        assert len(seen) == total, "pagination must return every record exactly once"
        assert len(set(seen)) == total, "pagination must not duplicate identities across pages"

    async def assert_stable_pagination(self) -> None:
        """Stable ordering holds across pagination boundaries.

        This is the contract that fails when an adapter drops the identity
        tie-breaker from its ORDER BY: with a sort field that contains ties,
        offset pagination then repeats or drops records across pages.
        """
        ds = await self.datasource()
        records = await self._records()
        assert len(records) >= 4, "fixture needs at least four records for stable pagination"
        if self.sort_group_field is not None:
            group_values = [record.get(self.sort_group_field) for record in records]
            assert len(set(group_values)) < len(records), (
                "sort_group_field must have ties in the fixture"
            )

        sort_field = self.sort_group_field or self.field_policy.sort_fields[0]
        per_page = 2
        seen: list[tuple[object, ...]] = []
        page_number = 1
        while True:
            page = await ds.list(
                ResourceQuery(
                    sorting=(Sort(field=sort_field),),
                    identity_tie_breakers=tuple(
                        Sort(field=field) for field in self.identity_fields
                    ),
                    pagination=OffsetPagination(page=page_number, per_page=per_page),
                    count_policy=CountPolicy.DISABLED,
                )
            )
            seen.extend(
                tuple(self.record_field(item, field) for field in self.identity_fields)
                for item in page.items
            )
            if not page.has_next:
                break
            page_number += 1

        assert len(seen) == len(records), (
            "stable pagination must return every record exactly once "
            f"(got {len(seen)} records over {page_number} pages)"
        )
        assert len(set(seen)) == len(records), (
            "stable pagination must not duplicate identities across pages"
        )
        ordered = sorted(records, key=self._field_identity_sort_key)
        expected = [await self._identity_sequence(record) for record in ordered]
        assert seen == expected, (
            "pagination order must equal the declared sort with identity tie-breakers"
        )

    async def assert_count_policy_semantics(self) -> None:
        """Count policies behave as declared: exact counts, deferred, disabled."""
        ds = await self.datasource()
        records = await self._records()
        total = len(records)
        exact = await ds.list(ResourceQuery(count_policy=CountPolicy.EXACT))
        assert exact.total_count == total, "EXACT count must report the full filtered total"
        deferred = await ds.list(ResourceQuery(count_policy=CountPolicy.DEFERRED))
        assert deferred.total_count is None, "DEFERRED count must not run a total count"
        assert len(deferred.items) == total
        disabled = await ds.list(ResourceQuery(count_policy=CountPolicy.DISABLED))
        assert disabled.total_count is None, "DISABLED count must not run a total count"
        assert len(disabled.items) == total
        counted = await ds.count(ResourceQuery(count_policy=CountPolicy.EXACT))
        assert counted == total, "count() must return the exact filtered total"

    async def assert_transactions(self) -> None:
        """A transaction rolls back its writes when the body raises."""
        _require(self.capabilities.transactions, "capabilities.transactions is disabled")
        _require(self.requires_transactions, "suite must opt in with requires_transactions=True")
        ds = await self.datasource()
        values: dict[str, object] = {
            field: record[field] for record in (await self._records())[:1] for field in record
        }
        values[self.identity_fields[0]] = self._generated_identity_value(values)
        identity = self._identity_for_values(values)

        class _Rollback(Exception):
            pass

        try:
            async with self.transaction():
                await self.create_record(values)
                raise _Rollback()
        except _Rollback:
            pass
        assert await ds.detail(identity) is None, (
            "a rolled-back transaction must not persist its writes"
        )

    async def assert_writes(self) -> None:
        """Create/update/delete round-trip through the read path."""
        _require(
            self.capabilities.create or self.capabilities.update or self.capabilities.delete,
            "capabilities declare no write support",
        )
        _require(self.requires_writes, "suite must opt in with requires_writes=True")
        ds = await self.datasource()
        template = dict((await self._records())[0])
        values = dict(template)
        values[self.identity_fields[0]] = self._generated_identity_value(values)
        identity = await self.create_record(values)
        assert await ds.detail(identity) is not None, "create_record must persist the record"

        update_values = {
            field: f"{field}-updated"
            for field in values
            if field not in self.identity_fields and field != self.version_field
        }
        await self.update_record(identity, update_values)
        detail = await ds.detail(identity)
        assert detail is not None
        sample_field = next(iter(update_values))
        assert self.record_field(detail, sample_field) == update_values[sample_field], (
            "update_record must persist its changes"
        )

        await self.delete_record(identity)
        assert await ds.detail(identity) is None, "delete_record must remove the record"

    async def assert_concurrency(self) -> None:
        """A stale expected version must not silently overwrite newer state."""
        _require(
            self.capabilities.optimistic_concurrency,
            "capabilities.optimistic_concurrency is disabled",
        )
        _require(self.requires_concurrency, "suite must opt in with requires_concurrency=True")
        ds = await self.datasource()
        template = dict((await self._records())[0])
        values = dict(template)
        values[self.identity_fields[0]] = self._generated_identity_value(values)
        identity = await self.create_record(values)
        detail = await ds.detail(identity)
        assert detail is not None
        original_version = await self.record_version(detail)

        await self.update_record(identity, {}, expected_version=original_version)
        detail_after = await ds.detail(identity)
        assert detail_after is not None
        newer_version = await self.record_version(detail_after)
        assert newer_version != original_version, "a successful update must advance the version"

        try:
            await self.update_record(identity, {}, expected_version=original_version)
        except RakitError as exc:
            assert exc.code == ErrorCode.RESOURCE_CONFLICT, (
                "a stale expected version must raise resource.conflict"
            )
            assert exc.status_code == 409
        else:
            raise AssertionError("a stale expected version must raise a concurrency conflict")

    async def assert_relationships(self) -> None:
        """Exposed relationship metadata is structurally sound."""
        ds = await self.datasource()
        metadata = getattr(ds, "relationship_metadata", None)
        _require(metadata is not None, "data source exposes no relationship_metadata")
        from rakit_core.relationships import RelationshipMetadata

        assert isinstance(metadata, Mapping), "relationship_metadata must be a mapping"
        for relationship_id, entry in metadata.items():
            assert isinstance(entry, RelationshipMetadata), (
                f"relationship {relationship_id!r} must be a RelationshipMetadata"
            )
            assert entry.relationship_id == relationship_id
            assert entry.kind is not None
            assert entry.cardinality is not None

    async def assert_cancellation_declarations(self) -> None:
        """A declared cancellation contract is actually exposed by the adapter."""
        _require(
            self.cancellation_declaration is not None, "suite declares no cancellation support"
        )
        ds = await self.datasource()
        declared = getattr(ds, "cancellation_declaration", None)
        assert declared == self.cancellation_declaration, (
            "adapter must expose the declared cancellation_declaration value"
        )

    async def assert_error_translation(self) -> None:
        """Invalid query input fails closed as a portable validation error."""
        ds = await self.datasource()
        records = await self._records()
        assert records
        bogus_filter_field = next(
            (field for field in records[0] if field not in self.identity_fields), None
        )
        if bogus_filter_field is not None:
            async with self._expect_validation_error():
                await ds.list(
                    ResourceQuery(
                        filters=(
                            Filter(
                                field=bogus_filter_field, operator=FilterOperator.EQ, value=object()
                            ),
                        )
                    )
                )
        async with self._expect_validation_error():
            await ds.detail(RecordIdentity(values={"__unknown__": 1}))

    # ------------------------------------------------------------------
    # Runner
    # ------------------------------------------------------------------

    def _expect_validation_error(self) -> AbstractAsyncContextManager[None]:
        @asynccontextmanager
        async def _context() -> AsyncIterator[None]:
            try:
                yield
            except RakitError as exc:
                assert exc.code == ErrorCode.VALIDATION_FAILED, (
                    "invalid query input must map to validation.failed"
                )
                assert exc.status_code == 400
            else:
                raise AssertionError("invalid query input must raise a validation.failed error")

        return _context()

    def _generated_identity_value(self, values: Mapping[str, object]) -> object:
        first_field = self.identity_fields[0]
        current = values.get(first_field)
        if isinstance(current, int):
            return int(current) + 1_000_000
        if isinstance(current, str):
            return f"{current}-contract"
        return uuid.uuid4()

    @property
    def all_assertions(self) -> tuple[str, ...]:
        return (
            "assert_list_detail_and_not_found",
            "assert_identity_round_trip",
            "assert_filtering",
            "assert_search",
            "assert_deterministic_sorting",
            "assert_identity_tie_breaker",
            "assert_pagination",
            "assert_stable_pagination",
            "assert_count_policy_semantics",
            "assert_transactions",
            "assert_writes",
            "assert_concurrency",
            "assert_relationships",
            "assert_cancellation_declarations",
            "assert_error_translation",
        )

    @property
    def skipped(self) -> tuple[str, ...]:
        """Assertion methods skipped during :meth:`run_all` because the suite
        declared them unsupported."""
        return tuple(getattr(self, "_skipped", ()))

    async def run_all(self) -> None:
        """Run every assertion the suite supports; unsupported features are
        recorded in :attr:`skipped` and do not abort the run."""
        self._skipped: list[str] = []
        for name in self.all_assertions:
            try:
                await getattr(self, name)()
            except _SKIP_EXCEPTION_TYPE:
                self._skipped.append(name)
