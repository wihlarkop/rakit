from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected exactly one anchor in {path!r}, found {count}: {old[:100]!r}")
    target.write_text(text.replace(old, new, 1))


def replace_count(path: str, old: str, new: str, expected: int) -> None:
    target = Path(path)
    text = target.read_text()
    count = text.count(old)
    if count != expected:
        raise SystemExit(
            f"expected exactly {expected} anchors in {path!r}, found {count}: {old[:100]!r}"
        )
    target.write_text(text.replace(old, new))


# Backward compatibility: datasource capability objects created before UI-05D
# implicitly support the historical PAGE strategy.
compiler = "packages/rakit-core/src/rakit_core/compiler.py"
replace_once(
    compiler,
    "from .generated_runtime import GeneratedResourceExecutorProvider, ResourceAdapterRuntime\n"
    "from .permissions import PermissionRequirement\n",
    "from .generated_runtime import GeneratedResourceExecutorProvider, ResourceAdapterRuntime\n"
    "from .pagination import PaginationStrategy\n"
    "from .permissions import PermissionRequirement\n",
)
replace_once(
    compiler,
    "        if definition.pagination.strategy not in data_source.capabilities.pagination_strategies:\n",
    "        pagination_strategies = getattr(\n"
    "            data_source.capabilities,\n"
    "            \"pagination_strategies\",\n"
    "            frozenset({PaginationStrategy.PAGE}),\n"
    "        )\n"
    "        if definition.pagination.strategy not in pagination_strategies:\n",
)

# Dataclass defaults use a factory so the compiled contract stays conventional
# and type-checker friendly.
generated_api = "packages/rakit-core/src/rakit_core/generated_api.py"
replace_once(generated_api, "from dataclasses import dataclass\n", "from dataclasses import dataclass, field\n")
replace_once(
    generated_api,
    "    pagination: ResourcePaginationPolicy = ResourcePaginationPolicy()\n",
    "    pagination: ResourcePaginationPolicy = field(default_factory=ResourcePaginationPolicy)\n",
)

# Built-in field filters derive predicate_fields from field at validation time.
# Give the static constructor a default as well, and make tuple serialization
# explicitly typed after the runtime all(str) guard.
filters = "packages/rakit-core/src/rakit_core/filters.py"
replace_once(filters, "from typing import Any\n", "from typing import Any, cast\n")
replace_once(
    filters,
    '            return ",".join(value)\n',
    '            return ",".join(cast(tuple[str, ...], value))\n',
)
replace_once(
    filters,
    "class _FieldResourceFilter(ResourceFilter):\n    field: str\n",
    "class _FieldResourceFilter(ResourceFilter):\n    predicate_fields: tuple[str, ...] = ()\n    field: str\n",
)

# The reusable datasource contract historically exercises page-number results.
# UI-05D broadens DataSource.list() to a strategy union, so narrow explicitly in
# the page-specific contract assertions instead of assuming every result shape.
contract = "packages/rakit-core/src/rakit_core/testing/datasource_contract.py"
replace_once(
    contract,
    "    OffsetPagination,\n    ResourceQuery,\n",
    "    OffsetPagination,\n    PageResult,\n    ResourceQuery,\n",
)
replace_count(
    contract,
    "                    count_policy=CountPolicy.DISABLED,\n"
    "                )\n"
    "            )\n"
    "            seen.extend(\n",
    "                    count_policy=CountPolicy.DISABLED,\n"
    "                )\n"
    "            )\n"
    "            assert isinstance(page, PageResult)\n"
    "            seen.extend(\n",
    2,
)
replace_once(
    contract,
    "        exact = await ds.list(ResourceQuery(count_policy=CountPolicy.EXACT))\n"
    "        assert exact.total_count == total, \"EXACT count must report the full filtered total\"\n",
    "        exact = await ds.list(ResourceQuery(count_policy=CountPolicy.EXACT))\n"
    "        assert isinstance(exact, PageResult)\n"
    "        assert exact.total_count == total, \"EXACT count must report the full filtered total\"\n",
)
replace_once(
    contract,
    "        deferred = await ds.list(ResourceQuery(count_policy=CountPolicy.DEFERRED))\n"
    "        assert deferred.total_count is None, \"DEFERRED count must not run a total count\"\n",
    "        deferred = await ds.list(ResourceQuery(count_policy=CountPolicy.DEFERRED))\n"
    "        assert isinstance(deferred, PageResult)\n"
    "        assert deferred.total_count is None, \"DEFERRED count must not run a total count\"\n",
)
replace_once(
    contract,
    "        disabled = await ds.list(ResourceQuery(count_policy=CountPolicy.DISABLED))\n"
    "        assert disabled.total_count is None, \"DISABLED count must not run a total count\"\n",
    "        disabled = await ds.list(ResourceQuery(count_policy=CountPolicy.DISABLED))\n"
    "        assert isinstance(disabled, PageResult)\n"
    "        assert disabled.total_count is None, \"DISABLED count must not run a total count\"\n",
)

showcase = "examples/ui_showcase/main.py"
replace_once(
    showcase,
    "    Admin,\n"
    "    DashboardDefinition,\n"
    "    LauncherItem,\n",
    "    Admin,\n"
    "    ChoiceFilter,\n"
    "    DashboardDefinition,\n"
    "    DataSourceCapabilities,\n"
    "    DateRangeFilter,\n"
    "    Filter,\n"
    "    FilterChoice,\n"
    "    FilterControl,\n"
    "    FilterOperator,\n"
    "    LauncherItem,\n",
)
replace_once(
    showcase,
    "    PageDefinition,\n"
    "    PageResult,\n"
    "    RelationshipCardinality,\n",
    "    PageDefinition,\n"
    "    PageResult,\n"
    "    PageSizePolicy,\n"
    "    RelationshipCardinality,\n",
)
replace_once(
    showcase,
    "    ResourceAdmin,\n"
    "    SecretValue,\n",
    "    ResourceAdmin,\n"
    "    ResourceFilter,\n"
    "    ResourcePaginationPolicy,\n"
    "    SecretValue,\n",
)
replace_once(
    showcase,
    "    TableWidgetResult,\n"
    "    WidgetDefinition,\n",
    "    TableWidgetResult,\n"
    "    TextFilter,\n"
    "    WidgetDefinition,\n",
)
replace_once(
    showcase,
    'class _MemoryDataSource:\n    capabilities = type("Capabilities", (), {"read": True})()\n',
    "class _MemoryDataSource:\n    capabilities = DataSourceCapabilities(read=True)\n",
)

stock_filter = '''\n\nclass StockLevelFilter(ResourceFilter):\n    \"\"\"Semantic showcase filter resolved without datasource-specific query objects.\"\"\"\n\n    def parse_value(self, *, operator: FilterOperator, raw_value: object) -> object:\n        if operator is not FilterOperator.EQ or not isinstance(raw_value, str):\n            raise ValueError(\"Stock-level filter accepts one named choice\")\n        if raw_value not in {choice.value for choice in self.choices}:\n            raise ValueError(\"Stock-level filter choice is not allowed\")\n        return raw_value\n\n    def resolve_predicates(\n        self,\n        *,\n        operator: FilterOperator,\n        value: object,\n    ) -> tuple[Filter, ...]:\n        if operator is not FilterOperator.EQ or not isinstance(value, str):\n            raise ValueError(\"Stock-level filter selection is invalid\")\n        if value == \"attention\":\n            return (\n                Filter(\n                    field=\"status\",\n                    operator=FilterOperator.IN,\n                    value=(\"Low stock\", \"Out of stock\"),\n                ),\n            )\n        if value == \"out\":\n            return (\n                Filter(\n                    field=\"status\",\n                    operator=FilterOperator.EQ,\n                    value=\"Out of stock\",\n                ),\n            )\n        raise ValueError(\"Stock-level filter choice is not allowed\")\n'''
replace_once(showcase, "\n\nclass RefundOrder:\n", stock_filter + "\n\nclass RefundOrder:\n")

old_orders = '''    filter_fields = ("customer", "status")\n    search_fields = ("id", "customer")\n    sort_fields = ("id", "customer", "status", "created")\n'''
new_orders = '''    filters = (\n        TextFilter(\n            filter_id="customer",\n            label="Customer",\n            field="customer",\n            operators=(FilterOperator.CONTAINS, FilterOperator.EQ),\n        ),\n        ChoiceFilter(\n            filter_id="status",\n            label="Status",\n            field="status",\n            choices=(\n                FilterChoice(value="Paid", label="Paid"),\n                FilterChoice(value="Pending review", label="Pending review"),\n                FilterChoice(value="Processing", label="Processing"),\n                FilterChoice(value="Fulfilled", label="Fulfilled"),\n                FilterChoice(value="Refunded", label="Refunded"),\n                FilterChoice(value="Cancelled", label="Cancelled"),\n            ),\n        ),\n        DateRangeFilter(\n            filter_id="created",\n            label="Created",\n            field="created",\n        ),\n    )\n    filter_fields = ()\n    search_fields = ("id", "customer")\n    sort_fields = ("id", "customer", "status", "created")\n    pagination = ResourcePaginationPolicy(\n        size=PageSizePolicy(default=20, allowed=(20, 40, 80))\n    )\n'''
replace_once(showcase, old_orders, new_orders)

old_inventory = '''    filter_fields = ("status",)\n    search_fields = ("id", "sku", "product")\n    sort_fields = ("id", "sku", "product", "on_hand", "status")\n'''
new_inventory = '''    filters = (\n        StockLevelFilter(\n            filter_id="stock_level",\n            label="Stock level",\n            predicate_fields=("status",),\n            control=FilterControl.CHOICE,\n            operators=(FilterOperator.EQ,),\n            choices=(\n                FilterChoice(value="attention", label="Needs attention"),\n                FilterChoice(value="out", label="Out of stock"),\n            ),\n        ),\n    )\n    filter_fields = ()\n    search_fields = ("id", "sku", "product")\n    sort_fields = ("id", "sku", "product", "on_hand", "status")\n'''
replace_once(showcase, old_inventory, new_inventory)
