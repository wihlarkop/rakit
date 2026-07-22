"""Web-side wiring that turns a registered resource into real Starlette routes.

Core keeps `ResourceDefinition`/`RouteDefinition` framework-neutral (no Starlette
callables). This module owns the resource_id -> handler association: it builds a
`ResourceBinding` per resource and the list/detail `Route` objects that render
templates via `ResourceService`, the query parser, and the identity codec.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from jinja2 import ChoiceLoader, FileSystemLoader, PackageLoader, select_autoescape
from jinja2 import Environment as JinjaEnvironment
from rakit_core.definitions import ResourceDefinition
from rakit_core.identity import IdentityCodec, RecordIdentity
from rakit_core.query import OffsetPagination, ResourceQuery
from rakit_core.resources import ResourceService
from starlette.datastructures import QueryParams
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route
from starlette.templating import Jinja2Templates

_PAGINATION_DEFAULTS = OffsetPagination()


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
        try:
            return ResourceQuery.from_params(
                sort=sort,
                page=page,
                per_page=per_page,
                allowed_sort_fields=allowed_sort_fields,
                identity_fields=identity_fields,
            )
        except ValueError:
            # A malformed query string (bad sort field, out-of-range pagination)
            # falls back to a default query for this read-only slice; strict
            # validation-to-HTTP translation is a later task's concern.
            return ResourceQuery.from_params(
                page=_PAGINATION_DEFAULTS.page,
                per_page=_PAGINATION_DEFAULTS.per_page,
                allowed_sort_fields=allowed_sort_fields,
                identity_fields=identity_fields,
            )


def _parse_int(value: str | None, fallback: int) -> int:
    if value is None:
        return fallback
    try:
        return int(value)
    except ValueError:
        return fallback


def build_resource_routes(binding: ResourceBinding) -> list[Route]:
    async def resource_list(request: Request) -> Response:
        query = binding.parse_query(request.query_params)
        page = await binding.service.list(query)
        fields = binding.fields

        rows: list[dict[str, object]] = []
        for item in page.items:
            identity_values = _identity_values(item, binding.identity_fields)
            detail_url = ""
            if identity_values:
                encoded = binding.codec.encode(RecordIdentity(values=identity_values))
                detail_url = str(request.url_for(binding.detail_route_name, identity=encoded))
            rows.append(
                {
                    "cells": [_field_value(item, field_name) for field_name in fields],
                    "detail_url": detail_url,
                }
            )

        logical_name = "_table.html" if _is_htmx(request) else "list.html"
        context = {
            "resource": binding.definition,
            "page": page,
            "query": query,
            "fields": fields,
            "rows": rows,
        }
        return binding.templates.TemplateResponse(
            request,
            binding.resolve_template(logical_name),
            context,
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

    return [
        Route(
            binding.definition.path,
            resource_list,
            name=binding.list_route_name,
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
