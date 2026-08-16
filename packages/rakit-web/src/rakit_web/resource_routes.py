"""Web-side wiring that turns a registered resource into real Starlette routes.

Core keeps `ResourceDefinition`/`RouteDefinition` framework-neutral (no Starlette
callables). This module owns the resource_id -> handler association: it builds a
`ResourceBinding` per resource and the list/detail `Route` objects that render
templates via `ResourceService`, the query parser, and the identity codec.
"""

from collections.abc import Callable, Sequence
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
from starlette.responses import Response
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from ._paths import mounted_path as _mounted_path
from .assets import static_url

_PAGINATION_DEFAULTS = OffsetPagination()


@pass_context
def _template_static_url(context: Context, name: str) -> str:
    url = static_url(name)
    request = context.get("request")
    if not isinstance(request, Request):
        return url
    return _mounted_path(request, url)


def build_templates(
    template_dirs: Sequence[Path],
    *,
    navigation_provider: Callable[[Request], object] | None = None,
) -> Jinja2Templates:
    """Build templates with user overrides and optional admin-shell navigation."""

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
    if navigation_provider is not None:
        globals_["rakit_navigation"] = navigation_provider
    return Jinja2Templates(env=environment)


def _field_value(item: object, field_name: str) -> object:
    if isinstance(item, dict):
        return item.get(field_name)
    return getattr(item, field_name, None)


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
        """Resolve a logical name honouring user override precedence."""
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
    def resource_path(self) -> str:
        return self.definition.path


def _query_values(params: QueryParams, key: str) -> tuple[str, ...]:
    return tuple(params.getlist(key))


def _parse_filters(binding: ResourceBinding, params: QueryParams) -> tuple[Filter, ...]:
    filters: list[Filter] = []
    allowed = set(binding.filter_fields)
    for value in _query_values(params, "filter"):
        field_name, separator, raw = value.partition(":")
        if not separator or field_name not in allowed:
            continue
        filters.append(Filter(field=field_name, operator=FilterOperator.EQ, value=raw))
    return tuple(filters)


def _parse_sorting(binding: ResourceBinding, params: QueryParams) -> tuple[Sort, ...]:
    values = _query_values(params, "sort")
    allowed = set(binding.sort_fields)
    sorting: list[Sort] = []
    for value in values:
        direction = SortDirection.ASC
        field_name = value
        if value.startswith("-"):
            direction = SortDirection.DESC
            field_name = value[1:]
        if field_name in allowed:
            sorting.append(Sort(field=field_name, direction=direction))
    return tuple(sorting)


def _parse_query(binding: ResourceBinding, request: Request) -> ResourceQuery:
    params = request.query_params
    try:
        page = max(1, int(params.get("page", "1")))
    except ValueError:
        page = 1
    try:
        per_page = max(1, min(100, int(params.get("per_page", "25"))))
    except ValueError:
        per_page = 25
    raw_count_policy = params.get("count_policy", CountPolicy.EXACT.value)
    try:
        count_policy = CountPolicy(raw_count_policy)
    except ValueError:
        count_policy = CountPolicy.EXACT
    search = params.get("search") if binding.search_fields else None
    return ResourceQuery(
        filters=_parse_filters(binding, params),
        search=search,
        sorting=_parse_sorting(binding, params),
        pagination=OffsetPagination(page=page, per_page=per_page),
        count_policy=count_policy,
    )


def _query_string(request: Request, **changes: object) -> str:
    values = list(request.query_params.multi_items())
    for key, raw_value in changes.items():
        values = [(name, value) for name, value in values if name != key]
        if raw_value is None:
            continue
        if isinstance(raw_value, tuple | list):
            values.extend((key, str(value)) for value in raw_value)
        else:
            values.append((key, str(raw_value)))
    return urlencode(values, doseq=True)


def _sort_headers(binding: ResourceBinding, request: Request, query: ResourceQuery) -> tuple[dict[str, object], ...]:
    active = query.sorting[0] if query.sorting else None
    headers: list[dict[str, object]] = []
    for field_name in binding.fields:
        if field_name not in binding.sort_fields:
            headers.append({"field": field_name, "url": None, "aria_sort": "none"})
            continue
        is_active = active is not None and active.field == field_name
        current_direction = active.direction if is_active else None
        next_value = (
            f"-{field_name}" if current_direction is SortDirection.ASC else field_name
        )
        aria_sort = (
            "ascending"
            if current_direction is SortDirection.ASC
            else "descending"
            if current_direction is SortDirection.DESC
            else "none"
        )
        headers.append(
            {
                "field": field_name,
                "url": f"?{_query_string(request, sort=next_value, page=1)}",
                "aria_sort": aria_sort,
            }
        )
    return tuple(headers)


def _pagination_view(request: Request, page: object) -> dict[str, object]:
    current_page = int(getattr(page, "page", 1))
    return {
        "current_page": current_page,
        "previous_url": (
            f"?{_query_string(request, page=current_page - 1)}"
            if bool(getattr(page, "has_previous", False))
            else None
        ),
        "next_url": (
            f"?{_query_string(request, page=current_page + 1)}"
            if bool(getattr(page, "has_next", False))
            else None
        ),
    }


def _mounted(request: Request, path: str) -> str:
    return _mounted_path(request, path)


def build_resource_routes(binding: ResourceBinding) -> list[Route]:
    async def resource_list(request: Request) -> Response:
        query = _parse_query(binding, request)
        page = await binding.service.list(query)
        rows = []
        for item in page.items:
            identity_values = _identity_values(item, binding.service.identity_fields)
            detail_url = None
            if len(identity_values) == len(binding.service.identity_fields):
                identity = RecordIdentity(values=identity_values)
                detail_url = _mounted(
                    request,
                    f"{binding.resource_path}/{binding.codec.encode(identity)}",
                )
            rows.append(
                {
                    "cells": tuple(_field_value(item, field_name) for field_name in binding.fields),
                    "detail_url": detail_url,
                }
            )
        resource_path = _mounted(request, binding.resource_path)
        count_url = _mounted(request, binding.count_path)
        template = binding.resolve_template("list.html")
        table_template = binding.resolve_template("_table.html")
        return binding.templates.TemplateResponse(
            request,
            template,
            {
                "resource": binding.definition,
                "resource_path": resource_path,
                "count_url": count_url,
                "page": page,
                "query": query,
                "rows": tuple(rows),
                "fields": binding.fields,
                "sort_headers": _sort_headers(binding, request, query),
                "table_template": table_template,
                "search_enabled": bool(binding.search_fields),
                "search_value": query.search or "",
                "filter_values": _query_values(request.query_params, "filter"),
                "sort_value": request.query_params.get("sort", ""),
                "per_page_value": query.pagination.per_page,
                "pagination": _pagination_view(request, page),
            },
            headers={"Cache-Control": "no-store"},
        )

    async def resource_count(request: Request) -> Response:
        query = _parse_query(binding, request).model_copy(update={"count_policy": CountPolicy.EXACT})
        total = await binding.service.count(query)
        return binding.templates.TemplateResponse(
            request,
            binding.resolve_template("_count.html"),
            {"total": total},
            headers={"Cache-Control": "no-store"},
        )

    async def resource_detail(request: Request) -> Response:
        try:
            identity = binding.codec.decode(request.path_params["identity"])
        except ValueError:
            raise RakitError(
                code=ErrorCode.RESOURCE_NOT_FOUND,
                message="Resource record was not found",
                status_code=404,
            ) from None
        item = await binding.service.detail(identity)
        if item is None:
            raise RakitError(
                code=ErrorCode.RESOURCE_NOT_FOUND,
                message="Resource record was not found",
                status_code=404,
            )
        fields = binding.detail_fields or binding.fields
        cells = {field_name: _field_value(item, field_name) for field_name in fields}
        return binding.templates.TemplateResponse(
            request,
            binding.resolve_template("detail.html"),
            {
                "resource": binding.definition,
                "item": item,
                "fields": fields,
                "cells": cells,
            },
            headers={"Cache-Control": "no-store"},
        )

    return [
        Route(binding.resource_path, resource_list, methods=["GET"], name=binding.list_route_name),
        Route(binding.count_path, resource_count, methods=["GET"], name=binding.count_route_name),
        Route(binding.detail_path, resource_detail, methods=["GET"], name=binding.detail_route_name),
    ]
