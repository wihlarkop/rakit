from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text()
    if text.count(old) != 1:
        raise SystemExit(f"expected exactly one anchor in {path!r}, found {text.count(old)}")
    target.write_text(text.replace(old, new, 1))


# Admin composition: validate explicit filter/pagination declarations, widen only
# the adapter claim policy, and retain the developer's legacy field policy in the
# canonical ResourceDefinition.
replace_once(
    "packages/rakit-web/src/rakit_web/admin.py",
    "from rakit_core.events import EventBus, EventPublisher\nfrom rakit_core.generated_api import ApiExposure\n",
    "from rakit_core.events import EventBus, EventPublisher\n"
    "from rakit_core.filters import ResourceFilter\n"
    "from rakit_core.generated_api import ApiExposure\n"
    "from rakit_core.pagination import ResourcePaginationPolicy\n",
)
replace_once(
    "packages/rakit-web/src/rakit_web/admin.py",
    "        field_policy = _normalize_field_policy(admin_cls)\n"
    "        relationships = resource_relationships(admin_cls)\n",
    "        field_policy = _normalize_field_policy(admin_cls)\n"
    "        raw_filters = getattr(admin_cls, \"filters\", ())\n"
    "        if not isinstance(raw_filters, (list, tuple)) or not all(\n"
    "            isinstance(definition, ResourceFilter) for definition in raw_filters\n"
    "        ):\n"
    "            raise RakitError(\n"
    "                code=ErrorCode.CONFIG_INVALID_RESOURCE_POLICY,\n"
    "                message=\"Invalid resource filter declaration\",\n"
    "                status_code=500,\n"
    "                details={\"resource_id\": admin_cls.resource_id, \"reason\": \"invalid_filters\"},\n"
    "            )\n"
    "        filters = tuple(raw_filters)\n"
    "        pagination = getattr(admin_cls, \"pagination\", ResourcePaginationPolicy())\n"
    "        if not isinstance(pagination, ResourcePaginationPolicy):\n"
    "            raise RakitError(\n"
    "                code=ErrorCode.CONFIG_INVALID_RESOURCE_POLICY,\n"
    "                message=\"Invalid resource pagination declaration\",\n"
    "                status_code=500,\n"
    "                details={\n"
    "                    \"resource_id\": admin_cls.resource_id,\n"
    "                    \"reason\": \"invalid_pagination_policy\",\n"
    "                },\n"
    "            )\n"
    "        predicate_fields = tuple(\n"
    "            field\n"
    "            for definition in filters\n"
    "            for field in definition.predicate_fields\n"
    "        )\n"
    "        effective_filter_fields = tuple(\n"
    "            dict.fromkeys((*field_policy.filter_fields, *predicate_fields))\n"
    "        )\n"
    "        adapter_field_policy = field_policy.model_copy(\n"
    "            update={\"filter_fields\": effective_filter_fields}\n"
    "        )\n"
    "        relationships = resource_relationships(admin_cls)\n",
)
replace_once(
    "packages/rakit-web/src/rakit_web/admin.py",
    "                if (result := claim(admin_cls.model, field_policy)) is not None\n",
    "                if (result := claim(admin_cls.model, adapter_field_policy)) is not None\n",
)
replace_once(
    "packages/rakit-web/src/rakit_web/admin.py",
    "        data_source = adapter_runtime.data_source\n"
    "        definition = ResourceDefinition(\n",
    "        data_source = adapter_runtime.data_source\n"
    "        unknown_predicate_fields = set(predicate_fields).difference(data_source.fields)\n"
    "        if unknown_predicate_fields:\n"
    "            raise RakitError(\n"
    "                code=ErrorCode.CONFIG_INVALID_RESOURCE_POLICY,\n"
    "                message=\"Invalid resource filter declaration\",\n"
    "                status_code=500,\n"
    "                details={\n"
    "                    \"resource_id\": admin_cls.resource_id,\n"
    "                    \"reason\": \"unknown_filter_predicate_field\",\n"
    "                    \"fields\": sorted(unknown_predicate_fields),\n"
    "                },\n"
    "            )\n"
    "        definition = ResourceDefinition(\n",
)
replace_once(
    "packages/rakit-web/src/rakit_web/admin.py",
    "            field_policy=field_policy,\n"
    "            relationships=relationships,\n"
    "            api=admin_cls.api,\n",
    "            field_policy=field_policy,\n"
    "            filters=filters,\n"
    "            pagination=pagination,\n"
    "            relationships=relationships,\n"
    "            api=admin_cls.api,\n",
)

# Core compiler: any composition path, not only rakit-web.Admin, must reject a
# pagination strategy that the selected data source does not advertise.
replace_once(
    "packages/rakit-core/src/rakit_core/compiler.py",
    "        self._resources.append(definition)\n"
    "        self._resource_data_sources[definition.resource_id] = data_source\n",
    "        if (\n"
    "            definition.pagination.strategy\n"
    "            not in data_source.capabilities.pagination_strategies\n"
    "        ):\n"
    "            raise RakitError(\n"
    "                code=ErrorCode.CONFIG_INVALID_RESOURCE_POLICY,\n"
    "                message=f'Resource \"{definition.resource_id}\" requests an unsupported pagination strategy.',\n"
    "                status_code=500,\n"
    "                details={\n"
    "                    \"resource_id\": definition.resource_id,\n"
    "                    \"reason\": \"pagination_strategy_not_supported\",\n"
    "                    \"strategy\": definition.pagination.strategy.value,\n"
    "                },\n"
    "            )\n"
    "        self._resources.append(definition)\n"
    "        self._resource_data_sources[definition.resource_id] = data_source\n",
)

# SQLAlchemy advertises PAGE + true LIMIT_OFFSET and branches explicitly. Cursor
# remains unsupported and fails closed if it reaches the adapter by direct misuse.
replace_once(
    "packages/rakit-sqlalchemy/src/rakit_sqlalchemy/datasource.py",
    "from rakit_core.identity import RecordIdentity\n"
    "from rakit_core.query import (\n"
    "    CountPolicy,\n"
    "    Filter,\n"
    "    FilterOperator,\n"
    "    NullPlacement,\n"
    "    PageResult,\n"
    "    ResourceQuery,\n"
    "    Sort,\n"
    "    SortDirection,\n"
    ")\n",
    "from rakit_core.identity import RecordIdentity\n"
    "from rakit_core.pagination import (\n"
    "    LimitOffsetPagination,\n"
    "    LimitOffsetResult,\n"
    "    PagePagination,\n"
    "    PageResult,\n"
    "    PaginationStrategy,\n"
    "    ResourceListResult,\n"
    ")\n"
    "from rakit_core.query import (\n"
    "    CountPolicy,\n"
    "    Filter,\n"
    "    FilterOperator,\n"
    "    NullPlacement,\n"
    "    ResourceQuery,\n"
    "    Sort,\n"
    "    SortDirection,\n"
    ")\n",
)
replace_once(
    "packages/rakit-sqlalchemy/src/rakit_sqlalchemy/datasource.py",
    "class SQLAlchemyDataSource:\n    capabilities = DataSourceCapabilities(read=True)\n",
    "class SQLAlchemyDataSource:\n"
    "    capabilities = DataSourceCapabilities(\n"
    "        read=True,\n"
    "        pagination_strategies=frozenset(\n"
    "            {PaginationStrategy.PAGE, PaginationStrategy.LIMIT_OFFSET}\n"
    "        ),\n"
    "    )\n",
)
old_list = '''    async def list(self, query: ResourceQuery) -> PageResult:\n        self._validate_query_policy(query)\n        filtered = self._filtered_statement(query)\n        ordered = filtered\n        for sort in self._effective_sorting(query):\n            ordered = self._apply_sort(ordered, sort)\n\n        pagination = query.pagination\n        async with self._session_factory() as session:\n            if query.count_policy is CountPolicy.EXACT:\n                total_count: int | None = await self._count(session, filtered)\n                paginated = ordered.offset(pagination.offset).limit(pagination.per_page)\n                items = tuple((await session.execute(paginated)).scalars().all())\n                has_next = pagination.offset + len(items) < total_count\n            else:\n                # DISABLED and DEFERRED both avoid the count query on this page:\n                # fetch one extra row to learn whether a next page exists, then\n                # trim it back off before building the result. DEFERRED's real\n                # total is fetched separately via the dedicated `_count` route.\n                paginated = ordered.offset(pagination.offset).limit(pagination.per_page + 1)\n                rows = list((await session.execute(paginated)).scalars().all())\n                has_next = len(rows) > pagination.per_page\n                items = tuple(rows[: pagination.per_page])\n                total_count = None\n\n        return PageResult(\n            items=items,\n            page=pagination.page,\n            per_page=pagination.per_page,\n            has_previous=pagination.page > 1,\n            has_next=has_next,\n            total_count=total_count,\n        )\n'''
new_list = '''    async def list(self, query: ResourceQuery) -> ResourceListResult:\n        self._validate_query_policy(query)\n        filtered = self._filtered_statement(query)\n        ordered = filtered\n        for sort in self._effective_sorting(query):\n            ordered = self._apply_sort(ordered, sort)\n\n        pagination = query.pagination\n        if isinstance(pagination, PagePagination):\n            offset = pagination.offset\n            limit = pagination.per_page\n        elif isinstance(pagination, LimitOffsetPagination):\n            offset = pagination.offset\n            limit = pagination.limit\n        else:\n            raise RakitError(\n                code=ErrorCode.CONFIG_INVALID_RESOURCE_POLICY,\n                message=\"SQLAlchemy data source does not support cursor pagination.\",\n                status_code=500,\n                details={\"reason\": \"pagination_strategy_not_supported\"},\n            )\n\n        async with self._session_factory() as session:\n            if query.count_policy is CountPolicy.EXACT:\n                total_count: int | None = await self._count(session, filtered)\n                paginated = ordered.offset(offset).limit(limit)\n                items = tuple((await session.execute(paginated)).scalars().all())\n                has_next = offset + len(items) < total_count\n            else:\n                paginated = ordered.offset(offset).limit(limit + 1)\n                rows = list((await session.execute(paginated)).scalars().all())\n                has_next = len(rows) > limit\n                items = tuple(rows[:limit])\n                total_count = None\n\n        if isinstance(pagination, PagePagination):\n            return PageResult(\n                items=items,\n                page=pagination.page,\n                per_page=pagination.per_page,\n                has_previous=pagination.page > 1,\n                has_next=has_next,\n                total_count=total_count,\n            )\n        return LimitOffsetResult(\n            items=items,\n            offset=pagination.offset,\n            limit=pagination.limit,\n            has_previous=pagination.offset > 0,\n            has_next=has_next,\n            total_count=total_count,\n        )\n'''
replace_once(
    "packages/rakit-sqlalchemy/src/rakit_sqlalchemy/datasource.py",
    old_list,
    new_list,
)
