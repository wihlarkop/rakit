from collections.abc import Sequence

from rakit_core.datasource import DataSourceCapabilities
from rakit_core.identity import RecordIdentity
from rakit_core.query import Filter, FilterOperator, NullPlacement, PageResult, ResourceQuery, Sort
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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

    def _apply_sort(self, statement: Select, sort: Sort) -> Select:
        column = getattr(self._model, sort.field)
        ordering = column.desc() if sort.direction.value == "desc" else column.asc()
        if sort.nulls == NullPlacement.FIRST:
            ordering = ordering.nulls_first()
        elif sort.nulls == NullPlacement.LAST:
            ordering = ordering.nulls_last()
        return statement.order_by(ordering)

    async def list(self, query: ResourceQuery) -> PageResult:
        statement = self._base_statement()
        for filter_ in query.filters:
            statement = self._apply_filter(statement, filter_)
        for sort in query.sorting:
            statement = self._apply_sort(statement, sort)

        async with self._session_factory() as session:
            count_statement = select(func.count()).select_from(statement.subquery())
            total_count = (await session.execute(count_statement)).scalar_one()

            paginated_statement = statement.offset(query.pagination.offset).limit(
                query.pagination.per_page
            )
            result = await session.execute(paginated_statement)
            items: Sequence[object] = result.scalars().all()

        has_previous = query.pagination.page > 1
        has_next = query.pagination.offset + len(items) < total_count

        return PageResult(
            items=tuple(items),
            page=query.pagination.page,
            per_page=query.pagination.per_page,
            has_previous=has_previous,
            has_next=has_next,
            total_count=total_count,
        )

    async def detail(self, identity: RecordIdentity) -> object | None:
        column = getattr(self._model, self._metadata.identity_field)
        statement = self._base_statement().where(
            column == identity.values[self._metadata.identity_field]
        )
        async with self._session_factory() as session:
            result = await session.execute(statement)
            return result.scalar_one_or_none()
