from __future__ import annotations

from typing import Any

from peewee import DoesNotExist, fn
from playhouse.pwasyncio import AsyncDatabaseMixin
from rakit_core.datasource import DataSourceCapabilities
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.fields import FieldDefinition
from rakit_core.identity import RecordIdentity
from rakit_core.pagination import (
    LimitOffsetPagination,
    LimitOffsetResult,
    PagePagination,
    PageResult,
    PaginationStrategy,
    ResourceListResult,
)
from rakit_core.query import CountPolicy, Filter, FilterOperator, NullPlacement, ResourceQuery

from .introspection import (
    PeeweeModelMetadata,
    field_definitions,
    inspect_model,
    validate_field_policy,
)


def _validation_error(
    message: str, *, field: str | None = None, cause: Exception | None = None
) -> RakitError:
    details = {"field": field} if field is not None else None
    return RakitError(
        code=ErrorCode.VALIDATION_FAILED,
        message=message,
        status_code=400,
        details=details,
        cause=cause,
    )


class PeeweeDataSource:
    capabilities = DataSourceCapabilities(
        read=True,
        pagination_strategies=frozenset({PaginationStrategy.PAGE, PaginationStrategy.LIMIT_OFFSET}),
    )

    def __init__(
        self,
        *,
        model: type[Any],
        database: AsyncDatabaseMixin,
        field_policy: ResourceFieldPolicy,
    ) -> None:
        self._database = database
        self._metadata: PeeweeModelMetadata = inspect_model(model, database=database)
        self._model = self._metadata.model
        self._field_policy = field_policy
        validate_field_policy(self._metadata, field_policy)
        self._field_definitions = field_definitions(self._metadata, field_policy)
        self._fields_by_name = {field.name: field for field in self._metadata.fields}

    @property
    def database(self) -> AsyncDatabaseMixin:
        return self._database

    @property
    def fields(self) -> tuple[str, ...]:
        return self._metadata.field_names

    @property
    def identity_fields(self) -> tuple[str, ...]:
        return (self._metadata.identity_field,)

    @property
    def field_definitions(self) -> tuple[FieldDefinition, ...]:
        return self._field_definitions

    def _field(self, name: str) -> Any:
        metadata = self._fields_by_name.get(name)
        if metadata is None:
            raise _validation_error("Unknown persistence field", field=name)
        return metadata.field

    def _validate_filter(self, filter_: Filter) -> None:
        if filter_.field not in self._field_policy.filter_fields:
            raise _validation_error("Filter field is not allowed", field=filter_.field)

    def _filter_expression(self, filter_: Filter) -> Any:
        self._validate_filter(filter_)
        field = self._field(filter_.field)
        if filter_.operator is FilterOperator.EQ:
            return field == filter_.value
        if filter_.operator is FilterOperator.NEQ:
            return field != filter_.value
        if filter_.operator is FilterOperator.LT:
            return field < filter_.value
        if filter_.operator is FilterOperator.LTE:
            return field <= filter_.value
        if filter_.operator is FilterOperator.GT:
            return field > filter_.value
        if filter_.operator is FilterOperator.GTE:
            return field >= filter_.value
        if filter_.operator is FilterOperator.CONTAINS:
            return field.contains(filter_.value)
        if filter_.operator is FilterOperator.IN:
            return field.in_(filter_.value)
        if filter_.operator is FilterOperator.IS_NULL:
            return field.is_null(bool(filter_.value))
        raise _validation_error("Filter operator is not supported", field=filter_.field)

    def _apply_filters_and_search(self, query: Any, resource_query: ResourceQuery) -> Any:
        for filter_ in resource_query.filters:
            query = query.where(self._filter_expression(filter_))
        search = resource_query.search
        if not search:
            return query
        fields = self._field_policy.search_fields
        if not fields:
            raise _validation_error("Search is not enabled for this resource")
        expression: Any | None = None
        normalized = search.lower()
        for field_name in fields:
            candidate = fn.LOWER(self._field(field_name)).contains(normalized)
            expression = candidate if expression is None else expression | candidate
        assert expression is not None
        return query.where(expression)

    def _apply_sorting(self, query: Any, resource_query: ResourceQuery) -> Any:
        terms: list[Any] = []
        for sort in (*resource_query.sorting, *resource_query.identity_tie_breakers):
            if sort.nulls is not NullPlacement.AUTO:
                raise _validation_error("Explicit NULL sort placement is not portable for Peewee")
            if (
                sort.field not in self._field_policy.sort_fields
                and sort.field not in self.identity_fields
            ):
                raise _validation_error("Sort field is not allowed", field=sort.field)
            field = self._field(sort.field)
            terms.append(field.desc() if sort.direction.value == "desc" else field.asc())
        if not terms:
            terms.append(self._field(self._metadata.identity_field).asc())
        return query.order_by(*terms)

    def _filtered_query(self, resource_query: ResourceQuery) -> Any:
        try:
            return self._apply_filters_and_search(self._model.select(), resource_query)
        except RakitError:
            raise
        except (TypeError, ValueError) as exc:
            raise _validation_error("Invalid persistence query", cause=exc) from exc

    def _query(self, resource_query: ResourceQuery) -> Any:
        try:
            return self._apply_sorting(self._filtered_query(resource_query), resource_query)
        except RakitError:
            raise
        except (TypeError, ValueError) as exc:
            raise _validation_error("Invalid persistence query", cause=exc) from exc

    async def count(self, query: ResourceQuery) -> int:
        queryset = self._filtered_query(query)
        try:
            return int(await self._database.run(queryset.count))
        except RakitError:
            raise
        except Exception as exc:
            raise RakitError(
                code=ErrorCode.DATASOURCE_FAILURE,
                message="Peewee count query failed",
                status_code=500,
                cause=exc,
            ) from exc

    async def list(self, query: ResourceQuery) -> ResourceListResult[object]:
        queryset = self._query(query)
        pagination = query.pagination
        if isinstance(pagination, PagePagination):
            offset, limit = pagination.offset, pagination.per_page
        elif isinstance(pagination, LimitOffsetPagination):
            offset, limit = pagination.offset, pagination.limit
        else:
            raise _validation_error("Peewee adapter does not support cursor pagination")

        try:
            total_count = (
                await self._database.run(self._filtered_query(query).count)
                if query.count_policy is CountPolicy.EXACT
                else None
            )
            fetched = tuple(
                await self._database.list(queryset.offset(offset).limit(limit + 1))
            )
        except RakitError:
            raise
        except Exception as exc:
            raise RakitError(
                code=ErrorCode.DATASOURCE_FAILURE,
                message="Peewee list query failed",
                status_code=500,
                cause=exc,
            ) from exc

        has_next = len(fetched) > limit
        items = fetched[:limit]
        if isinstance(pagination, PagePagination):
            return PageResult(
                items=items,
                page=pagination.page,
                per_page=pagination.per_page,
                has_previous=pagination.page > 1,
                has_next=has_next,
                total_count=int(total_count) if total_count is not None else None,
            )
        return LimitOffsetResult(
            items=items,
            offset=pagination.offset,
            limit=pagination.limit,
            has_previous=pagination.offset > 0,
            has_next=has_next,
            total_count=int(total_count) if total_count is not None else None,
        )

    def _identity_value(self, identity: RecordIdentity) -> object:
        values = dict(identity.values)
        expected = self._metadata.identity_field
        if tuple(values) != (expected,):
            raise _validation_error("Invalid resource identity", field=expected)
        return values[expected]

    async def detail(self, identity: RecordIdentity) -> object:
        identity_value = self._identity_value(identity)
        identity_field = self._field(self._metadata.identity_field)
        try:
            return await self._database.get(
                self._model.select().where(identity_field == identity_value)
            )
        except DoesNotExist as exc:
            raise RakitError(
                code=ErrorCode.RESOURCE_NOT_FOUND,
                message="Resource not found",
                status_code=404,
            ) from exc
        except Exception as exc:
            raise RakitError(
                code=ErrorCode.DATASOURCE_FAILURE,
                message="Peewee detail query failed",
                status_code=500,
                cause=exc,
            ) from exc


__all__ = ["PeeweeDataSource"]
