import inspect
from datetime import date, datetime
from decimal import Decimal
from enum import Enum as PythonEnum
from math import isfinite
from typing import Any
from uuid import UUID

from rakit_core.datasource import DataSourceCapabilities
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.fields import FieldDefinition, infer_field_security
from rakit_core.identity import RecordIdentity
from rakit_core.pagination import (
    LimitOffsetPagination,
    LimitOffsetResult,
    PagePagination,
    PageResult,
    PaginationStrategy,
    ResourceListResult,
)
from rakit_core.query import (
    CountPolicy,
    Filter,
    FilterOperator,
    NullPlacement,
    ResourceQuery,
    Sort,
    SortDirection,
)
from rakit_core.relationships import RelationshipDefinition, RelationshipMetadata
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

from .introspection import (
    FieldMetadata,
    ModelMetadata,
    UnsupportedFieldPolicyError,
    inspect_model,
)
from .relationships import inspect_relationships, validate_relationship_definition

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


def _query_field_not_allowed() -> RakitError:
    return RakitError(
        code=ErrorCode.VALIDATION_FAILED,
        message="Query field is not allowed",
        status_code=400,
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


def _accepts_one_positional_argument(candidate: object) -> bool:
    """Whether `candidate` can be called with exactly one positional
    argument, i.e. conforms to the documented
    `rakit_coerce_filter_value(value: str) -> object` contract.

    `inspect.signature(...).bind("probe")` only checks arity/parameter kinds
    against a probe value -- it never calls `candidate`, so this stays a pure
    claim-time check with no application side effects. A callable whose
    signature cannot be determined at all (e.g. some C extensions) is treated
    as non-conforming: fail closed rather than assume safety.
    """
    if not callable(candidate):
        return False
    try:
        inspect.signature(candidate).bind("probe")
    except (TypeError, ValueError):
        return False
    return True


def _is_filterable_type(type_: TypeEngine[Any]) -> bool:
    """Whether this mapped type has a supported filter-value coercion path.

    Mirrors `_coerce_known_value`'s type dispatch: any type it can actually
    convert (plus a type with an explicit, genuinely *callable*
    `rakit_coerce_filter_value` hook that also accepts the documented
    single-argument call, which bypasses that dispatch entirely) is
    filterable. Anything else (e.g. `LargeBinary`, `JSON`, `PickleType`, a
    malformed hook such as `rakit_coerce_filter_value = object()`, or a hook
    whose call signature can't accept `(value)`) would otherwise only fail at
    the first request that tries to use it -- this check exists so that
    failure surfaces at compile/claim time instead. A hook attribute that is
    merely non-`None` but not callable, or callable but arity-incompatible,
    is treated as unsupported here (not "safe by presence"), matching the
    runtime check `_coerce_filter_item` already performs before invoking it.
    """
    custom_coercer = getattr(type_, "rakit_coerce_filter_value", None)
    if custom_coercer is not None:
        return _accepts_one_positional_argument(custom_coercer)
    unwrapped = _unwrap_type(type_)
    return isinstance(
        unwrapped,
        Enum | Boolean | DateTime | Date | Uuid | Integer | Float | Numeric | String | Text,
    )


def _validate_field_policy_semantics(
    field_policy: ResourceFieldPolicy,
    field_metadata: tuple[FieldMetadata, ...],
) -> None:
    """Fail closed at claim time rather than silently no-op at request time.

    `search_fields` must name only string-searchable columns: a declared
    search field this adapter cannot actually search on (e.g. an integer or
    Enum column) must not compile successfully, since silently skipping it
    at request time would make `?search=...` accept input and return the
    whole table -- indistinguishable from "matched everything". `filter_fields`
    gets the analogous check against `_is_filterable_type`, so an
    unsupported filter field fails at registration instead of the first
    request that happens to use it. A resource with no declared
    `search_fields` is valid (no search control is rendered for it); this
    only rejects a field that *was* declared but cannot be honoured.
    """
    types_by_field = {meta.attribute_name: meta.column_type for meta in field_metadata}
    for field_name in field_policy.search_fields:
        column_type = types_by_field.get(field_name)
        if column_type is None or not _is_string_type(column_type):
            raise UnsupportedFieldPolicyError(field_name, "search_fields", "unsupported_search")
    for field_name in field_policy.filter_fields:
        column_type = types_by_field.get(field_name)
        if column_type is None or not _is_filterable_type(column_type):
            raise UnsupportedFieldPolicyError(field_name, "filter_fields", "unsupported_filter")


def _coerce_by_effective_python_type(effective_type: type, raw_value: object) -> object:
    """Convert a decoded identity URL segment to a `TypeDecorator`'s declared
    effective `python_type` (exactly `int`, `str`, or `UUID` -- the only
    values `introspection._validate_identity_type` ever accepts), so the
    decorator's own `process_bind_param` receives the Python value it
    actually expects, not a value shaped for its storage `impl`."""
    if effective_type is int:
        if isinstance(raw_value, bool) or not isinstance(raw_value, str | int):
            raise ValueError
        return int(raw_value)
    if effective_type is str:
        if not isinstance(raw_value, str):
            raise ValueError
        return raw_value
    if effective_type is UUID:
        if not isinstance(raw_value, str | UUID):
            raise ValueError
        return raw_value if isinstance(raw_value, UUID) else UUID(raw_value)
    raise ValueError


def _coerce_identity_component(type_: TypeEngine[Any], raw_value: object) -> object:
    """Convert one decoded identity component to its mapped column's value.

    Deliberately separate from `_coerce_filter_item`: Plan 02 supports only
    int/str/UUID identities (no custom identity codec -- see
    `introspection._validate_identity_type`), so this never consults the
    filter-specific `rakit_coerce_filter_value` hook, which exists for a
    different purpose and a type author may not have written with identity
    decoding in mind. Only types that `_validate_identity_type` already
    accepted as identities reach this function, so no further type-acceptance
    check is needed here.

    A `TypeDecorator` is coerced according to its own validated `python_type`
    -- never its unwrapped `impl` -- because a decorator may legitimately
    store its value under a different storage representation (e.g. a `UUID`
    persisted as a `String`). Coercing to the `impl`'s type instead would
    hand the decorator's `process_bind_param` a value of the wrong Python
    type. A non-decorator column has no such distinction: its own type *is*
    its storage type, so the existing dispatch applies directly.
    """
    if isinstance(type_, TypeDecorator):
        return _coerce_by_effective_python_type(type_.python_type, raw_value)
    return _coerce_known_value(type_, raw_value)


class SQLAlchemyDataSource:
    capabilities = DataSourceCapabilities(
        read=True,
        pagination_strategies=frozenset({PaginationStrategy.PAGE, PaginationStrategy.LIMIT_OFFSET}),
    )

    def __init__(
        self,
        *,
        model: type[object],
        session_factory: async_sessionmaker[AsyncSession],
        field_policy: ResourceFieldPolicy,
    ) -> None:
        self._model = model
        self._session_factory = session_factory
        self._metadata: ModelMetadata = inspect_model(model)
        self._field_policy = field_policy
        _validate_field_policy_semantics(field_policy, self._metadata.field_metadata)

    @property
    def fields(self) -> tuple[str, ...]:
        return self._metadata.fields

    @property
    def identity_fields(self) -> tuple[str, ...]:
        return (self._metadata.identity_field,)

    @property
    def field_definitions(self) -> tuple[FieldDefinition, ...]:
        search_fields = set(self._field_policy.search_fields)
        filter_fields = set(self._field_policy.filter_fields)
        sort_fields = set(self._field_policy.sort_fields)
        return tuple(
            infer_field_security(
                FieldDefinition(
                    field_id=metadata.attribute_name,
                    python_type=metadata.python_type,
                    readable=True,
                    writable=metadata.writable,
                    searchable=metadata.attribute_name in search_fields,
                    filterable=metadata.attribute_name in filter_fields,
                    sortable=metadata.attribute_name in sort_fields,
                    required=metadata.required,
                    nullable=metadata.nullable,
                )
            )
            for metadata in self._metadata.field_metadata
        )

    @property
    def relationship_metadata(self) -> dict[str, RelationshipMetadata]:
        return inspect_relationships(self._model)

    def validate_relationship(
        self,
        definition: RelationshipDefinition,
        target_data_source: object,
        association_target_data_source: object | None = None,
    ) -> None:
        if not isinstance(target_data_source, SQLAlchemyDataSource):
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Relationship target must use the SQLAlchemy adapter.",
                status_code=500,
                details={"relationship_id": definition.relationship_id},
            )
        validate_relationship_definition(
            definition,
            source_model=self._model,
            target_model=target_data_source._model,
            association_target_model=(
                association_target_data_source._model
                if isinstance(association_target_data_source, SQLAlchemyDataSource)
                else None
            ),
        )

    def _base_statement(self) -> Select:
        return select(self._model)

    def scoped_statement(self) -> Select:
        """The resource visibility selectable, reusable by write operations.

        Subclasses may narrow ``_base_statement`` for tenancy or visibility;
        mutations consume this public seam rather than bypassing that scope.
        """
        return self._base_statement()

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
        for field_name in self._field_policy.search_fields:
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

    def _validate_query_policy(self, query: ResourceQuery) -> None:
        known_fields = set(self.fields)
        allowed_sort_fields = set(self._field_policy.sort_fields)
        if any(
            sort.field not in known_fields or sort.field not in allowed_sort_fields
            for sort in query.sorting
        ):
            raise _query_field_not_allowed()
        # `identity_tie_breakers` are internal, adapter-required stable
        # ordering, not user-requested sorting: they are exempt from the
        # `sort_fields` whitelist (that's the whole point -- an identity
        # column need not be user-sortable for the tie-breaker composition to
        # work). But "exempt from the sort whitelist" must not mean "any
        # known field" -- that would let a caller order by a sensitive,
        # non-sortable column (e.g. `password_hash`) merely by placing it in
        # `identity_tie_breakers` instead of `sorting`. A tie-breaker is only
        # ever legitimate as this datasource's *actual* identity field(s),
        # ascending, with no null-placement override, and each identity field
        # named at most once.
        identity_fields = set(self.identity_fields)
        seen_tie_breaker_fields: set[str] = set()
        for tie_breaker in query.identity_tie_breakers:
            if (
                tie_breaker.field not in identity_fields
                or tie_breaker.field in seen_tie_breaker_fields
                or tie_breaker.direction is not SortDirection.ASC
                or tie_breaker.nulls is not NullPlacement.AUTO
            ):
                raise _query_field_not_allowed()
            seen_tie_breaker_fields.add(tie_breaker.field)
        allowed_filter_fields = set(self._field_policy.filter_fields)
        if any(
            filter_.field not in known_fields or filter_.field not in allowed_filter_fields
            for filter_ in query.filters
        ):
            raise _query_field_not_allowed()
        if query.search and (
            not self._field_policy.search_fields
            or not set(self._field_policy.search_fields) <= known_fields
        ):
            raise _query_field_not_allowed()

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
        """Combine explicit sorting with stable identity ordering.

        Priority, each added only if its field isn't already present (so
        identity ordering appears exactly once, after explicit sorting):
        1. `query.sorting` -- explicit, policy-validated user sort;
        2. `query.identity_tie_breakers` -- the caller-declared identity
           ordering from `ResourceQuery.from_params(identity_fields=...)`;
        3. `self.identity_fields` -- this adapter's own mapped identity
           column. Stable pagination is an adapter invariant: it is appended
           unconditionally so a query built by direct `ResourceQuery(...)`
           construction (bypassing `from_params()` entirely) still gets a
           stable, deterministic order.
        """
        sorting = list(query.sorting)
        sorted_fields = {sort.field for sort in sorting}
        for tie_breaker in query.identity_tie_breakers:
            if tie_breaker.field not in sorted_fields:
                sorting.append(tie_breaker)
                sorted_fields.add(tie_breaker.field)
        for field_name in self.identity_fields:
            if field_name not in sorted_fields:
                sorting.append(Sort(field=field_name))
                sorted_fields.add(field_name)
        return tuple(sorting)

    async def list(self, query: ResourceQuery) -> ResourceListResult:
        self._validate_query_policy(query)
        filtered = self._filtered_statement(query)
        ordered = filtered
        for sort in self._effective_sorting(query):
            ordered = self._apply_sort(ordered, sort)

        pagination = query.pagination
        if isinstance(pagination, PagePagination):
            offset = pagination.offset
            limit = pagination.per_page
        elif isinstance(pagination, LimitOffsetPagination):
            offset = pagination.offset
            limit = pagination.limit
        else:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID_RESOURCE_POLICY,
                message="SQLAlchemy data source does not support cursor pagination.",
                status_code=500,
                details={"reason": "pagination_strategy_not_supported"},
            )

        async with self._session_factory() as session:
            if query.count_policy is CountPolicy.EXACT:
                total_count: int | None = await self._count(session, filtered)
                paginated = ordered.offset(offset).limit(limit)
                items = tuple((await session.execute(paginated)).scalars().all())
                has_next = offset + len(items) < total_count
            else:
                paginated = ordered.offset(offset).limit(limit + 1)
                rows = list((await session.execute(paginated)).scalars().all())
                has_next = len(rows) > limit
                items = tuple(rows[:limit])
                total_count = None

        if isinstance(pagination, PagePagination):
            return PageResult(
                items=items,
                page=pagination.page,
                per_page=pagination.per_page,
                has_previous=pagination.page > 1,
                has_next=has_next,
                total_count=total_count,
            )
        return LimitOffsetResult(
            items=items,
            offset=pagination.offset,
            limit=pagination.limit,
            has_previous=pagination.offset > 0,
            has_next=has_next,
            total_count=total_count,
        )

    async def count(self, query: ResourceQuery) -> int:
        """Run the EXACT count for a query, ignoring pagination and ordering.

        Backs the deferred-count route: it re-derives the same filter/search
        predicates as `list()` so a deferred total matches the filtered list it
        annotates, rather than counting the whole table.
        """
        self._validate_query_policy(query)
        filtered = self._filtered_statement(query)
        async with self._session_factory() as session:
            return await self._count(session, filtered)

    def _detail_statement(self, identity: RecordIdentity) -> Select:
        identity_field = self._metadata.identity_field
        if set(identity.values) != {identity_field}:
            raise _invalid_identity(identity_field)

        column = getattr(self._model, identity_field)
        try:
            value = _coerce_identity_component(column.type, identity.values[identity_field])
        except (ArithmeticError, TypeError, ValueError) as exc:
            raise _invalid_identity(identity_field, cause=exc) from exc
        return self._base_statement().where(column == value)

    async def detail(self, identity: RecordIdentity) -> object | None:
        statement = self._detail_statement(identity)
        async with self._session_factory() as session:
            result = await session.execute(statement)
            return result.scalar_one_or_none()

    def identity_for(self, record: object) -> RecordIdentity:
        """Return this data source's canonical identity for an already-loaded record."""

        return RecordIdentity(
            values={field: getattr(record, field) for field in self.identity_fields}
        )

    def identity_conditions(self, identity: RecordIdentity) -> tuple[ColumnElement[bool], ...]:
        """Build validated mapped identity predicates for an adapter-owned statement."""

        if set(identity.values) != set(self.identity_fields):
            raise _invalid_identity(self._metadata.identity_field)
        return tuple(
            getattr(self._model, field) == value for field, value in identity.values.items()
        )

    async def resolve_scoped(
        self, session: AsyncSession, identity: RecordIdentity
    ) -> object | None:
        """Resolve an identity from the resource's canonical visibility scope.

        This is intentionally adapter-owned so relationship writes cannot
        substitute ``Session.get`` and accidentally bypass a host's scoped
        base query.
        """

        return (
            await session.scalars(
                self.scoped_statement().where(*self.identity_conditions(identity))
            )
        ).one_or_none()
