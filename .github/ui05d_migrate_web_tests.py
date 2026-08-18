from pathlib import Path


def replace(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text()
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"missing Web migration anchor in {path}: {old[:140]!r}")
    target.write_text(text.replace(old, new, 1))


# Bulk-list fake remains intentionally page-number only.
bulk = "packages/rakit-web/tests/test_bulk_list_ui.py"
replace(
    bulk,
    "from rakit_core.query import PageResult, ResourceQuery\n",
    "from rakit_core.query import PagePagination, PageResult, ResourceQuery\n",
)
replace(
    bulk,
    "    async def list(self, query: ResourceQuery) -> PageResult[dict[str, object]]:\n"
    "        return PageResult(\n"
    '            items=({"id": 1, "name": "One"}, {"id": 2, "name": "Two"}),\n'
    "            page=query.pagination.page,\n"
    "            per_page=query.pagination.per_page,\n",
    "    async def list(self, query: ResourceQuery) -> PageResult[dict[str, object]]:\n"
    "        pagination = query.pagination\n"
    "        if not isinstance(pagination, PagePagination):\n"
    '            raise ValueError("_DataSource supports page-number pagination only")\n'
    "        return PageResult(\n"
    '            items=({"id": 1, "name": "One"}, {"id": 2, "name": "Two"}),\n'
    "            page=pagination.page,\n"
    "            per_page=pagination.per_page,\n",
)

# Generated REST fixture uses the normalized compiled filter contract.
generated = "packages/rakit-web/tests/test_generated_rest_contracts.py"
replace(
    generated,
    "    ApiFilterDefinition,\n    CompiledResourceApi,\n",
    "    ApiFilterDefinition,\n    CompiledApiFilterDefinition,\n    CompiledResourceApi,\n",
)
replace(
    generated,
    "from rakit_core.generated_api import (\n",
    "from rakit_core.filters import LegacyFieldFilter\nfrom rakit_core.generated_api import (\n",
)
replace(
    generated,
    "from rakit_core.query import FilterOperator, SortDirection\n",
    "from rakit_core.query import FilterOperator, PagePagination, SortDirection\n",
)
replace(
    generated,
    "    return CompiledResourceApi(\n"
    '        resource_id="users",\n'
    "        definition=definition,\n"
    "        operations=definition.operations,\n"
    "        read_fields=definition.read_fields,\n"
    "        create_fields=definition.create_fields,\n"
    "        update_fields=definition.update_fields,\n"
    '        identity_fields=("id",),\n'
    "        filters=definition.filters,\n"
    "    )\n",
    "    filter_definition = LegacyFieldFilter(\n"
    '        filter_id="status",\n'
    '        label="Status",\n'
    '        field="status",\n'
    "        operators=(FilterOperator.EQ, FilterOperator.IN),\n"
    "        strip_in_values=True,\n"
    "    )\n"
    "    return CompiledResourceApi(\n"
    '        resource_id="users",\n'
    "        definition=definition,\n"
    "        operations=definition.operations,\n"
    "        read_fields=definition.read_fields,\n"
    "        create_fields=definition.create_fields,\n"
    "        update_fields=definition.update_fields,\n"
    '        identity_fields=("id",),\n'
    "        filters=(\n"
    "            CompiledApiFilterDefinition(\n"
    '                name="status",\n'
    "                filter=filter_definition,\n"
    "                operators=filter_definition.operators,\n"
    "            ),\n"
    "        ),\n"
    "    )\n",
)
replace(
    generated,
    "    )\n\n    assert query.pagination.page == 2\n",
    "    )\n\n    assert isinstance(query.pagination, PagePagination)\n    assert query.pagination.page == 2\n",
)

# Query UI tests target semantic serialization rather than removed private helpers.
query_ui = "packages/rakit-web/tests/test_query_ui.py"
replace(
    query_ui,
    "from rakit_core.errors import RakitError\nfrom rakit_core.query import Filter, FilterOperator\n",
    "from rakit_core.filters import FilterSelection, LegacyFieldFilter\n"
    "from rakit_core.query import FilterOperator\n",
)
replace(
    query_ui,
    "from rakit_web.resource_routes import _serialize_filter\n",
    "from rakit_web.resource_query_ui import serialize_selection\n",
)
replace(
    query_ui,
    "def test_query_control_serialization_rejects_unsafe_filter_shapes() -> None:\n"
    "    filter_ = Filter(\n"
    '        field="name",\n'
    "        operator=FilterOperator.EQ,\n"
    '        value={"unexpected": "mapping"},\n'
    "    )\n\n"
    "    with pytest.raises(RakitError) as exc_info:\n"
    "        _serialize_filter(filter_)\n\n"
    "    assert exc_info.value.to_public_dict() == {\n"
    '        "code": "validation.failed",\n'
    '        "message": "Cannot safely render query controls",\n'
    "    }\n",
    "def test_query_control_serialization_rejects_unsafe_semantic_values() -> None:\n"
    "    definition = LegacyFieldFilter(\n"
    '        filter_id="name",\n'
    '        label="Name",\n'
    '        field="name",\n'
    "    )\n"
    "    selection = FilterSelection(\n"
    '        filter_id="name",\n'
    "        operator=FilterOperator.EQ,\n"
    '        value={"unexpected": "mapping"},\n'
    "    )\n\n"
    "    with pytest.raises(ValueError):\n"
    "        serialize_selection(selection, definition)\n",
)

# Relationship candidate source is page-only.
relationship = "packages/rakit-web/tests/test_relationship_ui.py"
replace(
    relationship,
    "from rakit_core.query import PageResult, ResourceQuery\n",
    "from rakit_core.query import PagePagination, PageResult, ResourceQuery\n",
)
replace(
    relationship,
    "        start = query.pagination.offset\n"
    "        items = records[start : start + query.pagination.per_page]\n"
    "        return PageResult(\n"
    "            items=items,\n"
    "            page=query.pagination.page,\n"
    "            per_page=query.pagination.per_page,\n"
    "            has_previous=query.pagination.page > 1,\n",
    "        pagination = query.pagination\n"
    "        if not isinstance(pagination, PagePagination):\n"
    '            raise ValueError("CandidateSource supports page-number pagination only")\n'
    "        start = pagination.offset\n"
    "        items = records[start : start + pagination.per_page]\n"
    "        return PageResult(\n"
    "            items=items,\n"
    "            page=pagination.page,\n"
    "            per_page=pagination.per_page,\n"
    "            has_previous=pagination.page > 1,\n",
)

# Resource detail fixture is page-only.
detail = "packages/rakit-web/tests/test_resource_detail_form_ui_maturity.py"
replace(
    detail,
    "from rakit_core.query import PageResult, ResourceQuery\n",
    "from rakit_core.query import PagePagination, PageResult, ResourceQuery\n",
)
replace(
    detail,
    "    async def list(self, query: ResourceQuery) -> PageResult[dict[str, object]]:\n"
    "        return PageResult(\n"
    "            items=(self.record,),\n"
    "            page=query.pagination.page,\n"
    "            per_page=query.pagination.per_page,\n",
    "    async def list(self, query: ResourceQuery) -> PageResult[dict[str, object]]:\n"
    "        pagination = query.pagination\n"
    "        if not isinstance(pagination, PagePagination):\n"
    '            raise ValueError("_ResourceDataSource supports page-number pagination only")\n'
    "        return PageResult(\n"
    "            items=(self.record,),\n"
    "            page=pagination.page,\n"
    "            per_page=pagination.per_page,\n",
)

# Resource list fixture and compatibility-builder tests use the semantic query layer.
resource_list = "packages/rakit-web/tests/test_resource_list_ui_maturity.py"
replace(
    resource_list,
    "from rakit_core.errors import RakitError\nfrom rakit_core.identity import RecordIdentity\n"
    "from rakit_core.query import CountPolicy, PageResult, ResourceQuery\n",
    "from rakit_core.filters import LegacyFieldFilter\n"
    "from rakit_core.identity import RecordIdentity\n"
    "from rakit_core.query import CountPolicy, PagePagination, PageResult, ResourceQuery\n",
)
replace(
    resource_list,
    "from rakit_web.resource_routes import (\n"
    "    ResourceBinding,\n"
    "    _builder_filter,\n"
    "    build_resource_routes,\n"
    "    build_templates,\n"
    ")\n",
    "from rakit_web.resource_query_ui import builder_selections\n"
    "from rakit_web.resource_routes import (\n"
    "    ResourceBinding,\n"
    "    build_resource_routes,\n"
    "    build_templates,\n"
    ")\n",
)
replace(
    resource_list,
    "        start = query.pagination.offset\n"
    "        end = start + query.pagination.per_page\n"
    "        page_items = tuple(items[start:end])\n"
    "        return PageResult(\n"
    "            items=page_items,\n"
    "            page=query.pagination.page,\n"
    "            per_page=query.pagination.per_page,\n"
    "            has_previous=query.pagination.page > 1,\n",
    "        pagination = query.pagination\n"
    "        if not isinstance(pagination, PagePagination):\n"
    '            raise ValueError("_DataSource supports page-number pagination only")\n'
    "        start = pagination.offset\n"
    "        end = start + pagination.per_page\n"
    "        page_items = tuple(items[start:end])\n"
    "        return PageResult(\n"
    "            items=page_items,\n"
    "            page=pagination.page,\n"
    "            per_page=pagination.per_page,\n"
    "            has_previous=pagination.page > 1,\n",
)
replace(
    resource_list,
    "def test_filter_builder_rejects_unapproved_or_malformed_state() -> None:\n"
    "    assert (\n"
    "        _builder_filter(\n"
    '            QueryParams("filter_field=secret&filter_operator=eq&filter_value=value"),\n'
    '            {"status"},\n'
    "        )\n"
    "        is None\n"
    "    )\n"
    "    assert (\n"
    "        _builder_filter(\n"
    '            QueryParams("filter_field=status&filter_operator=eq"),\n'
    '            {"status"},\n'
    "        )\n"
    "        is None\n"
    "    )\n"
    "    with pytest.raises(RakitError):\n"
    "        _builder_filter(\n"
    '            QueryParams("filter_field=status&filter_operator=is_null&filter_value=maybe"),\n'
    '            {"status"},\n'
    "        )\n",
    "def test_filter_builder_rejects_unapproved_or_malformed_state() -> None:\n"
    "    definitions = (\n"
    "        LegacyFieldFilter(\n"
    '            filter_id="status",\n'
    '            label="Status",\n'
    '            field="status",\n'
    "        ),\n"
    "    )\n"
    "    assert (\n"
    "        builder_selections(\n"
    '            QueryParams("filter_field=secret&filter_operator=eq&filter_value=value"),\n'
    "            definitions,\n"
    "        )\n"
    "        == ()\n"
    "    )\n"
    "    assert (\n"
    "        builder_selections(\n"
    '            QueryParams("filter_field=status&filter_operator=eq"),\n'
    "            definitions,\n"
    "        )\n"
    "        == ()\n"
    "    )\n"
    "    assert (\n"
    "        builder_selections(\n"
    '            QueryParams("filter_field=status&filter_operator=is_null&filter_value=maybe"),\n'
    "            definitions,\n"
    "        )\n"
    "        == ()\n"
    "    )\n",
)
replace(
    resource_list,
    "async def test_exact_count_pagination_renders_range_numbered_pages_and_custom_size() -> None:\n",
    "async def test_exact_count_pagination_renders_range_numbered_pages_and_policy_size() -> None:\n",
)
replace(
    resource_list,
    "    assert custom.status_code == 200\n"
    '    assert \'<option value="17" selected>17 (custom)</option>\' in custom.text\n'
    "    for size in (25, 50, 100):\n"
    '        assert f\'<option value="{size}">{size}</option>\' in custom.text\n',
    "    assert custom.status_code == 200\n"
    '    assert \'<option value="17"\' not in custom.text\n'
    '    assert \'<option value="25" selected>25</option>\' in custom.text\n'
    "    for size in (50, 100):\n"
    '        assert f\'<option value="{size}">{size}</option>\' in custom.text\n',
)

# Release-level security fake remains page-only.
security = "tests/integration/test_security_regressions.py"
replace(
    security,
    "from rakit_core.query import PageResult, ResourceQuery\n",
    "from rakit_core.query import PagePagination, PageResult, ResourceQuery\n",
)
replace(
    security,
    "    async def list(self, query: ResourceQuery) -> PageResult[_Record]:\n"
    "        return PageResult(\n"
    "            items=(_Record(),),\n"
    "            page=query.pagination.page,\n"
    "            per_page=query.pagination.per_page,\n",
    "    async def list(self, query: ResourceQuery) -> PageResult[_Record]:\n"
    "        pagination = query.pagination\n"
    "        if not isinstance(pagination, PagePagination):\n"
    '            raise ValueError("_Source supports page-number pagination only")\n'
    "        return PageResult(\n"
    "            items=(_Record(),),\n"
    "            page=pagination.page,\n"
    "            per_page=pagination.per_page,\n",
)
