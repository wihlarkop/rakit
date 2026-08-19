from __future__ import annotations
from http import HTTPStatus

from collections.abc import Sequence
from typing import Any
from urllib.parse import urlencode

from rakit_core.definitions import ResourceDefinition
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.filters import (
    FilterControl,
    FilterOperator,
    FilterSelection,
    ResourceFilter,
    effective_resource_filters,
    resolve_filter_selection,
)
from rakit_core.pagination import (
    CursorPageResult,
    CursorPagination,
    LimitOffsetPagination,
    LimitOffsetResult,
    PagePagination,
    PageResult,
    PaginationStrategy,
    ResourceListResult,
    ResourcePagination,
    ResourcePaginationPolicy,
)
from rakit_core.query import CountPolicy, ResourceQuery, Sort, SortDirection
from starlette.datastructures import QueryParams

_FILTER_OPERATOR_LABELS = {
    FilterOperator.EQ: "equals",
    FilterOperator.NEQ: "does not equal",
    FilterOperator.LT: "is less than",
    FilterOperator.LTE: "is less than or equal to",
    FilterOperator.GT: "is greater than",
    FilterOperator.GTE: "is greater than or equal to",
    FilterOperator.CONTAINS: "contains",
    FilterOperator.IN: "is one of",
    FilterOperator.IS_NULL: "is empty",
}
_FILTER_OPERATOR_SHORT_LABELS = {
    FilterOperator.EQ: "=",
    FilterOperator.NEQ: "≠",
    FilterOperator.LT: "<",
    FilterOperator.LTE: "≤",
    FilterOperator.GT: ">",
    FilterOperator.GTE: "≥",
    FilterOperator.CONTAINS: "contains",
    FilterOperator.IN: "in",
    FilterOperator.IS_NULL: "is empty",
}


def resource_filter_definitions(definition: ResourceDefinition) -> tuple[ResourceFilter, ...]:
    return effective_resource_filters(definition.filters, definition.field_policy.filter_fields)


def _parse_int(value: str | None, fallback: int, *, minimum: int) -> int:
    if value is None:
        return fallback
    try:
        parsed = int(value)
    except ValueError:
        return fallback
    return parsed if parsed >= minimum else fallback


def _parse_count_policy(value: str | None) -> CountPolicy:
    if value is None:
        return CountPolicy.EXACT
    try:
        return CountPolicy(value.strip().lower())
    except ValueError:
        return CountPolicy.EXACT


def _validated_size(params: QueryParams, policy: ResourcePaginationPolicy) -> int:
    name = "per_page" if policy.strategy is PaginationStrategy.PAGE else "limit"
    raw = params.get(name)
    size = _parse_int(raw, policy.size.default, minimum=1)
    return size if policy.size.accepts(size) else policy.size.default


def _pagination_request(
    params: QueryParams,
    policy: ResourcePaginationPolicy,
) -> ResourcePagination:
    size = _validated_size(params, policy)
    if policy.strategy is PaginationStrategy.PAGE:
        return PagePagination(
            page=_parse_int(params.get("page"), 1, minimum=1),
            per_page=size,
        )
    if policy.strategy is PaginationStrategy.LIMIT_OFFSET:
        return LimitOffsetPagination(
            offset=_parse_int(params.get("offset"), 0, minimum=0),
            limit=size,
        )
    cursor = params.get("cursor")
    if cursor == "":
        cursor = None
    return CursorPagination(cursor=cursor, limit=size)


def _resolve_canonical_filters(
    params: QueryParams,
    definitions: tuple[ResourceFilter, ...],
) -> tuple[tuple[FilterSelection, ...], tuple[Any, ...]]:
    by_id = {definition.filter_id: definition for definition in definitions}
    selections: list[FilterSelection] = []
    predicates: list[Any] = []
    for raw in params.getlist("filter"):
        parts = raw.split(":", 2)
        if len(parts) != 3:
            continue
        filter_id, operator_token, raw_value = parts
        definition = by_id.get(filter_id)
        if definition is None:
            continue
        try:
            operator = FilterOperator(operator_token.strip().lower())
            resolved = resolve_filter_selection(
                definition,
                operator=operator,
                raw_value=raw_value,
            )
        except (TypeError, ValueError):
            continue
        selections.append(resolved.selection)
        predicates.extend(resolved.predicates)
    return tuple(selections), tuple(predicates)


def parse_resource_query(
    definition: ResourceDefinition,
    identity_fields: Sequence[str],
    params: QueryParams,
) -> ResourceQuery:
    definitions = resource_filter_definitions(definition)
    selections, predicates = _resolve_canonical_filters(params, definitions)
    pagination = _pagination_request(params, definition.pagination)
    sort = params.get("sort")
    search = params.get("search") if definition.field_policy.search_fields else None
    count_policy = _parse_count_policy(params.get("count_policy"))
    try:
        return ResourceQuery.from_components(
            sort=sort,
            pagination=pagination,
            allowed_sort_fields=definition.field_policy.sort_fields,
            identity_fields=identity_fields,
            filters=predicates,
            filter_selections=selections,
            search=search,
            count_policy=count_policy,
        )
    except ValueError as exc:
        if "Contradictory sort field" in str(exc):
            raise RakitError(
                code=ErrorCode.VALIDATION_FAILED,
                message="Invalid sort query",
                status_code=HTTPStatus.BAD_REQUEST,
            ) from None
        return ResourceQuery.from_components(
            pagination=pagination,
            allowed_sort_fields=definition.field_policy.sort_fields,
            identity_fields=identity_fields,
            filters=predicates,
            filter_selections=selections,
            search=search,
            count_policy=count_policy,
        )


def explicit_sorting(raw_sort: str | None, fields: Sequence[str]) -> tuple[Sort, ...]:
    if raw_sort is None:
        return ()
    try:
        return ResourceQuery.from_params(
            sort=raw_sort,
            allowed_sort_fields=set(fields),
            identity_fields=(),
        ).sorting
    except ValueError:
        return ()


def sort_parameter(sorting: Sequence[Sort]) -> str:
    return ",".join(
        f"-{sort.field}" if sort.direction is SortDirection.DESC else sort.field for sort in sorting
    )


def _definition_map(definitions: Sequence[ResourceFilter]) -> dict[str, ResourceFilter]:
    return {definition.filter_id: definition for definition in definitions}


def serialize_selection(selection: FilterSelection, definition: ResourceFilter) -> str:
    raw = definition.serialize_value(operator=selection.operator, value=selection.value)
    return f"{selection.filter_id}:{selection.operator.value}:{raw}"


def _flatten_selections(
    selections: Sequence[FilterSelection],
    definitions: Sequence[ResourceFilter],
) -> tuple[Any, ...]:
    by_id = _definition_map(definitions)
    predicates: list[Any] = []
    for selection in selections:
        definition = by_id.get(selection.filter_id)
        if definition is None:
            continue
        resolved = resolve_filter_selection(
            definition,
            operator=selection.operator,
            raw_value=selection.value,
        )
        predicates.extend(resolved.predicates)
    return tuple(predicates)


def query_with_selections(
    query: ResourceQuery,
    selections: Sequence[FilterSelection],
    definitions: Sequence[ResourceFilter],
) -> ResourceQuery:
    selected = tuple(selections)
    return query.model_copy(
        update={
            "filter_selections": selected,
            "filters": _flatten_selections(selected, definitions),
        }
    )


def query_without_search(query: ResourceQuery) -> ResourceQuery:
    return query.model_copy(update={"search": None})


def query_without_filters(query: ResourceQuery) -> ResourceQuery:
    return query.model_copy(update={"filters": (), "filter_selections": ()})


def resource_url(path: str, params: Sequence[tuple[str, str]]) -> str:
    return f"{path}?{urlencode(params)}" if params else path


def _size_param(pagination: ResourcePagination) -> tuple[str, str]:
    if isinstance(pagination, PagePagination):
        return "per_page", str(pagination.per_page)
    return "limit", str(pagination.limit)


def validated_query_params(
    query: ResourceQuery,
    explicit: Sequence[Sort],
    definitions: Sequence[ResourceFilter],
) -> list[tuple[str, str]]:
    by_id = _definition_map(definitions)
    params: list[tuple[str, str]] = []
    for selection in query.filter_selections:
        definition = by_id.get(selection.filter_id)
        if definition is not None:
            params.append(("filter", serialize_selection(selection, definition)))
    if query.search:
        params.append(("search", query.search))
    if explicit:
        params.append(("sort", sort_parameter(explicit)))
    params.append(_size_param(query.pagination))
    if query.count_policy is not CountPolicy.EXACT:
        params.append(("count_policy", query.count_policy.value))
    return params


def _replace_filter_id(
    query: ResourceQuery,
    filter_id: str,
    replacements: Sequence[FilterSelection],
    definitions: Sequence[ResourceFilter],
) -> ResourceQuery:
    retained = [
        selection for selection in query.filter_selections if selection.filter_id != filter_id
    ]
    return query_with_selections(query, (*retained, *replacements), definitions)


def builder_selections(
    params: QueryParams,
    definitions: Sequence[ResourceFilter],
) -> tuple[FilterSelection, ...]:
    by_id = _definition_map(definitions)
    filter_id = params.get("filter_id") or params.get("filter_field")
    if filter_id is None:
        return ()
    definition = by_id.get(filter_id)
    if definition is None:
        return ()

    if definition.control is FilterControl.DATE_RANGE:
        resolved: list[FilterSelection] = []
        for name, operator in (
            ("filter_start", FilterOperator.GTE),
            ("filter_end", FilterOperator.LTE),
        ):
            raw_value = params.get(name)
            if not raw_value:
                continue
            try:
                selection = resolve_filter_selection(
                    definition,
                    operator=operator,
                    raw_value=raw_value,
                ).selection
            except (TypeError, ValueError):
                continue
            resolved.append(selection)
        return tuple(resolved)

    operator_token = params.get("filter_operator")
    raw_value = params.get("filter_value")
    if operator_token is None or raw_value is None:
        return ()
    try:
        operator = FilterOperator(operator_token.strip().lower())
        return (
            resolve_filter_selection(
                definition,
                operator=operator,
                raw_value=raw_value,
            ).selection,
        )
    except (TypeError, ValueError):
        return ()


def canonical_builder_query(
    query: ResourceQuery,
    params: QueryParams,
    definitions: Sequence[ResourceFilter],
) -> ResourceQuery | None:
    selections = builder_selections(params, definitions)
    if not selections:
        return None
    filter_id = selections[0].filter_id
    # Choice/boolean/date-range controls represent one semantic group and replace
    # the previous selection(s) for that filter id. Text/number/date/legacy inputs
    # remain additive so multiple operator constraints stay possible.
    definition = _definition_map(definitions)[filter_id]
    if definition.control in {
        FilterControl.CHOICE,
        FilterControl.BOOLEAN,
        FilterControl.DATE_RANGE,
    }:
        return _replace_filter_id(query, filter_id, selections, definitions)
    return query_with_selections(query, (*query.filter_selections, *selections), definitions)


def _operator_options(definition: ResourceFilter) -> list[dict[str, str]]:
    return [
        {"value": operator.value, "label": _FILTER_OPERATOR_LABELS[operator]}
        for operator in definition.operators
    ]


def _selection_remove_url(
    query: ResourceQuery,
    index: int,
    path: str,
    explicit: Sequence[Sort],
    definitions: Sequence[ResourceFilter],
) -> str:
    remaining = (*query.filter_selections[:index], *query.filter_selections[index + 1 :])
    next_query = query_with_selections(query, remaining, definitions)
    return resource_url(path, validated_query_params(next_query, explicit, definitions))


def filter_presentations(
    query: ResourceQuery,
    explicit: Sequence[Sort],
    path: str,
    definitions: Sequence[ResourceFilter],
) -> list[dict[str, str]]:
    by_id = _definition_map(definitions)
    presentations: list[dict[str, str]] = []
    for index, selection in enumerate(query.filter_selections):
        definition = by_id.get(selection.filter_id)
        if definition is None:
            continue
        value = definition.display_value(operator=selection.operator, value=selection.value)
        operator_label = _FILTER_OPERATOR_SHORT_LABELS[selection.operator]
        if selection.operator is FilterOperator.IS_NULL and selection.value is False:
            operator_label = "is not empty"
        if definition.control in {FilterControl.CHOICE, FilterControl.BOOLEAN}:
            chip_label = f"{definition.label}: {value}"
        elif selection.operator is FilterOperator.IS_NULL:
            chip_label = f"{definition.label} {operator_label}"
        else:
            chip_label = f"{definition.label} {operator_label} {value}"
        presentations.append(
            {
                "filter_id": selection.filter_id,
                "label": definition.label,
                "value": value,
                "operator": selection.operator.value,
                "operator_label": operator_label,
                "chip_label": chip_label,
                "remove_url": _selection_remove_url(
                    query,
                    index,
                    path,
                    explicit,
                    definitions,
                ),
            }
        )
    return presentations


def filter_groups(
    query: ResourceQuery,
    explicit: Sequence[Sort],
    path: str,
    definitions: Sequence[ResourceFilter],
) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for definition in definitions:
        active = tuple(
            selection
            for selection in query.filter_selections
            if selection.filter_id == definition.filter_id
        )
        group: dict[str, Any] = {
            "filter_id": definition.filter_id,
            "label": definition.label,
            "control": definition.control.value,
            "operators": _operator_options(definition),
            "active": bool(active),
            "all_url": resource_url(
                path,
                validated_query_params(
                    _replace_filter_id(query, definition.filter_id, (), definitions),
                    explicit,
                    definitions,
                ),
            ),
            "choices": [],
        }
        if definition.control is FilterControl.CHOICE:
            choice_rows: list[dict[str, Any]] = []
            for choice in definition.choices:
                resolved = resolve_filter_selection(
                    definition,
                    operator=definition.operators[0],
                    raw_value=choice.value,
                )
                next_query = _replace_filter_id(
                    query,
                    definition.filter_id,
                    (resolved.selection,),
                    definitions,
                )
                choice_rows.append(
                    {
                        "value": choice.value,
                        "label": choice.label,
                        "selected": any(selection.value == choice.value for selection in active),
                        "url": resource_url(
                            path,
                            validated_query_params(next_query, explicit, definitions),
                        ),
                    }
                )
            group["choices"] = choice_rows
        elif definition.control is FilterControl.BOOLEAN:
            boolean_rows: list[dict[str, Any]] = []
            for raw_value, label in (("true", "Yes"), ("false", "No")):
                resolved = resolve_filter_selection(
                    definition,
                    operator=FilterOperator.EQ,
                    raw_value=raw_value,
                )
                next_query = _replace_filter_id(
                    query,
                    definition.filter_id,
                    (resolved.selection,),
                    definitions,
                )
                boolean_rows.append(
                    {
                        "value": raw_value,
                        "label": label,
                        "selected": any(
                            selection.value == resolved.selection.value for selection in active
                        ),
                        "url": resource_url(
                            path,
                            validated_query_params(next_query, explicit, definitions),
                        ),
                    }
                )
            group["choices"] = boolean_rows
        groups.append(group)
    return groups


def page_size_options(
    query: ResourceQuery, policy: ResourcePaginationPolicy
) -> list[dict[str, Any]]:
    current = (
        query.pagination.per_page
        if isinstance(query.pagination, PagePagination)
        else query.pagination.limit
    )
    return [
        {"value": value, "label": str(value), "selected": value == current}
        for value in policy.size.allowed
    ]


def page_size_param(query: ResourceQuery) -> str:
    return "per_page" if isinstance(query.pagination, PagePagination) else "limit"


def page_size_value(query: ResourceQuery) -> str:
    return _size_param(query.pagination)[1]


def _toggle_explicit_sort(sorting: Sequence[Sort], field_name: str) -> str:
    updated = list(sorting)
    for index, sort in enumerate(updated):
        if sort.field != field_name:
            continue
        direction = SortDirection.DESC if sort.direction is SortDirection.ASC else SortDirection.ASC
        updated[index] = sort.model_copy(update={"direction": direction})
        break
    else:
        updated.append(Sort(field=field_name))
    return sort_parameter(updated)


def sort_headers(
    fields: Sequence[str],
    query: ResourceQuery,
    path: str,
    explicit: Sequence[Sort],
    allowed_sort_fields: set[str],
    definitions: Sequence[ResourceFilter],
) -> list[dict[str, str]]:
    primary = explicit[0] if explicit else None
    explicit_by_field = {sort.field: sort for sort in explicit}
    preserved = validated_query_params(query, (), definitions)
    headers: list[dict[str, str]] = []
    for field_name in fields:
        if field_name not in allowed_sort_fields:
            headers.append(
                {
                    "field": field_name,
                    "url": "",
                    "sort_value": "",
                    "aria_sort": "none",
                    "state": "none",
                }
            )
            continue
        next_sort = _toggle_explicit_sort(explicit, field_name)
        current = explicit_by_field.get(field_name)
        aria_sort = "none"
        state = "unsorted"
        if primary is not None and primary.field == field_name:
            aria_sort = "ascending" if primary.direction is SortDirection.ASC else "descending"
            state = aria_sort
        elif current is not None:
            aria_sort = "other"
            state = "secondary"
        params = [("sort", next_sort), *(item for item in preserved if item[0] != "sort")]
        headers.append(
            {
                "field": field_name,
                "url": resource_url(path, params),
                "sort_value": next_sort,
                "aria_sort": aria_sort,
                "state": state,
            }
        )
    return headers


def _numbered_pages(
    *,
    total_pages: int,
    current_page: int,
    path: str,
    params: Sequence[tuple[str, str]],
) -> list[dict[str, Any]]:
    if total_pages < 1 or current_page < 1 or current_page > total_pages:
        return []
    if total_pages <= 7:
        page_numbers = list(range(1, total_pages + 1))
    else:
        page_numbers = sorted(
            {
                1,
                total_pages,
                max(1, current_page - 1),
                current_page,
                min(total_pages, current_page + 1),
            }
        )
    items: list[dict[str, Any]] = []
    previous: int | None = None
    for page_number in page_numbers:
        if previous is not None and page_number - previous > 1:
            items.append({"ellipsis": True})
        items.append(
            {
                "label": str(page_number),
                "href": resource_url(path, [*params, ("page", str(page_number))]),
                "current": page_number == current_page,
            }
        )
        previous = page_number
    return items


def pagination_controls(
    query: ResourceQuery,
    result: ResourceListResult,
    path: str,
    explicit: Sequence[Sort],
    definitions: Sequence[ResourceFilter],
) -> dict[str, Any]:
    params = validated_query_params(query, explicit, definitions)
    base: dict[str, Any] = {
        "strategy": "",
        "current_page": None,
        "previous_url": "",
        "next_url": "",
        "items": [],
        "total_pages": None,
        "range_start": None,
        "range_end": None,
        "total_count": None,
    }
    if isinstance(result, PageResult) and isinstance(query.pagination, PagePagination):
        page = query.pagination
        base.update(
            {
                "strategy": PaginationStrategy.PAGE.value,
                "current_page": page.page,
                "previous_url": (
                    resource_url(path, [*params, ("page", str(page.page - 1))])
                    if result.has_previous
                    else ""
                ),
                "next_url": (
                    resource_url(path, [*params, ("page", str(page.page + 1))])
                    if result.has_next
                    else ""
                ),
                "total_count": result.total_count,
            }
        )
        if query.count_policy is CountPolicy.EXACT and result.total_count is not None:
            total_pages = (
                (result.total_count + page.per_page - 1) // page.per_page
                if result.total_count
                else 0
            )
            base["total_pages"] = total_pages
            base["range_start"] = page.offset + 1 if result.items else 0
            base["range_end"] = page.offset + len(result.items)
            base["items"] = _numbered_pages(
                total_pages=total_pages,
                current_page=page.page,
                path=path,
                params=params,
            )
        return base

    if isinstance(result, LimitOffsetResult) and isinstance(
        query.pagination, LimitOffsetPagination
    ):
        pagination = query.pagination
        base.update(
            {
                "strategy": PaginationStrategy.LIMIT_OFFSET.value,
                "previous_url": (
                    resource_url(
                        path,
                        [
                            *params,
                            ("offset", str(max(0, pagination.offset - pagination.limit))),
                        ],
                    )
                    if result.has_previous
                    else ""
                ),
                "next_url": (
                    resource_url(
                        path,
                        [*params, ("offset", str(pagination.offset + pagination.limit))],
                    )
                    if result.has_next
                    else ""
                ),
                "range_start": pagination.offset + 1 if result.items else 0,
                "range_end": pagination.offset + len(result.items),
                "total_count": result.total_count,
            }
        )
        return base

    if isinstance(result, CursorPageResult) and isinstance(query.pagination, CursorPagination):
        base.update(
            {
                "strategy": PaginationStrategy.CURSOR.value,
                "previous_url": (
                    resource_url(path, [*params, ("cursor", result.previous_cursor)])
                    if result.previous_cursor
                    else ""
                ),
                "next_url": (
                    resource_url(path, [*params, ("cursor", result.next_cursor)])
                    if result.next_cursor
                    else ""
                ),
            }
        )
        return base

    raise RakitError(
        code=ErrorCode.INTERNAL_ERROR,
        message="Data source returned pagination metadata incompatible with the resource query.",
        status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
        details={"reason": "pagination_result_mismatch"},
    )


def hidden_query_inputs(
    query: ResourceQuery,
    explicit: Sequence[Sort],
    definitions: Sequence[ResourceFilter],
    *,
    omit: frozenset[str] = frozenset(),
) -> list[dict[str, str]]:
    return [
        {"name": name, "value": value}
        for name, value in validated_query_params(query, explicit, definitions)
        if name not in omit
    ]


__all__ = [
    "canonical_builder_query",
    "explicit_sorting",
    "filter_groups",
    "filter_presentations",
    "hidden_query_inputs",
    "page_size_options",
    "page_size_param",
    "page_size_value",
    "pagination_controls",
    "parse_resource_query",
    "query_without_filters",
    "query_without_search",
    "resource_filter_definitions",
    "resource_url",
    "sort_headers",
    "sort_parameter",
    "validated_query_params",
]
