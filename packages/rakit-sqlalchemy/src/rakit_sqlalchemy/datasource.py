from datetime import date, datetime
from decimal import Decimal
from enum import Enum as PythonEnum
from math import isfinite
from typing import Any
from uuid import UUID

from rakit_core.datasource import DataSourceCapabilities
from rakit_core.errors import ErrorCode, RakitError
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
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
    func,
    or_,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import ColumnElement, Select
from sqlalchemy.sql.type_api import TypeEngine
from sqlalchemy.types import TypeDecorator

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


def _invalid_filter(
    filter_: Filter,
    *,
    message: str = "Invalid filter value",
    cause: BaseException | None = None,
) -> RakitError:
    return RakitError(
        code=ErrorCode.VALIDATION_FAILED,
        message=message,
        status_code=400,
        details={"field": filter_.field, "operator": filter_.operator.value},
        cause=cause,
    )


def _invalid_identity(
    field: str,
    *,
    cause: BaseException | None = None,
) -> RakitError:
    return RakitError(
        code=ErrorCode.VALIDATION_FAILED,
        message="Invalid resource identity",
        status_code=400,
        details={"field": field},
        cause=cause,
    )


def _enum_value(type_: Enum, value: object) -> object:
    if not isinstance(value, str):
        if type_.enum_class is not None and isinstance(value, type_.enum_class):
            return value
        raise ValueError

    if value not in type_.enums:
        raise ValueError
    if type_.enum_class is None:
        return value

    # ``Enum.enums`` is SQLAlchemy's persisted-value sequence. Its length tells
    # us whether this type persists aliases: pair it with every declaration in
    # that case, otherwise use only canonical members. This also supports a
    # values_callable without constructing the Enum class from URL input.
    declared_members = list(type_.enum_class.__members__.values())
    canonical_members = [
        member for name, member in type_.enum_class.__members__.items() if member.name == name
    ]
    members: list[PythonEnum] = (
        declared_members if len(type_.enums) == len(declared_members) else canonical_members
    )
    return dict(zip(type_.enums, members, strict=True))[value]


def _datetime_value(type_: DateTime, value: object) -> datetime:
    if isinstance(value, datetime):
        converted = value
    elif isinstance(value, str):
        converted = datetime.fromisoformat(value)
    else:
        raise ValueError
    is_aware = converted.tzinfo is not None and converted.utcoffset() is not None
    if type_.timezone != is_aware:
        raise ValueError
    return converted


def _coerce_known_value(type_: TypeEngine[Any], value: object) -> object:
    if isinstance(type_, Enum):
        return _enum_value(type_, value)
    if isinstance(type_, Boolean):
        if isinstance(value, bool):
            return value
        if not isinstance(value, str):
            raise ValueError
        normalized = value.lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
        raise ValueError
    if isinstance(type_, DateTime):
        if not isinstance(value, str | datetime):
            raise ValueError
        return _datetime_value(type_, value)
    if isinstance(type_, Date):
        if isinstance(value, datetime) or not isinstance(value, str | date):
            raise ValueError
        return value if isinstance(value, date) else date.fromisoformat(value)
    if isinstance(type_, Uuid):
        if not isinstance(value, str | UUID):
            raise ValueError
        converted = value if isinstance(value, UUID) else UUID(value)
        return converted if type_.as_uuid else str(converted)
    if isinstance(type_, Integer):
        if isinstance(value, bool) or not isinstance(value, str | int):
            raise ValueError
        return int(value)
    if isinstance(type_, Float):
        if isinstance(value, bool) or not isinstance(value, str | int | float | Decimal):
            raise ValueError
        converted_float = float(value)
        if not isfinite(converted_float):
            raise ValueError
        return converted_float
    if isinstance(type_, Numeric):
        if isinstance(value, bool) or not isinstance(value, str | int | float | Decimal):
            raise ValueError
        converted_decimal = Decimal(str(value))
        if not converted_decimal.is_finite():
            raise ValueError
        return converted_decimal
    if isinstance(type_, String | Text):
        if not isinstance(value, str):
            raise ValueError
        return value
    raise ValueError


def _unwrap_type(type_: TypeEngine[Any]) -> TypeEngine[Any]:
    while isinstance(type_, TypeDecorator):
        implementation = type_.impl
        if not isinstance(implementation, TypeEngine):
            raise ValueError
        type_ = implementation
    return type_


def _coerce_filter_item(type_: TypeEngine[Any], value: object) -> object:
    custom_coercer = getattr(type_, "rakit_coerce_filter_value", None)
    if custom_coercer is not None:
        if not callable(custom_coercer) or not isinstance(value, str):
            raise ValueError
        return custom_coercer(value)

    # A TypeDecorator without an explicit Rakit hook inherits safe conversion
    # from its declared implementation. Types with different URL semantics can
    # override via ``rakit_coerce_filter_value`` above.
    return _coerce_known_value(_unwrap_type(type_), value)


def _coerce_filter_value(type_: TypeEngine[Any], filter_: Filter) -> object:
    if filter_.operator is FilterOperator.IS_NULL:
        if not isinstance(filter_.value, bool):
            raise _invalid_filter(filter_)
        return filter_.value

    if filter_.operator is FilterOperator.IN:
        if not isinstance(filter_.value, list | tuple):
            raise _invalid_filter(filter_)
        values = filter_.value
    else:
        values = None

    try:
        if values is not None:
            return [_coerce_filter_item(type_, item) for item in values]
        return _coerce_filter_item(type_, filter_.value)
    except RakitError:
        raise
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise _invalid_filter(filter_, cause=exc) from exc


def _is_string_type(type_: TypeEngine[Any]) -> bool:
    type_ = _unwrap_type(type_)
    return isinstance(type_, String | Text) and not isinstance(type_, Enum)


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
        if filter_.operator is FilterOperator.CONTAINS and not _is_string_type(column.type):
            raise _invalid_filter(
                filter_,
                message="Filter operator is not valid for this field",
            )
        value = _coerce_filter_value(column.type, filter_)
        handler = _OPERATOR_HANDLERS[filter_.operator]
        return statement.where(handler(column, value))

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
            if _is_string_type(column.type):
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

    def _effective_sorting(self, query: ResourceQuery) -> tuple[Sort, ...]:
        sorting = list(query.sorting)
        sorted_fields = {sort.field for sort in sorting}
        for field_name in self.identity_fields:
            if field_name not in sorted_fields:
                sorting.append(Sort(field=field_name))
                sorted_fields.add(field_name)
        return tuple(sorting)

    async def list(self, query: ResourceQuery) -> PageResult:
        filtered = self._filtered_statement(query)
        ordered = filtered
        for sort in self._effective_sorting(query):
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

    def _detail_statement(self, identity: RecordIdentity) -> Select:
        identity_field = self._metadata.identity_field
        if set(identity.values) != {identity_field}:
            raise _invalid_identity(identity_field)

        column = getattr(self._model, identity_field)
        try:
            value = _coerce_filter_item(column.type, identity.values[identity_field])
        except (ArithmeticError, TypeError, ValueError) as exc:
            raise _invalid_identity(identity_field, cause=exc) from exc
        return self._base_statement().where(column == value)

    async def detail(self, identity: RecordIdentity) -> object | None:
        statement = self._detail_statement(identity)
        async with self._session_factory() as session:
            result = await session.execute(statement)
            return result.scalar_one_or_none()
