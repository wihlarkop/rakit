from pathlib import Path

path = Path("packages/rakit-web/src/rakit_web/resource_routes.py")
text = path.read_text()


def replace_once(old: str, new: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected exactly one resource_routes anchor, found {count}: {old[:80]!r}")
    text = text.replace(old, new, 1)


replace_once("from urllib.parse import urlencode\n", "")
replace_once(
    "from rakit_core.identity import IdentityCodec, RecordIdentity\n"
    "from rakit_core.query import (\n"
    "    CountPolicy,\n"
    "    Filter,\n"
    "    FilterOperator,\n"
    "    OffsetPagination,\n"
    "    ResourceQuery,\n"
    "    Sort,\n"
    "    SortDirection,\n"
    ")\n",
    "from rakit_core.filters import ResourceFilter\n"
    "from rakit_core.identity import IdentityCodec, RecordIdentity\n"
    "from rakit_core.pagination import ResourcePaginationPolicy\n"
    "from rakit_core.query import ResourceQuery\n",
)
replace_once(
    "from .icons import render_icon\n\n"
    "_PAGINATION_DEFAULTS = OffsetPagination()\n"
    "_PAGE_SIZE_CHOICES = (25, 50, 100)\n"
    "_FILTER_OPERATOR_LABELS = {\n"
    "    FilterOperator.EQ: \"equals\",\n"
    "    FilterOperator.NEQ: \"does not equal\",\n"
    "    FilterOperator.LT: \"is less than\",\n"
    "    FilterOperator.LTE: \"is less than or equal to\",\n"
    "    FilterOperator.GT: \"is greater than\",\n"
    "    FilterOperator.GTE: \"is greater than or equal to\",\n"
    "    FilterOperator.CONTAINS: \"contains\",\n"
    "    FilterOperator.IN: \"is one of\",\n"
    "    FilterOperator.IS_NULL: \"is empty\",\n"
    "}\n",
    "from .icons import render_icon\n"
    "from .resource_query_ui import (\n"
    "    canonical_builder_query,\n"
    "    explicit_sorting,\n"
    "    filter_groups,\n"
    "    filter_presentations,\n"
    "    hidden_query_inputs,\n"
    "    page_size_options,\n"
    "    page_size_param,\n"
    "    page_size_value,\n"
    "    pagination_controls,\n"
    "    parse_resource_query,\n"
    "    query_without_filters,\n"
    "    query_without_search,\n"
    "    resource_filter_definitions,\n"
    "    resource_url,\n"
    "    sort_headers,\n"
    "    sort_parameter,\n"
    "    validated_query_params,\n"
    ")\n",
)

replace_once(
    "    @property\n"
    "    def filter_fields(self) -> tuple[str, ...]:\n"
    "        return self.definition.field_policy.filter_fields\n\n"
    "    @property\n"
    "    def search_fields(self) -> tuple[str, ...]:\n",
    "    @property\n"
    "    def filter_fields(self) -> tuple[str, ...]:\n"
    "        return self.definition.field_policy.filter_fields\n\n"
    "    @property\n"
    "    def filter_definitions(self) -> tuple[ResourceFilter, ...]:\n"
    "        return resource_filter_definitions(self.definition)\n\n"
    "    @property\n"
    "    def pagination_policy(self) -> ResourcePaginationPolicy:\n"
    "        return self.definition.pagination\n\n"
    "    @property\n"
    "    def search_fields(self) -> tuple[str, ...]:\n",
)

parse_start = text.index("    def parse_query(self, params: QueryParams) -> ResourceQuery:\n")
helper_start = text.index("\ndef _parse_int", parse_start)
new_parse = '''    def parse_query(self, params: QueryParams) -> ResourceQuery:\n        return parse_resource_query(\n            self.definition,\n            self.identity_fields,\n            params,\n        )\n\n'''
text = text[:parse_start] + new_parse + text[helper_start:]

helper_start = text.index("\ndef _parse_int")
route_start = text.index("\ndef build_resource_routes", helper_start)
text = text[:helper_start] + "\n" + text[route_start:]

list_start = text.index("    async def resource_list(request: Request) -> Response:\n")
count_start = text.index("    async def resource_count(request: Request) -> Response:\n", list_start)
new_list = '''    async def resource_list(request: Request) -> Response:\n        query = binding.parse_query(request.query_params)\n        resource_path = _mounted_path(request, binding.definition.path)\n        definitions = binding.filter_definitions\n        explicit = explicit_sorting(request.query_params.get("sort"), binding.sort_fields)\n        builder_query = canonical_builder_query(query, request.query_params, definitions)\n        if builder_query is not None:\n            return RedirectResponse(\n                resource_url(\n                    resource_path,\n                    validated_query_params(builder_query, explicit, definitions),\n                ),\n                status_code=303,\n            )\n\n        page = await binding.service.list(query)\n        fields = binding.fields\n        rows: list[dict[str, object]] = []\n        for item in page.items:\n            identity_values = _identity_values(item, binding.identity_fields)\n            detail_url = ""\n            if identity_values:\n                encoded = binding.codec.encode(RecordIdentity(values=identity_values))\n                detail_url = _mounted_path(\n                    request,\n                    binding.detail_path.replace("{identity}", encoded),\n                )\n            cells = [_field_value(item, field_name) for field_name in fields]\n            rows.append(\n                {\n                    "cells": cells,\n                    "display_cells": [_display_value(value) for value in cells],\n                    "detail_url": detail_url,\n                }\n            )\n\n        table_template = binding.resolve_template("_table.html")\n        logical_name = (\n            table_template if _is_htmx(request) else binding.resolve_template("list.html")\n        )\n        validated_params = validated_query_params(query, explicit, definitions)\n        count_url = _mounted_path(request, binding.count_path)\n        if validated_params:\n            count_url = resource_url(count_url, validated_params)\n        presentations = filter_presentations(query, explicit, resource_path, definitions)\n        pagination = pagination_controls(query, page, resource_path, explicit, definitions)\n        context = {\n            "resource": binding.definition,\n            "page": page,\n            "query": query,\n            "fields": fields,\n            "rows": rows,\n            "resource_path": resource_path,\n            "create_url": (\n                _mounted_path(request, binding.crud_paths.create_path)\n                if binding.crud_paths is not None\n                else ""\n            ),\n            "count_url": count_url,\n            "sort_headers": sort_headers(\n                fields,\n                query,\n                resource_path,\n                explicit,\n                set(binding.sort_fields),\n                definitions,\n            ),\n            "pagination": pagination,\n            "search_value": query.search or "",\n            "search_enabled": bool(binding.search_fields),\n            "search_hidden_inputs": hidden_query_inputs(\n                query, explicit, definitions, omit=frozenset({"search"})\n            ),\n            "clear_search_url": resource_url(\n                resource_path,\n                validated_query_params(\n                    query_without_search(query),\n                    explicit,\n                    definitions,\n                ),\n            ),\n            "filter_enabled": bool(definitions),\n            "filter_groups": filter_groups(query, explicit, resource_path, definitions),\n            "filter_hidden_inputs": hidden_query_inputs(query, explicit, definitions),\n            "filter_presentations": presentations,\n            "active_filter_count": len(presentations),\n            "clear_filters_url": resource_url(\n                resource_path,\n                validated_query_params(\n                    query_without_filters(query),\n                    explicit,\n                    definitions,\n                ),\n            ),\n            "has_active_query": bool(query.search or query.filter_selections),\n            "sort_value": sort_parameter(explicit),\n            "sort_hidden_inputs": hidden_query_inputs(\n                query, explicit, definitions, omit=frozenset({"sort"})\n            ),\n            "page_size_param": page_size_param(query),\n            "page_size_value": page_size_value(query),\n            "page_size_options": page_size_options(query, binding.pagination_policy),\n            "show_page_size_selector": len(binding.pagination_policy.size.allowed) > 1,\n            "page_size_hidden_inputs": hidden_query_inputs(\n                query,\n                explicit,\n                definitions,\n                omit=frozenset({"per_page", "limit"}),\n            ),\n            "table_template": table_template,\n        }\n        return binding.templates.TemplateResponse(\n            request,\n            logical_name,\n            context,\n            headers={"Cache-Control": "no-store"},\n        )\n\n'''
text = text[:list_start] + new_list + text[count_start:]

path.write_text(text)
