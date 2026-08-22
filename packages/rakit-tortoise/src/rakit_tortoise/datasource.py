from __future__ import annotations

from typing import Any

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
from tortoise.expressions import Q
from tortoise.models import Model

from .introspection import (
    TortoiseModelMetadata,
    field_definitions,
    inspect_model,
    validate_field_policy,
)

_FILTER_SUFFIXES: dict[FilterOperator, str] = {
    FilterOperator.EQ: "",
    FilterOperator.LT: "__lt",
    FilterOperator.LTE: "__lte",
    FilterOperator.GT: "__gt",
    FilterOperator.GTE: "__gte",
    FilterOperator.CONTAINS: "__contains",
    FilterOperator.IN: "__in",
    FilterOperator.IS_NULL: "__isnull",
}


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


class TortoiseDataSource:
    capabilities = DataSourceCapabilities(
        read=True,
        pagination_strategies=frozenset({PaginationStrategy.PAGE, PaginationStrategy.LIMIT_OFFSET}),
    )

    def __init__(
        self,
        *,
        model: type[Model],
        field_policy: ResourceFieldPolicy,
    ) -> None:
        self._model = model
        self._metadata: TortoiseModelMetadata = inspect_model(model)
        self._field_policy = field_policy
        validate_field_policy(self._metadata, field_policy)
        self._field_definitions = field_definitions(self._metadata, field_policy)

    @property
    def fields(self) -> tuple[str, ...]:
        return self._metadata.field_names

    @property
    def identity_fields(self) -> tuple[str, ...]:
        return (self._metadata.identity_field,)

    @property
    def field_definitions(self) -> tuple[FieldDefinition, ...]:
        return self._field_definitions

    def _validate_filter(self, filter_: Filter) -> None:
        if filter_.field not in self._field_policy.filter_fields:
            raise _validation_error("Filter field is not allowed", field=filter_.field)

    def _apply_filter(self, queryset: Any, filter_: Filter) -> Any:
        self._validate_filter(filter_)
        if filter_.operator is FilterOperator.NEQ:
            return queryset.exclude(**{filter_.field: filter_.value})
        suffix = _FILTER_SUFFIXES.get(filter_.operator)
        if suffix is None:
            raise _validation_error("Filter operator is not supported", field=filter_.field)
        return queryset.filter(**{f"{filter_.field}{suffix}": filter_.value})

    def _apply_search(self, queryset: Any, search: str | None) -> Any:
        if not search:
            return queryset
        fields = self._field_policy.search_fields
        if not fields:
            raise _validation_error("Search is not enabled for this resource")
        expression: Q | None = None
        for field_name in fields:
            candidate = Q(**{f"{field_name}__icontains": search})
            expression = candidate if expression is None else expression | candidate
        assert expression is not None
        return queryset.filter(expression)

    def _apply_sorting(self, queryset: Any, query: ResourceQuery) -> Any:
        terms: list[str] = []
        for sort in (*query.sorting, *query.identity_tie_breakers):
            if sort.nulls is not NullPlacement.AUTO:
                raise _validation_error("Explicit NULL sort placement is not portable for Tortoise")
            if (
                sort.field not in self._field_policy.sort_fields
                and sort.field not in self.identity_fields
            ):
                raise _validation_error("Sort field is not allowed", field=sort.field)
            prefix = "-" if sort.direction.value == "desc" else ""
            terms.append(f"{prefix}{sort.field}")
        if not terms:
            terms.append(self._metadata.identity_field)
        return queryset.order_by(*terms)

    def _queryset(self, query: ResourceQuery) -> Any:
        queryset = self._model.all()
        try:
            for filter_ in query.filters:
                queryset = self._apply_filter(queryset, filter_)
            queryset = self._apply_search(queryset, query.search)
            return self._apply_sorting(queryset, query)
        except RakitError:
            raise
        except (TypeError, ValueError) as exc:
            raise _validation_error("Invalid persistence query", cause=exc) from exc

    async def count(self, query: ResourceQuery) -> int:
        queryset = self._queryset(query)
        try:
            return int(await queryset.count())
        except RakitError:
            raise
        except Exception as exc:
            raise RakitError(
                code=ErrorCode.DATASOURCE_FAILURE,
                message="Tortoise count query failed",
                status_code=500,
                cause=exc,
            ) from exc

    async def list(self, query: ResourceQuery) -> ResourceListResult[object]:
        queryset = self._queryset(query)
        pagination = query.pagination
        if isinstance(pagination, PagePagination):
            offset, limit = pagination.offset, pagination.per_page
        elif isinstance(pagination, LimitOffsetPagination):
            offset, limit = pagination.offset, pagination.limit
        else:
            raise _validation_error("Tortoise adapter does not support cursor pagination")

        try:
            total_count = (
                await queryset.count() if query.count_policy is CountPolicy.EXACT else None
            )
            fetched = tuple(await queryset.offset(offset).limit(limit + 1))
        except RakitError:
            raise
        except Exception as exc:
            raise RakitError(
                code=ErrorCode.DATASOURCE_FAILURE,
                message="Tortoise list query failed",
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

    def _identity_kwargs(self, identity: RecordIdentity) -> dict[str, Any]:
        values: dict[str, Any] = dict(identity.values)
        expected = self._metadata.identity_field
        if tuple(values) != (expected,):
            raise _validation_error("Invalid resource identity", field=expected)
        return values

    async def detail(self, identity: RecordIdentity) -> object:
        kwargs = self._identity_kwargs(identity)
        try:
            record = await self._model.get_or_none(**kwargs)
        except Exception as exc:
            raise RakitError(
                code=ErrorCode.DATASOURCE_FAILURE,
                message="Tortoise detail query failed",
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


__all__ = ["TortoiseDataSource"]
