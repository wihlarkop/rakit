"""Web-side wiring that turns a registered resource into real Starlette routes.

Core keeps `ResourceDefinition`/`RouteDefinition` framework-neutral (no Starlette
callables). This module owns the resource_id -> handler association: it builds a
`ResourceBinding` per resource and the list/detail `Route` objects that render
templates via `ResourceService`, the query parser, and the identity codec.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlencode
from uuid import UUID

from jinja2 import ChoiceLoader, FileSystemLoader, PackageLoader, pass_context, select_autoescape
from jinja2 import Environment as JinjaEnvironment
from jinja2.runtime import Context
from rakit_core.definitions import ResourceDefinition
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.identity import IdentityCodec, RecordIdentity
from rakit_core.query import (
    CountPolicy,
    Filter,
    FilterOperator,
    OffsetPagination,
    ResourceQuery,
    Sort,
    SortDirection,
)
from rakit_core.resources import ResourceService
from starlette.datastructures import QueryParams
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from ._paths import mounted_path as _mounted_path
from .assets import static_url
from .icons import render_icon

_PAGINATION_DEFAULTS = OffsetPagination()
_PAGE_SIZE_CHOICES = (25, 50, 100)
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


@pass_context
def _template_static_url(context: Context, name: str) -> str:
    url = static_url(name)
    request = context.get("request")
    if not isinstance(request, Request):
        return url
    return _mounted_path(request, url)


def build_templates(template_dirs: Sequence[Path]) -> Jinja2Templates:
    """Build a `Jinja2Templates` whose loader honours the override precedence.

    A single environment serves every resource: the resource-specific vs generic
    distinction is expressed by the candidate names passed to `select_template`
    (see `ResourceBinding.resolve_template`), so the loader only needs the user
    override roots (first match wins) followed by the built-in package templates.
    """
    loaders: list[FileSystemLoader | PackageLoader] = [
        FileSystemLoader(str(directory)) for directory in template_dirs
    ]
    loaders.append(PackageLoader("rakit_web", "templates"))
    environment = JinjaEnvironment(
        loader=ChoiceLoader(loaders),
        autoescape=select_autoescape(),
    )
    globals_ = cast(dict[str, Any], environment.globals)
    globals_["static_url"] = _template_static_url
    globals_["rakit_icon"] = render_icon
    return Jinja2Templates(env=environment)


def _field_value(item: object, field_name: str) -> object:
    if isinstance(item, dict):
        return item.get(field_name)
    return getattr(item, field_name, None)


def _display_value(value: object) -> object:
    return "—" if value is None else value


def _identity_values(item: object, identity_fields: Sequence[str]) -> dict[str, int | str]:
    values: dict[str, int | str] = {}
    for field_name in identity_fields:
        raw = _field_value(item, field_name)
        if isinstance(raw, UUID):
            values[field_name] = str(raw)
        elif isinstance(raw, int | str) and not isinstance(raw, bool):
            values[field_name] = raw
    return values


@dataclass(frozen=True)
class ResourceBinding:
    """Everything a request handler needs to serve one resource's pages."""

    definition: ResourceDefinition
    service: ResourceService
    templates: Jinja2Templates
    codec: IdentityCodec = field(default_factory=IdentityCodec)

    @property
    def resource_id(self) -> str:
        return self.definition.resource_id

    @property
    def list_route_name(self) -> str:
        return f"resource:{self.resource_id}:list"

    @property
    def detail_route_name(self) -> str:
        return f"resource:{self.resource_id}:detail"

    @property
    def count_route_name(self) -> str:
        return f"resource:{self.resource_id}:count"

    @property
    def count_path(self) -> str:
        return f"{self.definition.path}/_count"

    @property
    def detail_path(self) -> str:
        return f"{self.definition.path}/{{identity}}"

    def resolve_template(self, logical_name: str) -> str:
        """Resolve a logical name (e.g. ``list.html``) honouring override precedence."""
        candidates = [
            f"resources/{self.resource_id}/{logical_name}",
            f"resources/{logical_name}",
        ]
        template = self.templates.env.select_template(candidates)
        return template.name or candidates[-1]

    @property
    def fields(self) -> tuple[str, ...]:
        return self.definition.field_policy.list_fields

    @property
    def detail_fields(self) -> tuple[str, ...]:
        return self.definition.field_policy.detail_fields

    @property
    def filter_fields(self) -> tuple[str, ...]:
        return self.definition.field_policy.filter_fields

    @property
    def search_fields(self) -> tuple[str, ...]:
        return self.definition.field_policy.search_fields

    @property
    def sort_fields(self) -> tuple[str, ...]:
        return self.definition.field_policy.sort_fields

    @property
    def identity_fields(self) -> tuple[str, ...]:
        return self.service.data_source.identity_fields

    def parse_query(self, params: QueryParams) -> ResourceQuery:
        allowed_sort_fields = set(self.sort_fields)
        page = _parse_int(params.get("page"), _PAGINATION_DEFAULTS.page)
        per_page = _parse_int(params.get("per_page"), _PAGINATION_DEFAULTS.per_page)
        sort = params.get("sort")
        search = params.get("search") if self.search_fields else None
        filters = _parse_filters(params, set(self.filter_fields))
        count_policy = _parse_count_policy(params.get("count_policy"))
        try:
            return ResourceQuery.from_params(
                sort=sort,
                page=page,
                per_page=per_page,
                allowed_sort_fields=allowed_sort_fields,
                filters=filters,
                search=search,
                count_policy=count_policy,
            )
        except ValueError as exc:
            if "Contradictory sort field" in str(exc):
                raise RakitError(
                    code=ErrorCode.VALIDATION_FAILED,
                    message="Invalid sort query",
                    status_code=400,
                ) from None
            return ResourceQuery.from_params(
                page=_PAGINATION_DEFAULTS.page,
                per_page=_PAGINATION_DEFAULTS.per_page,
                allowed_sort_fields=allowed_sort_fields,
                filters=filters,
                search=search,
                count_policy=count_policy,
            )


def _parse_int(value: str | None, fallback: int) -> int:
    if value is None:
        return fallback
    try:
        return int(value)
    except ValueError:
        return fallback


def _parse_count_policy(value: str | None) -> CountPolicy:
    if value is None:
        return CountPolicy.EXACT
    try:
        return CountPolicy(value.strip().lower())
    except ValueError:
        return CountPolicy.EXACT


def _filter_value(operator: FilterOperator, raw_value: str, *, field_name: str) -> object:
    if operator is FilterOperator.IN:
        return [part for part in raw_value.split(",") if part]
    if operator is FilterOperator.IS_NULL:
        normalized_value = raw_value.strip().lower()
        if normalized_value == "true":
            return True
        if normalized_value == "false":
            return False
        raise RakitError(
            code=ErrorCode.VALIDATION_FAILED,
            message="Invalid filter value",
            status_code=400,
            details={"field": field_name, "operator": operator.value},
        )
    return raw_value


def _parse_filters(params: QueryParams, allowed_fields: set[str]) -> tuple[Filter, ...]:
    """Parse validated repeatable ``filter=<field>:<operator>:<value>`` params."""
    filters: list[Filter] = []
    for raw in params.getlist("filter"):
        parts = raw.split(":", 2)
        if len(parts) != 3:
            continue
        field_name, operator_token, raw_value = parts
        if field_name not in allowed_fields:
            continue
        try:
            operator = FilterOperator(operator_token.strip().lower())
        except ValueError:
            continue
        filters.append(
            Filter(
                field=field_name,
                operator=operator,
                value=_filter_value(operator, raw_value, field_name=field_name),
            )
        )
    return tuple(filters)


def _builder_filter(params: QueryParams, allowed_fields: set[str]) -> Filter | None:
    """Validate the no-JS filter-builder alias without making it canonical state."""
    field_name = params.get("filter_field")
    operator_token = params.get("filter_operator")
    raw_value = params.get("filter_value")
    if field_name is None and operator_token is None and raw_value is None:
        return None
    if field_name is None or operator_token is None or raw_value is None:
        return None
    if field_name not in allowed_fields:
        return None
    try:
        operator = FilterOperator(operator_token.strip().lower())
    except ValueError:
        return None
    return Filter(
        field=field_name,
        operator=operator,
        value=_filter_value(operator, raw_value, field_name=field_name),
    )


def _serialize_filter(filter_: Filter) -> str:
    if filter_.operator is FilterOperator.IN:
        if not isinstance(filter_.value, tuple) or not all(
            isinstance(item, str) for item in filter_.value
        ):
            raise RakitError(
                code=ErrorCode.VALIDATION_FAILED,
                message="Cannot safely render query controls",
                status_code=400,
            )
        raw_value = ",".join(cast(tuple[str, ...], filter_.value))
    elif filter_.operator is FilterOperator.IS_NULL:
        if not isinstance(filter_.value, bool):
            raise RakitError(
                code=ErrorCode.VALIDATION_FAILED,
                message="Cannot safely render query controls",
                status_code=400,
            )
        raw_value = "true" if filter_.value else "false"
    else:
        if not isinstance(filter_.value, str):
            raise RakitError(
                code=ErrorCode.VALIDATION_FAILED,
                message="Cannot safely render query controls",
                status_code=400,
            )
        raw_value = filter_.value
    return f"{filter_.field}:{filter_.operator.value}:{raw_value}"


def _explicit_sorting(raw_sort: str | None, fields: Sequence[str]) -> tuple[Sort, ...]:
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


def _sort_parameter(sorting: Sequence[Sort]) -> str:
    return ",".join(
        f"-{sort.field}" if sort.direction is SortDirection.DESC else sort.field for sort in sorting
    )


def _validated_query_params(
    query: ResourceQuery,
    explicit_sorting: Sequence[Sort],
) -> list[tuple[str, str]]:
    """Serialize only query state that survived resource-policy validation."""
    params = [("filter", _serialize_filter(filter_)) for filter_ in query.filters]
    if query.search:
        params.append(("search", query.search))
    if explicit_sorting:
        params.append(("sort", _sort_parameter(explicit_sorting)))
    params.append(("per_page", str(query.pagination.per_page)))
    params.append(("count_policy", query.count_policy.value))
    return params


def _resource_url(path: str, params: Sequence[tuple[str, str]]) -> str:
    return f"{path}?{urlencode(params)}" if params else path


def _page_url(path: str, params: Sequence[tuple[str, str]], page: int) -> str:
    return _resource_url(path, [*params, ("page", str(page))])


def _query_without_filters(query: ResourceQuery) -> ResourceQuery:
    return query.model_copy(update={"filters": ()})


def _query_without_search(query: ResourceQuery) -> ResourceQuery:
    return query.model_copy(update={"search": None})


def _display_filter_value(filter_: Filter) -> str:
    if filter_.operator is FilterOperator.IS_NULL:
        return ""
    if filter_.operator is FilterOperator.IN:
        if isinstance(filter_.value, tuple):
            return ", ".join(str(value) for value in filter_.value)
        return ""
    return str(filter_.value)


def _filter_presentations(
    query: ResourceQuery,
    explicit_sorting: Sequence[Sort],
    path: str,
) -> list[dict[str, str]]:
    presentations: list[dict[str, str]] = []
    for index, filter_ in enumerate(query.filters):
        remaining = (*query.filters[:index], *query.filters[index + 1 :])
        removal_query = query.model_copy(update={"filters": remaining})
        operator_label = _FILTER_OPERATOR_LABELS[filter_.operator]
        if filter_.operator is FilterOperator.IS_NULL and filter_.value is False:
            operator_label = "is not empty"
        presentations.append(
            {
                "field": filter_.field,
                "operator": filter_.operator.value,
                "operator_label": operator_label,
                "value": _display_filter_value(filter_),
                "serialized": _serialize_filter(filter_),
                "remove_url": _resource_url(
                    path,
                    _validated_query_params(removal_query, explicit_sorting),
                ),
            }
        )
    return presentations


def _filter_operator_options() -> list[dict[str, str]]:
    return [
        {"value": operator.value, "label": _FILTER_OPERATOR_LABELS[operator]}
        for operator in FilterOperator
    ]


def _page_size_options(per_page: int) -> list[dict[str, object]]:
    values = list(_PAGE_SIZE_CHOICES)
    if per_page not in values:
        values.insert(0, per_page)
    return [
        {
            "value": value,
            "label": f"{value} (custom)" if value not in _PAGE_SIZE_CHOICES else str(value),
            "selected": value == per_page,
        }
        for value in values
    ]


def _numbered_pages(
    *,
    total_pages: int,
    current_page: int,
    path: str,
    params: Sequence[tuple[str, str]],
) -> list[dict[str, object]]:
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
    items: list[dict[str, object]] = []
    previous_number: int | None = None
    for page_number in page_numbers:
        if previous_number is not None and page_number - previous_number > 1:
            items.append({"ellipsis": True})
        items.append(
            {
                "label": str(page_number),
                "href": _page_url(path, params, page_number),
                "current": page_number == current_page,
            }
        )
        previous_number = page_number
    return items


def _pagination_controls(
    query: ResourceQuery,
    path: str,
    explicit_sorting: Sequence[Sort],
    *,
    has_previous: bool,
    has_next: bool,
    total_count: int | None = None,
    item_count: int = 0,
) -> dict[str, object]:
    params = _validated_query_params(query, explicit_sorting)
    current_page = query.pagination.page
    context: dict[str, object] = {
        "current_page": current_page,
        "previous_url": _page_url(path, params, current_page - 1) if has_previous else "",
        "next_url": _page_url(path, params, current_page + 1) if has_next else "",
        "items": [],
        "total_pages": None,
        "range_start": None,
        "range_end": None,
        "total_count": total_count,
    }
    if query.count_policy is not CountPolicy.EXACT or total_count is None:
        return context
    total_pages = (
        (total_count + query.pagination.per_page - 1) // query.pagination.per_page
        if total_count
        else 0
    )
    context["total_pages"] = total_pages
    context["range_start"] = query.pagination.offset + 1 if item_count else 0
    context["range_end"] = query.pagination.offset + item_count
    context["items"] = _numbered_pages(
        total_pages=total_pages,
        current_page=current_page,
        path=path,
        params=params,
    )
    return context


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
    return _sort_parameter(updated)


def _sort_headers(
    fields: Sequence[str],
    query: ResourceQuery,
    path: str,
    explicit_sorting: Sequence[Sort],
    allowed_sort_fields: set[str],
) -> list[dict[str, str]]:
    """Build per-column sort-toggle state while preserving validated query state."""
    primary = explicit_sorting[0] if explicit_sorting else None
    explicit_fields = {sort.field for sort in explicit_sorting}
    preserved_params = [("filter", _serialize_filter(filter_)) for filter_ in query.filters]
    if query.search:
        preserved_params.append(("search", query.search))
    preserved_params.append(("per_page", str(query.pagination.per_page)))
    if query.count_policy is not CountPolicy.EXACT:
        preserved_params.append(("count_policy", query.count_policy.value))
    headers: list[dict[str, str]] = []
    for field_name in fields:
        if field_name not in allowed_sort_fields:
            headers.append({"field": field_name, "url": "", "sort_value": "", "aria_sort": "none"})
            continue
        next_sort = _toggle_explicit_sort(explicit_sorting, field_name)
        params: list[tuple[str, str]] = [("sort", next_sort), *preserved_params]
        aria_sort = "none"
        if primary is not None and primary.field == field_name:
            aria_sort = "ascending" if primary.direction is SortDirection.ASC else "descending"
        elif field_name in explicit_fields:
            aria_sort = "other"
        headers.append(
            {
                "field": field_name,
                "url": _resource_url(path, params),
                "sort_value": next_sort,
                "aria_sort": aria_sort,
            }
        )
    return headers


def build_resource_routes(binding: ResourceBinding) -> list[Route]:
    async def resource_list(request: Request) -> Response:
        query = binding.parse_query(request.query_params)
        resource_path = _mounted_path(request, binding.definition.path)
        explicit_sorting = _explicit_sorting(request.query_params.get("sort"), binding.sort_fields)
        builder_filter = _builder_filter(request.query_params, set(binding.filter_fields))
        if builder_filter is not None:
            canonical_query = query.model_copy(update={"filters": (*query.filters, builder_filter)})
            return RedirectResponse(
                _resource_url(
                    resource_path,
                    _validated_query_params(canonical_query, explicit_sorting),
                ),
                status_code=303,
            )

        page = await binding.service.list(query)
        fields = binding.fields
        rows: list[dict[str, object]] = []
        for item in page.items:
            identity_values = _identity_values(item, binding.identity_fields)
            detail_url = ""
            if identity_values:
                encoded = binding.codec.encode(RecordIdentity(values=identity_values))
                detail_url = _mounted_path(
                    request,
                    binding.detail_path.replace("{identity}", encoded),
                )
            cells = [_field_value(item, field_name) for field_name in fields]
            rows.append(
                {
                    "cells": cells,
                    "display_cells": [_display_value(value) for value in cells],
                    "detail_url": detail_url,
                }
            )

        table_template = binding.resolve_template("_table.html")
        logical_name = (
            table_template if _is_htmx(request) else binding.resolve_template("list.html")
        )
        validated_params = _validated_query_params(query, explicit_sorting)
        count_url = _mounted_path(request, binding.count_path)
        if validated_params:
            count_url = _resource_url(count_url, validated_params)
        filter_values = [_serialize_filter(filter_) for filter_ in query.filters]
        filter_presentations = _filter_presentations(query, explicit_sorting, resource_path)
        context = {
            "resource": binding.definition,
            "page": page,
            "query": query,
            "fields": fields,
            "rows": rows,
            "resource_path": resource_path,
            "count_url": count_url,
            "sort_headers": _sort_headers(
                fields,
                query,
                resource_path,
                explicit_sorting,
                set(binding.sort_fields),
            ),
            "pagination": _pagination_controls(
                query,
                resource_path,
                explicit_sorting,
                has_previous=page.has_previous,
                has_next=page.has_next,
                total_count=page.total_count,
                item_count=len(page.items),
            ),
            "search_value": query.search or "",
            "search_enabled": bool(binding.search_fields),
            "clear_search_url": _resource_url(
                resource_path,
                _validated_query_params(_query_without_search(query), explicit_sorting),
            ),
            "filter_enabled": bool(binding.filter_fields),
            "filter_fields": binding.filter_fields,
            "filter_operators": _filter_operator_options(),
            "filter_values": filter_values,
            "filter_presentations": filter_presentations,
            "active_filter_count": len(filter_presentations),
            "clear_filters_url": _resource_url(
                resource_path,
                _validated_query_params(_query_without_filters(query), explicit_sorting),
            ),
            "has_active_query": bool(query.search or query.filters),
            "sort_value": _sort_parameter(explicit_sorting),
            "per_page_value": str(query.pagination.per_page),
            "page_size_options": _page_size_options(query.pagination.per_page),
            "table_template": table_template,
        }
        return binding.templates.TemplateResponse(
            request,
            logical_name,
            context,
            headers={"Cache-Control": "no-store"},
        )

    async def resource_count(request: Request) -> Response:
        query = binding.parse_query(request.query_params)
        total = await binding.service.count(query)
        return binding.templates.TemplateResponse(
            request,
            binding.resolve_template("_count.html"),
            {"resource": binding.definition, "total": total},
            headers={"Cache-Control": "no-store"},
        )

    async def resource_detail(request: Request) -> Response:
        try:
            identity = binding.codec.decode(request.path_params["identity"])
        except ValueError as exc:
            raise RakitError(
                code=ErrorCode.VALIDATION_FAILED,
                message="Invalid resource identity",
                status_code=400,
                cause=exc,
            ) from exc
        if set(identity.values) != set(binding.identity_fields):
            raise RakitError(
                code=ErrorCode.VALIDATION_FAILED,
                message="Invalid resource identity",
                status_code=400,
            )
        record = await binding.service.detail(identity)
        fields = binding.detail_fields
        context = {
            "resource": binding.definition,
            "record": record,
            "fields": fields,
            "cells": {field_name: _field_value(record, field_name) for field_name in fields},
        }
        return binding.templates.TemplateResponse(
            request,
            binding.resolve_template("detail.html"),
            context,
            headers={"Cache-Control": "no-store"},
        )

    return [
        Route(
            binding.definition.path,
            resource_list,
            name=binding.list_route_name,
            methods=["GET"],
        ),
        Route(
            binding.count_path,
            resource_count,
            name=binding.count_route_name,
            methods=["GET"],
        ),
        Route(
            binding.detail_path,
            resource_detail,
            name=binding.detail_route_name,
            methods=["GET"],
        ),
    ]


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"
