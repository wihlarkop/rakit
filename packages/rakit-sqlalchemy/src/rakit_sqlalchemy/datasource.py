from rakit_core.datasource import DataSourceCapabilities
from rakit_core.identity import RecordIdentity
from rakit_core.query import (
    CountPolicy,
    Filter,
    FilterOperator,
    NullPlacement,
    PageResult,
    ResourceQuery,
    Sort,
)
from sqlalchemy import String, Text, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import ColumnElement, Select

from .introspection import ModelMetadata, inspect_model

_OPERATOR_HANDLERS = {
    FilterOperator.EQ: lambda column, value: column == value,
    FilterOperator.NEQ: lambda column, value: column != value,
    FilterOperator.LT: lambda column, value: column < value,
    FilterOperator.LTE: lambda column, value: column <= value,
    FilterOperator.GT: lambda column, value: column > value,
    FilterOperator.GTE: lambda column, value: column >= value,
    FilterOperator.CONTAINS: lambda column, value: column.contains(value),
    FilterOperator.IN: lambda column, value: column.in_(value),
    FilterOperator.IS_NULL: lambda column, value: (
        column.is_(None) if value else column.is_not(None)
    ),
}


class SQLAlchemyDataSource:
    capabilities = DataSourceCapabilities(read=True)

    def __init__(
        self,
        *,
        model: type[object],
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._model = model
        self._session_factory = session_factory
        self._metadata: ModelMetadata = inspect_model(model)

    @property
    def fields(self) -> tuple[str, ...]:
        return self._metadata.fields

    @property
    def identity_fields(self) -> tuple[str, ...]:
        return (self._metadata.identity_field,)

    def _base_statement(self) -> Select:
        return select(self._model)

    def _apply_filter(self, statement: Select, filter_: Filter) -> Select:
        column = getattr(self._model, filter_.field)
        handler = _OPERATOR_HANDLERS[filter_.operator]
        return statement.where(handler(column, filter_.value))

    def _apply_search(self, statement: Select, search: str) -> Select:
        """OR-combine a `contains` predicate across every string-typed field.

        Only `String`/`Text` columns are searched -- attempting `.contains()` on
        a non-string column (e.g. an integer PK) would produce nonsensical SQL or
        raise, so those columns are skipped. Case sensitivity is inherited from
        `column.contains()` (the same mapping used by the `contains` filter
        operator), rather than inventing a separate behaviour for search.
        """
        predicates: list[ColumnElement[bool]] = []
        for field_name in self.fields:
            column = getattr(self._model, field_name)
            if isinstance(column.type, String | Text):
                predicates.append(column.contains(search))
        if predicates:
            statement = statement.where(or_(*predicates))
        return statement

    def _filtered_statement(self, query: ResourceQuery) -> Select:
        """Base statement narrowed by filters and free-text search (no ordering).

        Ordering is deliberately excluded so this can back both the paginated
        fetch (which adds ordering) and the count query (which does not need it).
        """
        statement = self._base_statement()
        for filter_ in query.filters:
            statement = self._apply_filter(statement, filter_)
        if query.search:
            statement = self._apply_search(statement, query.search)
        return statement

    async def _count(self, session: AsyncSession, statement: Select) -> int:
        count_statement = select(func.count()).select_from(statement.subquery())
        return (await session.execute(count_statement)).scalar_one()

    def _apply_sort(self, statement: Select, sort: Sort) -> Select:
        column = getattr(self._model, sort.field)
        ordering = column.desc() if sort.direction.value == "desc" else column.asc()
        if sort.nulls == NullPlacement.FIRST:
            ordering = ordering.nulls_first()
        elif sort.nulls == NullPlacement.LAST:
            ordering = ordering.nulls_last()
        return statement.order_by(ordering)

    async def list(self, query: ResourceQuery) -> PageResult:
        filtered = self._filtered_statement(query)
        ordered = filtered
        for sort in query.sorting:
            ordered = self._apply_sort(ordered, sort)

        pagination = query.pagination
        async with self._session_factory() as session:
            if query.count_policy is CountPolicy.EXACT:
                total_count: int | None = await self._count(session, filtered)
                paginated = ordered.offset(pagination.offset).limit(pagination.per_page)
                items = tuple((await session.execute(paginated)).scalars().all())
                has_next = pagination.offset + len(items) < total_count
            else:
                # DISABLED and DEFERRED both avoid the count query on this page:
                # fetch one extra row to learn whether a next page exists, then
                # trim it back off before building the result. DEFERRED's real
                # total is fetched separately via the dedicated `_count` route.
                paginated = ordered.offset(pagination.offset).limit(pagination.per_page + 1)
                rows = list((await session.execute(paginated)).scalars().all())
                has_next = len(rows) > pagination.per_page
                items = tuple(rows[: pagination.per_page])
                total_count = None

        return PageResult(
            items=items,
            page=pagination.page,
            per_page=pagination.per_page,
            has_previous=pagination.page > 1,
            has_next=has_next,
            total_count=total_count,
        )

    async def count(self, query: ResourceQuery) -> int:
        """Run the EXACT count for a query, ignoring pagination and ordering.

        Backs the deferred-count route: it re-derives the same filter/search
        predicates as `list()` so a deferred total matches the filtered list it
        annotates, rather than counting the whole table.
        """
        filtered = self._filtered_statement(query)
        async with self._session_factory() as session:
            return await self._count(session, filtered)

    async def detail(self, identity: RecordIdentity) -> object | None:
        column = getattr(self._model, self._metadata.identity_field)
        statement = self._base_statement().where(
            column == identity.values[self._metadata.identity_field]
        )
        async with self._session_factory() as session:
            result = await session.execute(statement)
            return result.scalar_one_or_none()
