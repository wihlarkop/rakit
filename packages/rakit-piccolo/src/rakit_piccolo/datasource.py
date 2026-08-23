from __future__ import annotations

from typing import Any

from piccolo.engine.base import Engine
from piccolo.table import Table
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
    PiccoloModelMetadata,
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


class PiccoloDataSource:
    capabilities = DataSourceCapabilities(
        read=True,
        pagination_strategies=frozenset({PaginationStrategy.PAGE, PaginationStrategy.LIMIT_OFFSET}),
    )

    def __init__(
        self,
        *,
        model: type[Table],
        engine: Engine[Any],
        field_policy: ResourceFieldPolicy,
    ) -> None:
        self._engine = engine
        self._metadata: PiccoloModelMetadata = inspect_model(model, engine=engine)
        self._model = self._metadata.model
        self._field_policy = field_policy
        validate_field_policy(self._metadata, field_policy)
        self._field_definitions = field_definitions(self._metadata, field_policy)
        self._fields_by_name = {field.name: field for field in self._metadata.fields}

    @property
    def engine(self) -> Engine[Any]:
        return self._engine

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
        return metadata.column

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
            return field.like(f"%{filter_.value}%")
        if filter_.operator is FilterOperator.IN:
            return field.is_in(filter_.value)
        if filter_.operator is FilterOperator.IS_NULL:
            return field.is_null() if bool(filter_.value) else field.is_not_null()
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
        pattern = f"%{search}%"
        for field_name in fields:
            candidate = self._field(field_name).ilike(pattern)
            expression = candidate if expression is None else expression | candidate
        assert expression is not None
        return query.where(expression)

    def _apply_sorting(self, query: Any, resource_query: ResourceQuery) -> Any:
        sorting = (*resource_query.sorting, *resource_query.identity_tie_breakers)
        if not sorting:
            return query.order_by(self._field(self._metadata.identity_field))
        for sort in sorting:
            if sort.nulls is not NullPlacement.AUTO:
                raise _validation_error("Explicit NULL sort placement is not portable for Piccolo")
            if (
                sort.field not in self._field_policy.sort_fields
                and sort.field not in self.identity_fields
            ):
                raise _validation_error("Sort field is not allowed", field=sort.field)
            query = query.order_by(
                self._field(sort.field),
                ascending=sort.direction.value != "desc",
            )
        return query

    def _filtered_query(self, resource_query: ResourceQuery, *, count: bool = False) -> Any:
        base = self._model.count() if count else self._model.objects()
        try:
            return self._apply_filters_and_search(base, resource_query)
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
        try:
            return int(await self._filtered_query(query, count=True))
        except RakitError:
            raise
        except Exception as exc:
            raise RakitError(
                code=ErrorCode.DATASOURCE_FAILURE,
                message="Piccolo count query failed",
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
            raise _validation_error("Piccolo adapter does not support cursor pagination")

        try:
            total_count = (
                int(await self._filtered_query(query, count=True))
                if query.count_policy is CountPolicy.EXACT
                else None
            )
            fetched = tuple(await queryset.offset(offset).limit(limit + 1))
        except RakitError:
            raise
        except Exception as exc:
            raise RakitError(
                code=ErrorCode.DATASOURCE_FAILURE,
                message="Piccolo list query failed",
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
            record = await self._model.objects().where(identity_field == identity_value).first()
        except Exception as exc:
            raise RakitError(
                code=ErrorCode.DATASOURCE_FAILURE,
                message="Piccolo detail query failed",
                status_code=500,
                cause=exc,
            ) from exc
        if record is None:
            raise RakitError(
                code=ErrorCode.RESOURCE_NOT_FOUND,
                message="Resource not found",
                status_code=404,
            )
        return record


__all__ = ["PiccoloDataSource"]
