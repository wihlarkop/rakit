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

from jinja2 import ChoiceLoader, FileSystemLoader, PackageLoader, pass_context, select_autoescape
from jinja2 import Environment as JinjaEnvironment
from jinja2.runtime import Context
from rakit_core.definitions import ResourceDefinition
from rakit_core.identity import IdentityCodec, RecordIdentity
from rakit_core.query import (
    CountPolicy,
    Filter,
    FilterOperator,
    OffsetPagination,
    ResourceQuery,
)
from rakit_core.resources import ResourceService
from starlette.datastructures import QueryParams
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from .assets import static_url

_PAGINATION_DEFAULTS = OffsetPagination()


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
    cast(dict[str, Any], environment.globals)["static_url"] = _template_static_url
    return Jinja2Templates(env=environment)


def _field_value(item: object, field_name: str) -> object:
    if isinstance(item, dict):
        return item.get(field_name)
    return getattr(item, field_name, None)


def _identity_values(item: object, identity_fields: Sequence[str]) -> dict[str, int | str]:
    values: dict[str, int | str] = {}
    for field_name in identity_fields:
        raw = _field_value(item, field_name)
        if isinstance(raw, int | str):
            values[field_name] = raw
    return values


def _mounted_path(request: Request, path: str) -> str:
    """Prefix a child-app route with the ASGI mount's root path, if present."""

    root_path = request.scope.get("root_path", "").rstrip("/")
    return f"{root_path}{path}"


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
        """Resolve a logical name (e.g. ``list.html``) honouring override precedence.

        Candidate order per `select_template`: resource-specific first, then generic.
        Combined with the loader order (user dirs, then built-in package) this yields:
        resource-specific user -> generic user -> generic built-in, which matches the
        design's precedence (the resource-specific built-in tier is normally empty).
        """
        candidates = [
            f"resources/{self.resource_id}/{logical_name}",
            f"resources/{logical_name}",
        ]
        template = self.templates.env.select_template(candidates)
        return template.name or candidates[-1]

    @property
    def fields(self) -> tuple[str, ...]:
        return self.service.data_source.fields

    @property
    def identity_fields(self) -> tuple[str, ...]:
        return self.service.data_source.identity_fields

    def parse_query(self, params: QueryParams) -> ResourceQuery:
        allowed_sort_fields = set(self.fields)
        identity_fields = self.identity_fields
        page = _parse_int(params.get("page"), _PAGINATION_DEFAULTS.page)
        per_page = _parse_int(params.get("per_page"), _PAGINATION_DEFAULTS.per_page)
        sort = params.get("sort")
        search = params.get("search")
        filters = _parse_filters(params, allowed_sort_fields)
        count_policy = _parse_count_policy(params.get("count_policy"))
        try:
            return ResourceQuery.from_params(
                sort=sort,
                page=page,
                per_page=per_page,
                allowed_sort_fields=allowed_sort_fields,
                identity_fields=identity_fields,
                filters=filters,
                search=search,
                count_policy=count_policy,
            )
        except ValueError:
            # A malformed query string (bad sort field, out-of-range pagination)
            # falls back to a default query for this read-only slice; strict
            # validation-to-HTTP translation is a later task's concern. Filters,
            # search and count policy are already individually sanitised above,
            # so they are safe to carry into the fallback.
            return ResourceQuery.from_params(
                page=_PAGINATION_DEFAULTS.page,
                per_page=_PAGINATION_DEFAULTS.per_page,
                allowed_sort_fields=allowed_sort_fields,
                identity_fields=identity_fields,
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
        # Unknown policy in the URL falls back to the safe default rather than
        # erroring -- consistent with page/per_page/sort's lenient parsing.
        return CountPolicy.EXACT


def _parse_filters(params: QueryParams, allowed_fields: set[str]) -> tuple[Filter, ...]:
    """Parse repeatable ``filter=<field>:<operator>:<value>`` query params.

    Bookmarkable URL contract for 0.1: each filter is a single ``filter`` param
    whose value is three colon-delimited parts -- the field name, the operator
    token (one of ``FilterOperator``'s values), and the raw value (which may
    itself contain colons; only the first two colons are treated as delimiters).
    The param is repeatable and every filter is AND-combined downstream.

    Special value handling:
    - ``in``: the value is split on commas into a list.
    - ``is_null``: the value is interpreted as a boolean (``true``/``1``/``yes``).

    Any filter naming a field outside the whitelist, or using an unknown
    operator, is silently dropped -- same lenient philosophy as sort parsing.
    """
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
        value: object
        if operator is FilterOperator.IN:
            value = [part for part in raw_value.split(",") if part]
        elif operator is FilterOperator.IS_NULL:
            value = raw_value.strip().lower() in {"true", "1", "yes"}
        else:
            value = raw_value
        filters.append(Filter(field=field_name, operator=operator, value=value))
    return tuple(filters)


def _sort_headers(fields: Sequence[str], query: ResourceQuery, path: str) -> list[dict[str, str]]:
    """Build per-column sort-toggle links for the table header.

    Each link deliberately omits any ``page`` param: changing the sort resets to
    the first page (a stale page number may not exist in the re-sorted result
    set). The current free-text search and count policy are preserved so sorting
    does not silently discard them.
    """
    primary = query.sorting[0] if query.sorting else None
    headers: list[dict[str, str]] = []
    for field_name in fields:
        is_primary_asc = (
            primary is not None and primary.field == field_name and primary.direction.value == "asc"
        )
        # Toggle: an already-ascending primary column flips to descending.
        next_sort = f"-{field_name}" if is_primary_asc else field_name
        params: list[tuple[str, str]] = [("sort", next_sort)]
        if query.search:
            params.append(("search", query.search))
        if query.count_policy.value != "exact":
            params.append(("count_policy", query.count_policy.value))
        current = ""
        if primary is not None and primary.field == field_name:
            current = primary.direction.value
        headers.append(
            {
                "field": field_name,
                "url": f"{path}?{urlencode(params)}",
                "direction": current,
            }
        )
    return headers


def build_resource_routes(binding: ResourceBinding) -> list[Route]:
    async def resource_list(request: Request) -> Response:
        query = binding.parse_query(request.query_params)
        page = await binding.service.list(query)
        fields = binding.fields
        resource_path = _mounted_path(request, binding.definition.path)

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
            rows.append(
                {
                    "cells": [_field_value(item, field_name) for field_name in fields],
                    "detail_url": detail_url,
                }
            )

        count_url = _mounted_path(request, binding.count_path)
        if request.url.query:
            # Carry the current filters/search into the deferred-count fetch so
            # the total matches the list it annotates, not the whole table.
            count_url = f"{count_url}?{request.url.query}"

        logical_name = "_table.html" if _is_htmx(request) else "list.html"
        context = {
            "resource": binding.definition,
            "page": page,
            "query": query,
            "fields": fields,
            "rows": rows,
            "resource_path": resource_path,
            "count_url": count_url,
            "sort_headers": _sort_headers(fields, query, resource_path),
            "search_value": query.search or "",
        }
        return binding.templates.TemplateResponse(
            request,
            binding.resolve_template(logical_name),
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
        identity = binding.codec.decode(request.path_params["identity"])
        record = await binding.service.detail(identity)
        fields = binding.fields
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

    # `_count` is registered before the detail route so a request for
    # `{path}/_count` matches the count handler rather than being captured by
    # the detail route's `{identity}` path parameter.
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
