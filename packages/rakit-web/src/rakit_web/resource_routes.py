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
from uuid import UUID

from jinja2 import ChoiceLoader, FileSystemLoader, PackageLoader, pass_context, select_autoescape
from jinja2 import Environment as JinjaEnvironment
from jinja2.runtime import Context
from rakit_core.actions import ActionScope
from rakit_core.definitions import ResourceDefinition
from rakit_core.errors import ErrorCode, RakitError
from rakit_core.filters import ResourceFilter
from rakit_core.identity import IdentityCodec, RecordIdentity
from rakit_core.pagination import ResourcePaginationPolicy
from rakit_core.query import ResourceQuery
from rakit_core.resources import ResourceService
from starlette.datastructures import QueryParams
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from ._paths import mounted_path as _mounted_path
from .action_presentation import action_web_presentation
from .action_views import request_action_views
from .assets import static_url
from .icons import render_icon
from .resource_presentation import resource_web_presentation
from .resource_query_ui import (
    canonical_builder_query,
    explicit_sorting,
    filter_groups,
    filter_presentations,
    hidden_query_inputs,
    page_size_options,
    page_size_param,
    page_size_value,
    pagination_controls,
    parse_resource_query,
    query_without_filters,
    query_without_search,
    resource_filter_definitions,
    resource_url,
    sort_headers,
    sort_parameter,
    validated_query_params,
)


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
    globals_["rakit_resource_web_presentation"] = resource_web_presentation
    globals_["rakit_action_web_presentation"] = action_web_presentation
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
class ResourceCrudPaths:
    """Registered built-in CRUD routes available to resource presentation."""

    create_path: str
    update_path: str | None = None
    delete_path: str | None = None


@dataclass(frozen=True)
class ResourceBinding:
    """Everything a request handler needs to serve one resource's pages."""

    definition: ResourceDefinition
    service: ResourceService
    templates: Jinja2Templates
    crud_paths: ResourceCrudPaths | None = None
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
    def filter_definitions(self) -> tuple[ResourceFilter, ...]:
        return resource_filter_definitions(self.definition)

    @property
    def pagination_policy(self) -> ResourcePaginationPolicy:
        return self.definition.pagination

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
        return parse_resource_query(
            self.definition,
            self.identity_fields,
            params,
        )


def build_resource_routes(binding: ResourceBinding) -> list[Route]:
    async def resource_list(request: Request) -> Response:
        query = binding.parse_query(request.query_params)
        resource_path = _mounted_path(request, binding.definition.path)
        definitions = binding.filter_definitions
        explicit = explicit_sorting(request.query_params.get("sort"), binding.sort_fields)
        builder_query = canonical_builder_query(query, request.query_params, definitions)
        if builder_query is not None:
            return RedirectResponse(
                resource_url(
                    resource_path,
                    validated_query_params(builder_query, explicit, definitions),
                ),
                status_code=303,
            )

        page = await binding.service.list(query)
        resource_actions = await request_action_views(
            request,
            owner_id=binding.resource_id,
            scope=ActionScope.RESOURCE,
        )
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
        validated_params = validated_query_params(query, explicit, definitions)
        count_url = _mounted_path(request, binding.count_path)
        if validated_params:
            count_url = resource_url(count_url, validated_params)
        presentations = filter_presentations(query, explicit, resource_path, definitions)
        pagination = pagination_controls(query, page, resource_path, explicit, definitions)
        context = {
            "resource": binding.definition,
            "page": page,
            "query": query,
            "fields": fields,
            "rows": rows,
            "resource_path": resource_path,
            "resource_actions": resource_actions,
            "create_url": (
                _mounted_path(request, binding.crud_paths.create_path)
                if binding.crud_paths is not None
                else ""
            ),
            "count_url": count_url,
            "sort_headers": sort_headers(
                fields,
                query,
                resource_path,
                explicit,
                set(binding.sort_fields),
                definitions,
            ),
            "pagination": pagination,
            "search_value": query.search or "",
            "search_enabled": bool(binding.search_fields),
            "search_hidden_inputs": hidden_query_inputs(
                query, explicit, definitions, omit=frozenset({"search"})
            ),
            "clear_search_url": resource_url(
                resource_path,
                validated_query_params(
                    query_without_search(query),
                    explicit,
                    definitions,
                ),
            ),
            "filter_enabled": bool(definitions),
            "filter_groups": filter_groups(query, explicit, resource_path, definitions),
            "filter_hidden_inputs": hidden_query_inputs(query, explicit, definitions),
            "filter_presentations": presentations,
            "active_filter_count": len(presentations),
            "clear_filters_url": resource_url(
                resource_path,
                validated_query_params(
                    query_without_filters(query),
                    explicit,
                    definitions,
                ),
            ),
            "has_active_query": bool(query.search or query.filter_selections),
            "sort_value": sort_parameter(explicit),
            "sort_hidden_inputs": hidden_query_inputs(
                query, explicit, definitions, omit=frozenset({"sort"})
            ),
            "page_size_param": page_size_param(query),
            "page_size_value": page_size_value(query),
            "page_size_options": page_size_options(query, binding.pagination_policy),
            "show_page_size_selector": len(binding.pagination_policy.size.allowed) > 1,
            "page_size_hidden_inputs": hidden_query_inputs(
                query,
                explicit,
                definitions,
                omit=frozenset({"per_page", "limit"}),
            ),
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
        record_actions = await request_action_views(
            request,
            owner_id=binding.resource_id,
            scope=ActionScope.RECORD,
            identity=identity,
            record=record,
        )
        fields = binding.detail_fields
        cells = {field_name: _field_value(record, field_name) for field_name in fields}
        encoded_identity = binding.codec.encode(identity)
        edit_url = ""
        delete_url = ""
        if binding.crud_paths is not None:
            if binding.crud_paths.update_path:
                edit_url = _mounted_path(
                    request,
                    binding.crud_paths.update_path.replace("{identity}", encoded_identity),
                )
            if binding.crud_paths.delete_path:
                delete_url = _mounted_path(
                    request,
                    binding.crud_paths.delete_path.replace("{identity}", encoded_identity),
                )
        context = {
            "resource": binding.definition,
            "record": record,
            "fields": fields,
            "cells": cells,
            "display_cells": {
                field_name: _display_value(value) for field_name, value in cells.items()
            },
            "record_actions": record_actions,
            "encoded_identity": encoded_identity,
            "edit_url": edit_url,
            "delete_url": delete_url,
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
