from __future__ import annotations

from collections.abc import Mapping
from typing import cast
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
from rakit_core.query import CountPolicy, NullPlacement, ResourceQuery, Sort, SortDirection
from rakit_core.relationships import RelationshipDefinition, RelationshipMetadata
from sqlalchemy import Table, func, or_, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
from sqlalchemy.sql import ColumnElement, Select

from .core_relationships import (
    ResolvedCoreRelationship,
    SQLAlchemyCoreRelationshipBinding,
    resolve_relationship_definition,
)
from .datasource import (
    _OPERATOR_HANDLERS,
    _coerce_filter_value,
    _coerce_identity_component,
    _invalid_filter,
    _invalid_identity,
    _is_string_type,
    _query_field_not_allowed,
    _validate_field_policy_semantics,
)
from .introspection import (
    FieldMetadata,
    ModelMetadata,
    UnsupportedIdentityError,
    _python_type,
    _validate_identity_type,
)


def inspect_table(table: Table) -> ModelMetadata:
    primary_keys = tuple(table.primary_key.columns)
    if len(primary_keys) != 1:
        raise UnsupportedIdentityError("composite_identity")

    identity_column = primary_keys[0]
    _validate_identity_type(identity_column.type)

    metadata: list[FieldMetadata] = []
    for column in table.columns:
        writable = not column.primary_key and column.computed is None
        has_default = (
            column.default is not None
            or column.server_default is not None
            or column.identity is not None
        )
        metadata.append(
            FieldMetadata(
                attribute_name=column.key,
                database_name=column.name,
                column_type=column.type,
                python_type=_python_type(column.type),
                nullable=bool(column.nullable),
                required=writable and not column.nullable and not has_default,
                writable=writable,
            )
        )

    field_metadata = tuple(metadata)
    return ModelMetadata(
        identity_field=identity_column.key,
        fields=tuple(field.attribute_name for field in field_metadata),
        field_metadata=field_metadata,
    )


class SQLAlchemyCoreDataSource:
    capabilities = DataSourceCapabilities(
        read=True,
        pagination_strategies=frozenset({PaginationStrategy.PAGE, PaginationStrategy.LIMIT_OFFSET}),
    )

    def __init__(
        self,
        *,
        table: Table,
        engine: AsyncEngine,
        field_policy: ResourceFieldPolicy,
        relationship_bindings: Mapping[str, SQLAlchemyCoreRelationshipBinding] | None = None,
    ) -> None:
        self._table = table
        self._engine = engine
        self._metadata = inspect_table(table)
        self._field_policy = field_policy
        self._relationship_bindings = dict(relationship_bindings or {})
        self._relationship_metadata: dict[str, RelationshipMetadata] = {}
        self._resolved_relationships: dict[str, ResolvedCoreRelationship] = {}
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
        """Return only relationship facts already resolved from explicit definitions."""

        return dict(self._relationship_metadata)

    def validate_relationship(
        self,
        definition: RelationshipDefinition,
        target_data_source: object,
        association_target_data_source: object | None = None,
    ) -> None:
        if not isinstance(target_data_source, SQLAlchemyCoreDataSource):
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Relationship target must use the SQLAlchemy Core adapter.",
                status_code=500,
                details={"relationship_id": definition.relationship_id},
            )
        if association_target_data_source is not None and not isinstance(
            association_target_data_source, SQLAlchemyCoreDataSource
        ):
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="Association target must use the SQLAlchemy Core adapter.",
                status_code=500,
                details={"relationship_id": definition.relationship_id},
            )
        relationship_id = str(definition.relationship_id)
        resolved = resolve_relationship_definition(
            definition,
            source_table=self._table,
            target_table=target_data_source._table,
            association_target_table=(
                association_target_data_source._table
                if isinstance(association_target_data_source, SQLAlchemyCoreDataSource)
                else None
            ),
            binding=self._relationship_bindings.get(relationship_id),
        )
        self._resolved_relationships[relationship_id] = resolved
        self._relationship_metadata[relationship_id] = resolved.metadata

    def resolved_relationship(self, relationship_id: str) -> ResolvedCoreRelationship:
        try:
            return self._resolved_relationships[relationship_id]
        except KeyError as exc:
            raise RakitError(
                code=ErrorCode.CONFIG_INVALID,
                message="SQLAlchemy Core relationship was not compiled before runtime use.",
                status_code=500,
                details={"relationship_id": relationship_id},
                cause=exc,
            ) from exc

    def _column(self, field: str):
        return self._table.c[field]

    def _base_statement(self) -> Select:
        return select(self._table)

    def scoped_statement(self) -> Select:
        """Return the canonical Core visibility statement used by relationship resolution."""

        return self._base_statement()

    def identity_conditions(self, identity: RecordIdentity) -> tuple[ColumnElement[bool], ...]:
        identity_field = self._metadata.identity_field
        if set(identity.values) != {identity_field}:
            raise _invalid_identity(identity_field)
        column = self._column(identity_field)
        try:
            value = _coerce_identity_component(column.type, identity.values[identity_field])
        except (ArithmeticError, TypeError, ValueError) as exc:
            raise _invalid_identity(identity_field, cause=exc) from exc
        return (column == value,)

    async def resolve_scoped(
        self, connection: AsyncConnection, identity: RecordIdentity
    ) -> dict[str, object] | None:
        result = await connection.execute(
            self.scoped_statement().where(*self.identity_conditions(identity))
        )
        row = result.mappings().one_or_none()
        return None if row is None else dict(row)

    def _apply_filter(self, statement: Select, filter_):
        column = self._column(filter_.field)
        if filter_.operator.value == "contains" and not _is_string_type(column.type):
            raise _invalid_filter(
                filter_,
                message="Filter operator is not valid for this field",
            )
        value = _coerce_filter_value(column.type, filter_)
        handler = _OPERATOR_HANDLERS[filter_.operator]
        return statement.where(handler(column, value))

    def _apply_search(self, statement: Select, search: str) -> Select:
        predicates: list[ColumnElement[bool]] = []
        for field_name in self._field_policy.search_fields:
            column = self._column(field_name)
            if _is_string_type(column.type):
                predicates.append(column.contains(search))
        if predicates:
            statement = statement.where(or_(*predicates))
        return statement

    def _filtered_statement(self, query: ResourceQuery) -> Select:
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

    def _apply_sort(self, statement: Select, sort: Sort) -> Select:
        column = self._column(sort.field)
        ordering = column.desc() if sort.direction is SortDirection.DESC else column.asc()
        if sort.nulls is NullPlacement.FIRST:
            ordering = ordering.nulls_first()
        elif sort.nulls is NullPlacement.LAST:
            ordering = ordering.nulls_last()
        return statement.order_by(ordering)

    def _effective_sorting(self, query: ResourceQuery) -> tuple[Sort, ...]:
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

    async def _count(self, statement: Select) -> int:
        count_statement = select(func.count()).select_from(statement.subquery())
        async with self._engine.connect() as connection:
            return int((await connection.scalar(count_statement)) or 0)

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
                message="SQLAlchemy Core data source does not support cursor pagination.",
                status_code=500,
                details={"reason": "pagination_strategy_not_supported"},
            )

        async with self._engine.connect() as connection:
            if query.count_policy is CountPolicy.EXACT:
                count_statement = select(func.count()).select_from(filtered.subquery())
                total_count = int((await connection.scalar(count_statement)) or 0)
                result = await connection.execute(ordered.offset(offset).limit(limit))
                items = tuple(dict(row) for row in result.mappings().all())
                has_next = offset + len(items) < total_count
            else:
                result = await connection.execute(ordered.offset(offset).limit(limit + 1))
                rows = [dict(row) for row in result.mappings().all()]
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
        self._validate_query_policy(query)
        return await self._count(self._filtered_statement(query))

    async def detail(self, identity: RecordIdentity) -> object | None:
        async with self._engine.connect() as connection:
            return await self.resolve_scoped(connection, identity)

    def identity_for(self, record: object) -> RecordIdentity:
        if not isinstance(record, Mapping):
            raise TypeError("SQLAlchemy Core records must be mapping values")
        values = cast(Mapping[str, object], record)
        identity_field = self._metadata.identity_field
        value = values[identity_field]
        if isinstance(value, bool) or not isinstance(value, int | str | UUID):
            raise TypeError("SQLAlchemy Core identity values must be int, str, or UUID")
        return RecordIdentity(values={identity_field: value})
