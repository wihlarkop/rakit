# UI-05D Resource Query Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one backend-neutral resource-query configuration layer that powers Django-admin-style Web filters, generated REST filter exposure, visible sort affordances, resource-controlled page-size policy, and explicit pagination strategy contracts without breaking existing Rakit resources.

**Architecture:** Add first-class filter and pagination configuration types to `rakit-core`, normalize legacy `filter_fields` and `ApiFilterDefinition` declarations into that shared contract, then make Web and generated REST resolve semantic filter selections into ordinary backend-neutral `Filter` predicates. Preserve page-number behavior as the default, add explicit page/limit-offset/cursor request/result types plus data-source capability declarations, and only render navigation that the active pagination strategy can truthfully support.

**Tech Stack:** Python 3.12+, Pydantic v2, Starlette/Jinja/HTMX progressive enhancement, Tailwind CSS v4, SQLAlchemy async adapter, uv workspace, Ruff, ty, pytest.

**Spec:** `docs/superpowers/specs/2026-08-18-ui-05d-resource-query-configuration-design.md`

## Global Constraints

- Keep `ui-05-resource-experience -> main` PR #21 draft until UI-05D is merged into the integration branch and visually accepted.
- Work on `ui-05d-resource-query-configuration`, based on `ui-05-resource-experience`.
- Existing `ResourceFieldPolicy(filter_fields=...)` declarations remain valid.
- Existing direct `ApiFilterDefinition(...)` declarations remain valid.
- Generated REST filter exposure remains explicit and fail closed; an Admin Web filter is never automatically exposed externally.
- Existing generated REST URLs such as `?filter[status]=paid` and `?filter[total][gte]=100` remain valid.
- Existing Web legacy URLs such as `?filter=status:eq:paid` remain valid.
- Custom filters resolve only to zero or more ordinary `Filter` predicates; no OR/NOT/expression-tree DSL in UI-05D.
- Custom filters must declare every backend predicate field they may emit so adapters can validate/filter safely before runtime.
- Default page size remains 25 and default selectable sizes remain `(25, 50, 100)`.
- `PagePagination` becomes the canonical page-number request type; the existing `OffsetPagination` public name remains a compatibility alias for page-number pagination.
- True limit/offset uses `LimitOffsetPagination`; opaque cursor navigation uses `CursorPagination`.
- Data sources declare supported pagination strategies; unsupported configured strategies fail closed rather than being emulated.
- SQLAlchemy supports page-number and true limit/offset in this phase; cursor support is not faked.
- SSR/normal GET remains authoritative; HTMX is enhancement only.
- No UI-06 action/relationship/auth/custom-page work, database namespace work, release/tag/PyPI work, or unrelated refactor.
- Per the established UI-05 execution workflow requested by the user, implementation is feature-first; focused regression tests are added after the feature surface is complete, followed by full verification.

---

## File Structure

### New focused core modules

- `packages/rakit-core/src/rakit_core/filters.py`
  - Public filter-definition, filter-choice, semantic filter-selection, resolution, legacy-normalization helpers, and built-in filter types.
- `packages/rakit-core/src/rakit_core/pagination.py`
  - `PaginationStrategy`, `PageSizePolicy`, `ResourcePaginationPolicy`, page/limit-offset/cursor request types, and strategy-specific result metadata/result types.

### Core files modified

- `packages/rakit-core/src/rakit_core/query.py`
  - Keep `Filter`, `Sort`, `ResourceQuery`, compatibility imports/aliases, and accept the new pagination request union plus semantic `FilterSelection` provenance.
- `packages/rakit-core/src/rakit_core/definitions.py`
  - Add `ResourceDefinition.filters` and `ResourceDefinition.pagination`.
- `packages/rakit-core/src/rakit_core/admin_types.py`
  - Add `ResourceAdmin.filters` and `ResourceAdmin.pagination`.
- `packages/rakit-core/src/rakit_core/datasource.py`
  - Add pagination-strategy capabilities and return-type union.
- `packages/rakit-core/src/rakit_core/generated_api.py`
  - Allow API filters to reference resource filter IDs while preserving direct `ApiFilterDefinition`; add compiled normalized API-filter type and pagination policy.
- `packages/rakit-core/src/rakit_core/generated_compiler.py`
  - Normalize/filter explicit API exposure against resource filter definitions; reject unknown IDs/operators.
- `packages/rakit-core/src/rakit_core/generated_query.py`
  - Resolve generated REST selections through the shared resource filter contract.
- `packages/rakit-core/src/rakit_core/resources.py`
  - Widen list result typing to the strategy-specific result union.
- `packages/rakit-core/src/rakit_core/compiler.py`
  - Fail closed when a resource requests a pagination strategy its data source does not support.

### Public facade/composition files modified

- `packages/rakit-web/src/rakit_web/admin.py`
  - Normalize Admin declarations, pass effective predicate fields to adapter claims, store reusable resource filters/pagination policy.
- `packages/rakit/src/rakit/__init__.py`
  - Export developer-facing filter/pagination configuration types.

### Generated REST files modified

- `packages/rakit-web/src/rakit_web/generated_rest.py`
  - Preserve query syntax while delegating filter value semantics to the compiled shared definition; parse strategy-specific pagination parameters.
- `packages/rakit-web/src/rakit_web/generated_rest_runtime.py`
  - Serialize page/limit-offset/cursor result metadata truthfully.

### Admin Web files modified

- `packages/rakit-web/src/rakit_web/resource_routes.py`
  - Parse registered filters into semantic selections + flattened predicates, canonicalize legacy/new controls, build presentation groups/chips, apply resource page-size policy, and produce strategy-aware pagination context.
- `packages/rakit-web/src/rakit_web/templates/resources/list.html`
  - Replace the generic filter builder as the primary UX with definition-driven Django-admin-style filter groups; keep legacy builder only for synthesized legacy filters.
- `packages/rakit-web/src/rakit_web/templates/resources/_table.html`
  - Add inactive sortable/ascending/descending affordances while preserving accessible sort semantics.
- `packages/rakit-web/src/rakit_web/templates/resources/_count.html`
  - Preserve count-fragment compatibility while strategy-aware list UI decides whether totals/page numbers are meaningful.
- `packages/rakit-web/src/rakit_web/icons.py`
  - Add only the small Lucide sort affordance needed by sortable inactive headers if it is not already vendored.
- `packages/rakit-web/src/rakit_web/assets/rakit.css`
  - Only reusable query-filter/sort presentation rules if existing primitives/utilities are insufficient.
- `packages/rakit-web/src/rakit_web/static/rakit.css`
  - Regenerated only with `bun run css:build` when source/template scanning requires a changed artifact.

### SQLAlchemy files modified

- `packages/rakit-sqlalchemy/src/rakit_sqlalchemy/datasource.py`
  - Keep filter coercion/whitelisting fail closed, accept effective predicate fields, and execute `PagePagination` plus `LimitOffsetPagination` only.

### Showcase/docs modified

- `examples/ui_showcase/main.py`
  - Configure realistic first-class filters and custom page-size policy on suitable resources.
- `docs/...` only where existing user-facing resource/generated-API examples need their declarations updated; do not create an unrelated documentation rewrite.

### Tests added/modified in the final test phase

- `packages/rakit-core/tests/test_resource_filters.py` (new)
- `packages/rakit-core/tests/test_query.py`
- `packages/rakit-core/tests/test_generated_api_definitions.py`
- `packages/rakit-core/tests/test_generated_api_compilation.py`
- `packages/rakit-core/tests/test_generated_api_query.py`
- `packages/rakit-web/tests/test_resource_query_configuration.py` (new)
- existing generated REST query/runtime tests in `packages/rakit-web/tests/`
- `packages/rakit-sqlalchemy/tests/` query/data-source tests covering pagination and resolved filter predicates
- facade/import tests under the existing `rakit` package tests
- root `tests/test_ui_showcase.py` only for showcase configuration contracts; run separately from package tests when root/package `conftest.py` isolation requires it.

---

### Task 1: Introduce first-class filter definitions and semantic selection provenance

**Files:**
- Create: `packages/rakit-core/src/rakit_core/filters.py`
- Modify: `packages/rakit-core/src/rakit_core/query.py`
- Modify: `packages/rakit-core/src/rakit_core/definitions.py`
- Modify: `packages/rakit-core/src/rakit_core/admin_types.py`

**Interfaces:**
- Produces `FilterControl`, `FilterChoice`, `FilterSelection`, `ResolvedFilterSelection`, `ResourceFilter`, `ChoiceFilter`, `BooleanFilter`, `TextFilter`, `NumberFilter`, `DateFilter`, `DateRangeFilter`, `LegacyFieldFilter`, `effective_resource_filters(...)`, and `resolve_filter_selection(...)`.
- `ResourceQuery.filter_selections: tuple[FilterSelection, ...]` stores validated semantic provenance separately from flattened `ResourceQuery.filters` predicates; adapters continue to execute only `filters`.
- `ResourceFilter.predicate_fields` is mandatory/derived for every concrete filter; runtime resolution rejects a custom implementation that emits a `Filter.field` outside this declaration.

- [ ] **Step 1: Create the core filter contract and built-ins**

Implement immutable Pydantic models with these public shapes:

```python
class FilterControl(StrEnum):
    LEGACY = "legacy"
    CHOICE = "choice"
    BOOLEAN = "boolean"
    TEXT = "text"
    NUMBER = "number"
    DATE = "date"
    DATE_RANGE = "date_range"


class FilterChoice(BaseModel):
    model_config = ConfigDict(frozen=True)
    value: str
    label: str


class FilterSelection(BaseModel):
    model_config = ConfigDict(frozen=True)
    filter_id: str
    operator: FilterOperator
    value: object


@dataclass(frozen=True, slots=True)
class ResolvedFilterSelection:
    selection: FilterSelection
    predicates: tuple[Filter, ...]
    display_value: str


class ResourceFilter(BaseModel):
    model_config = ConfigDict(frozen=True)
    filter_id: str
    label: str
    operators: tuple[FilterOperator, ...] = (FilterOperator.EQ,)
    predicate_fields: tuple[str, ...] = ()
    control: FilterControl = FilterControl.TEXT
    choices: tuple[FilterChoice, ...] = ()

    def parse_value(self, *, operator: FilterOperator, raw_value: object) -> object: ...
    def resolve_predicates(self, *, operator: FilterOperator, value: object) -> tuple[Filter, ...]: ...
    def serialize_value(self, *, operator: FilterOperator, value: object) -> str: ...
    def display_value(self, *, operator: FilterOperator, value: object) -> str: ...
```

Validation requirements:

- non-blank `filter_id`/`label`;
- non-empty unique operators;
- non-blank unique `predicate_fields`;
- non-blank unique choice values with non-blank labels;
- `resolve_filter_selection()` checks requested operator, parses the value, resolves predicates, and rejects any emitted predicate field not declared by `predicate_fields`.

Built-in behavior:

- `ChoiceFilter(field=...)`: `control=CHOICE`, default operator `EQ`, value must match one declared choice.
- `BooleanFilter(field=...)`: `control=BOOLEAN`, `EQ`, accepts bool or `true`/`false`, resolves typed bool.
- `TextFilter(field=...)`: `control=TEXT`, default operators `(EQ, NEQ, CONTAINS)`.
- `NumberFilter(field=...)`: `control=NUMBER`, operators `(EQ, NEQ, LT, LTE, GT, GTE)`; validate finite decimal syntax but preserve canonical string for adapter-specific field coercion.
- `DateFilter(field=...)`: `control=DATE`, operators `(EQ, NEQ, LT, LTE, GT, GTE)`; validate ISO date syntax but preserve canonical string.
- `DateRangeFilter(field=...)`: `control=DATE_RANGE`, operators `(GTE, LTE)` so Web may submit start/end as two semantic selections while adapters still receive ordinary predicates.
- `LegacyFieldFilter`: internal compatibility filter with all existing `FilterOperator` values and current `IN`/`IS_NULL` parsing/serialization semantics.

- [ ] **Step 2: Add semantic selections to `ResourceQuery` without breaking direct callers**

Keep existing `ResourceQuery.from_params(...)` arguments intact and add optional:

```python
filter_selections: tuple[FilterSelection, ...] = ()
```

Direct construction and all legacy callers with only `filters=` must continue to work.

- [ ] **Step 3: Add reusable filter declarations to resource definitions**

Add:

```python
class ResourceDefinition(BaseModel):
    ...
    filters: tuple[ResourceFilter, ...] = ()
```

Reject duplicate explicit filter IDs. Explicit filter IDs override a same-named synthesized legacy filter from `field_policy.filter_fields`; they do not create two controls.

Add to `ResourceAdmin`:

```python
filters: tuple[ResourceFilter, ...] = ()
```

- [ ] **Step 4: Add the normalization helper used by Web/API composition**

`effective_resource_filters(definition_or_explicit, legacy_fields)` returns explicit filters first plus `LegacyFieldFilter(filter_id=field, field=field, label=humanized_field_name)` only when no explicit filter has that ID.

Humanization is deterministic (`created_at -> Created at`) and presentation-only; transport identity remains the stable filter ID.

- [ ] **Step 5: Commit the feature slice**

```bash
git add packages/rakit-core/src/rakit_core/filters.py packages/rakit-core/src/rakit_core/query.py packages/rakit-core/src/rakit_core/definitions.py packages/rakit-core/src/rakit_core/admin_types.py
git commit -m "feat(core): add reusable resource filters"
```

---

### Task 2: Add page-size policy and explicit pagination strategy contracts

**Files:**
- Create: `packages/rakit-core/src/rakit_core/pagination.py`
- Modify: `packages/rakit-core/src/rakit_core/query.py`
- Modify: `packages/rakit-core/src/rakit_core/definitions.py`
- Modify: `packages/rakit-core/src/rakit_core/admin_types.py`
- Modify: `packages/rakit-core/src/rakit_core/datasource.py`
- Modify: `packages/rakit-core/src/rakit_core/resources.py`
- Modify: `packages/rakit-core/src/rakit_core/compiler.py`

**Interfaces:**
- Produces `PaginationStrategy.PAGE`, `.LIMIT_OFFSET`, `.CURSOR`.
- Produces `PageSizePolicy`, `ResourcePaginationPolicy`, `PagePagination`, compatibility alias `OffsetPagination`, `LimitOffsetPagination`, `CursorPagination`, `PageResult`, `LimitOffsetResult`, `CursorPageResult`, and `ResourceListResult`.
- `DataSourceCapabilities.pagination_strategies` defaults to `{PAGE}` so existing custom data sources remain source compatible.

- [ ] **Step 1: Create pagination configuration/request/result models**

Use these contracts:

```python
class PaginationStrategy(StrEnum):
    PAGE = "page"
    LIMIT_OFFSET = "limit_offset"
    CURSOR = "cursor"


class PageSizePolicy(BaseModel):
    model_config = ConfigDict(frozen=True)
    default: int = 25
    allowed: tuple[int, ...] = (25, 50, 100)


class ResourcePaginationPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)
    strategy: PaginationStrategy = PaginationStrategy.PAGE
    size: PageSizePolicy = Field(default_factory=PageSizePolicy)


class PagePagination(BaseModel):
    model_config = ConfigDict(frozen=True)
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=25, ge=1, le=200)

    @property
    def offset(self) -> int: ...


OffsetPagination = PagePagination


class LimitOffsetPagination(BaseModel):
    model_config = ConfigDict(frozen=True)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=25, ge=1, le=200)


class CursorPagination(BaseModel):
    model_config = ConfigDict(frozen=True)
    cursor: str | None = None
    limit: int = Field(default=25, ge=1, le=200)
```

Validate `PageSizePolicy` values: positive, <=200, unique, default included in allowed.

Result contracts:

```python
@dataclass(frozen=True)
class PageResult[T]:
    items: tuple[T, ...]
    page: int
    per_page: int
    has_previous: bool
    has_next: bool
    total_count: int | None = None


@dataclass(frozen=True)
class LimitOffsetResult[T]:
    items: tuple[T, ...]
    offset: int
    limit: int
    has_previous: bool
    has_next: bool
    total_count: int | None = None


@dataclass(frozen=True)
class CursorPageResult[T]:
    items: tuple[T, ...]
    limit: int
    previous_cursor: str | None = None
    next_cursor: str | None = None


type ResourceListResult[T] = PageResult[T] | LimitOffsetResult[T] | CursorPageResult[T]
```

- [ ] **Step 2: Make `ResourceQuery.pagination` a typed request union**

Preserve `ResourceQuery.from_params(page=..., per_page=...)` as the compatibility page constructor. Add a new constructor that accepts an already-validated pagination object:

```python
@classmethod
def from_components(
    cls,
    *,
    sort: str | None = None,
    pagination: PagePagination | LimitOffsetPagination | CursorPagination,
    allowed_sort_fields: Iterable[str],
    identity_fields: Sequence[str] = (),
    filters: tuple[Filter, ...] = (),
    filter_selections: tuple[FilterSelection, ...] = (),
    search: str | None = None,
    count_policy: CountPolicy = CountPolicy.EXACT,
) -> "ResourceQuery": ...
```

`from_params()` delegates to `from_components(pagination=PagePagination(...))`.

- [ ] **Step 3: Attach resource pagination policy**

Add:

```python
ResourceDefinition.pagination: ResourcePaginationPolicy = Field(default_factory=ResourcePaginationPolicy)
ResourceAdmin.pagination: ResourcePaginationPolicy = ResourcePaginationPolicy()
```

- [ ] **Step 4: Advertise pagination support on data sources and fail closed**

Extend:

```python
class DataSourceCapabilities(BaseModel):
    ...
    pagination_strategies: frozenset[PaginationStrategy] = frozenset({PaginationStrategy.PAGE})
```

Widen `DataSource.list()` and `ResourceService.list()` to `ResourceListResult`.

During resource registration/compilation, if `definition.pagination.strategy` is absent from `data_source.capabilities.pagination_strategies`, raise `CONFIG_INVALID_RESOURCE_POLICY` with a stable reason such as `pagination_strategy_not_supported`.

- [ ] **Step 5: Commit the feature slice**

```bash
git add packages/rakit-core/src/rakit_core/pagination.py packages/rakit-core/src/rakit_core/query.py packages/rakit-core/src/rakit_core/definitions.py packages/rakit-core/src/rakit_core/admin_types.py packages/rakit-core/src/rakit_core/datasource.py packages/rakit-core/src/rakit_core/resources.py packages/rakit-core/src/rakit_core/compiler.py
git commit -m "feat(core): add resource pagination strategies"
```

---

### Task 3: Wire Admin composition and adapter predicate-field safety

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/admin.py`
- Modify: `packages/rakit-sqlalchemy/src/rakit_sqlalchemy/datasource.py`

**Interfaces:**
- Consumes explicit `ResourceAdmin.filters` and `ResourceAdmin.pagination`.
- Produces a `ResourceDefinition` with reusable filters/pagination.
- Model adapter claims receive an effective field policy whose `filter_fields` is the ordered union of legacy `filter_fields` plus every first-class filter `predicate_fields`; the canonical `ResourceDefinition.field_policy.filter_fields` remains the developer's legacy declaration and is not widened for presentation.

- [ ] **Step 1: Normalize ResourceAdmin filter declarations before adapter claim**

Validate `admin_cls.filters` is list/tuple of `ResourceFilter` instances. Convert to tuple and reject duplicate explicit IDs through the core definition contract.

Build adapter-only effective predicate field order:

```python
legacy = tuple(field_policy.filter_fields)
predicate_fields = tuple(
    field
    for definition in explicit_filters
    for field in definition.predicate_fields
)
effective_filter_fields = tuple(dict.fromkeys((*legacy, *predicate_fields)))
adapter_field_policy = field_policy.model_copy(update={"filter_fields": effective_filter_fields})
```

Pass `adapter_field_policy` to model adapter claims, but store the original `field_policy` plus `filters=explicit_filters` in `ResourceDefinition`.

- [ ] **Step 2: Carry pagination declaration into `ResourceDefinition`**

Validate `admin_cls.pagination` is `ResourcePaginationPolicy`; invalid declarations produce the existing public configuration boundary rather than raw Pydantic details.

- [ ] **Step 3: Keep SQLAlchemy filtering fail closed with effective predicate fields**

Do not relax `_validate_query_policy`. SQLAlchemy should continue validating actual `Filter.field` against the effective adapter `field_policy.filter_fields`, which now contains fields declared by custom filter definitions.

Set SQLAlchemy read capabilities to:

```python
DataSourceCapabilities(
    read=True,
    pagination_strategies=frozenset({PaginationStrategy.PAGE, PaginationStrategy.LIMIT_OFFSET}),
)
```

Implement `list()` branching:

- `PagePagination`: preserve existing count/deferred/disabled behavior and return `PageResult` exactly as today.
- `LimitOffsetPagination`: use `offset`/`limit`; exact count computes `has_next` against total, non-exact fetches one extra row; return `LimitOffsetResult`.
- `CursorPagination`: unreachable after capability validation; if received by direct misuse, fail closed with `CONFIG_INVALID_RESOURCE_POLICY` rather than silently interpreting it as offset/page.

- [ ] **Step 4: Commit the feature slice**

```bash
git add packages/rakit-web/src/rakit_web/admin.py packages/rakit-sqlalchemy/src/rakit_sqlalchemy/datasource.py
git commit -m "feat(query): wire resource filter and pagination policy"
```

---

### Task 4: Unify generated API filter exposure with resource filters

**Files:**
- Modify: `packages/rakit-core/src/rakit_core/generated_api.py`
- Modify: `packages/rakit-core/src/rakit_core/generated_compiler.py`
- Modify: `packages/rakit-core/src/rakit_core/generated_query.py`

**Interfaces:**
- `ResourceApiDefinition.filters` accepts `tuple[str | ApiFilterDefinition, ...]`.
- Produces internal `CompiledApiFilterDefinition(name, filter, operators)`; this compiled type is not exported from the top-level `rakit` facade.
- A string API entry references an effective resource filter ID and exposes only that definition's operators.
- Direct legacy `ApiFilterDefinition` remains field-based and uses a compatibility `LegacyFieldFilter` configured with its historical name/field/operator allowlist.

- [ ] **Step 1: Expand the API declaration while preserving direct definitions**

Change:

```python
filters: tuple[str | ApiFilterDefinition, ...] = ()
```

Validate unique public API filter names across mixed entries (`str` value itself vs `ApiFilterDefinition.name`) and reject blank string references.

Add internal compiled shape:

```python
@dataclass(frozen=True, slots=True)
class CompiledApiFilterDefinition:
    name: str
    filter: ResourceFilter
    operators: tuple[FilterOperator, ...]
```

`CompiledResourceApi.filters` becomes this normalized tuple and carries `pagination: ResourcePaginationPolicy`.

- [ ] **Step 2: Resolve API allowlist entries at compile time**

Build the resource's effective filter map from explicit definitions + legacy synthesized fields.

For string references:

- unknown ID -> `generated_api_filter_not_found` configuration failure;
- use the same `ResourceFilter` instance/contract as Web;
- operators are `definition.operators`.

For direct `ApiFilterDefinition`:

- preserve the existing known-field + legacy `field_policy.filter_fields` validation;
- synthesize `LegacyFieldFilter(filter_id=item.name, field=item.field, operators=item.operators, ...)`;
- do not automatically widen direct legacy API definitions to arbitrary first-class predicate fields.

- [ ] **Step 3: Resolve generated filter values through shared definitions**

Keep `GeneratedFilterValue(name, operator, value)` for transport/runtime compatibility, but `build_generated_resource_query()` must:

1. find `CompiledApiFilterDefinition` by `name`;
2. reject unexposed names/operators;
3. call `resolve_filter_selection(compiled.filter, operator=..., raw_value=...)`;
4. append `resolved.predicates` to `ResourceQuery.filters`;
5. append `resolved.selection` to `ResourceQuery.filter_selections`;
6. construct the query with `api.pagination`'s request strategy.

- [ ] **Step 4: Commit the feature slice**

```bash
git add packages/rakit-core/src/rakit_core/generated_api.py packages/rakit-core/src/rakit_core/generated_compiler.py packages/rakit-core/src/rakit_core/generated_query.py
git commit -m "feat(api): reuse resource filter definitions"
```

---

### Task 5: Make generated REST strategy-aware without changing filter URL syntax

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/generated_rest.py`
- Modify: `packages/rakit-web/src/rakit_web/generated_rest_runtime.py`

**Interfaces:**
- Filter transport remains `filter[name]` / `filter[name][operator]`.
- Transport no longer performs semantic `IN`/`IS_NULL` coercion globally; it passes the raw string to the compiled filter resolver so built-in/custom definitions own value semantics.
- Page resources accept `page` + `per_page`; limit-offset resources accept `offset` + `limit`; cursor resources accept `cursor` + `limit`.

- [ ] **Step 1: Keep generated REST filter parsing shape stable and delegate semantics**

`parse_generated_rest_query()` still validates duplicate names and operator token syntax, then creates `GeneratedFilterValue(..., value=raw_value)`. Remove transport-specific semantic coercion that would bypass custom filter parsing.

- [ ] **Step 2: Parse only pagination parameters valid for the configured strategy**

Use a strategy-specific singleton allowlist:

```text
PAGE         page, per_page, sort, search
LIMIT_OFFSET offset, limit, sort, search
CURSOR       cursor, limit, sort, search
```

Reject parameters belonging to another strategy as `generated_api_query_parameter_not_allowed`.

Apply `PageSizePolicy` to user-provided `per_page`/`limit`; invalid API values return 400 `generated_api_invalid_pagination` rather than silently falling back.

- [ ] **Step 3: Serialize list result metadata by actual result type**

Generated REST responses remain `{data, meta}` but truthful metadata is strategy-specific:

```json
{"page": 2, "per_page": 25, "has_previous": true, "has_next": true, "total": 137}
```

```json
{"offset": 25, "limit": 25, "has_previous": true, "has_next": true, "total": 137}
```

```json
{"limit": 25, "previous_cursor": "...", "next_cursor": "..."}
```

Never manufacture a page number or total pages for a cursor result.

- [ ] **Step 4: Commit the feature slice**

```bash
git add packages/rakit-web/src/rakit_web/generated_rest.py packages/rakit-web/src/rakit_web/generated_rest_runtime.py
git commit -m "feat(api): support resource query strategies"
```

---

### Task 6: Replace the primary Admin filter builder with definition-driven filter groups

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/resource_routes.py`
- Modify: `packages/rakit-web/src/rakit_web/templates/resources/list.html`
- Modify: `packages/rakit-web/src/rakit_web/templates/resources/_table.html`
- Modify: `packages/rakit-web/src/rakit_web/icons.py`
- Modify: `packages/rakit-web/src/rakit_web/assets/rakit.css` only if existing primitives are insufficient

**Interfaces:**
- Web canonical legacy-compatible state remains repeatable `filter=<filter_id>:<operator>:<serialized-value>`.
- Web parser resolves IDs through `effective_resource_filters()`; legacy synthesized filters preserve the old URL exactly because `filter_id == field`.
- `ResourceQuery.filter_selections` is the source of validated semantic filter identity used for chips/remove links; adapters receive only flattened predicates.

- [ ] **Step 1: Make `ResourceBinding` expose effective filters and pagination policy**

Add properties:

```python
@property
def filter_definitions(self) -> tuple[ResourceFilter, ...]: ...

@property
def pagination_policy(self) -> ResourcePaginationPolicy: ...
```

Replace `_parse_filters(params, allowed_fields)` with parsing that:

- splits canonical `filter=id:operator:value`;
- looks up the registered filter ID;
- calls `resolve_filter_selection()`;
- tolerantly skips malformed/unknown Web fragments as today;
- returns both semantic selections and flattened predicates;
- never reflects unvalidated raw state into links.

- [ ] **Step 2: Canonicalize no-JS typed filter controls**

Keep the current redirect-to-canonical pattern, but builder aliases now target a specific filter definition:

```text
filter_id
filter_operator
filter_value
```

For `DateRangeFilter`, accept `filter_start` and/or `filter_end` and canonicalize them into `GTE`/`LTE` selections.

Choice/boolean/custom-choice groups should primarily use direct GET links rather than requiring Apply; text/number/date controls use compact GET forms and canonical redirect.

- [ ] **Step 3: Build Django-admin-style presentation groups**

Template context for each filter includes stable fields such as:

```python
{
    "filter_id": "status",
    "label": "Status",
    "control": "choice",
    "operators": [...],
    "choices": [
        {"value": "paid", "label": "Paid", "url": "...", "selected": True},
    ],
    "active": [...],
}
```

Presentation rules:

- Choice/custom choice: `All` plus direct semantic choices.
- Boolean: `All / Yes / No`.
- Text/number/date: one compact input + only allowed operators.
- Date range: From / To controls.
- Legacy synthesized filter: retain generic Field/Condition/Value behavior only for that legacy definition, not as the default UI for first-class filters.

Active chips use the filter definition label and definition-provided display value, not backend predicate field/operator internals.

- [ ] **Step 4: Make sortable capability visible before activation**

Extend sort-header context with a stable state (`unsorted`, `ascending`, `descending`, `secondary`, `none`).

Render:

- no icon for non-sortable headers;
- neutral Lucide `arrow-up-down` (or the closest existing vendored equivalent) for sortable inactive headers;
- ascending/descending icon for active primary sort;
- accessible text/label remains present and `aria-sort` remains authoritative.

Do not change existing multi-sort toggle semantics.

- [ ] **Step 5: Apply page-size policy in Web request parsing and controls**

For PAGE, read `per_page`; LIMIT_OFFSET/CURSOR read `limit`.

Web behavior for malformed/disallowed user values is tolerant but safe: normalize to `policy.size.default` and canonical links use only validated policy values. Do not show arbitrary user-provided values as a new `(custom)` UI option anymore.

Page-size selector:

- options exactly `policy.size.allowed`;
- hidden entirely when only one allowed value exists;
- changing size resets PAGE to page 1, LIMIT_OFFSET to offset 0, and CURSOR to no cursor.

- [ ] **Step 6: Build strategy-aware pagination context**

PAGE:
- exact total -> numbered pagination;
- deferred/disabled/no total -> Previous/Next only.

LIMIT_OFFSET:
- Previous/Next URLs with validated offsets; optional truthful range/total when exact.
- no numbered-page UI.

CURSOR:
- Previous/Next URLs from result cursors only;
- no fake totals/pages.

- [ ] **Step 7: Commit the feature slice**

```bash
git add packages/rakit-web/src/rakit_web/resource_routes.py packages/rakit-web/src/rakit_web/templates/resources/list.html packages/rakit-web/src/rakit_web/templates/resources/_table.html packages/rakit-web/src/rakit_web/icons.py packages/rakit-web/src/rakit_web/assets/rakit.css
git commit -m "feat(web): add definition-driven resource filters"
```

---

### Task 7: Export the public API and make the showcase demonstrate the new contract

**Files:**
- Modify: `packages/rakit/src/rakit/__init__.py`
- Modify: `examples/ui_showcase/main.py`
- Modify: existing targeted docs/examples if they currently teach the old primary filter-builder pattern

**Interfaces:**
- Export only developer-facing declarations: `ResourceFilter`, `FilterChoice`, `ChoiceFilter`, `BooleanFilter`, `TextFilter`, `NumberFilter`, `DateFilter`, `DateRangeFilter`, `FilterSelection`, `PaginationStrategy`, `PageSizePolicy`, `ResourcePaginationPolicy`, `PagePagination`, `LimitOffsetPagination`, `CursorPagination`.
- Keep internal legacy/compiled normalization types private.

- [ ] **Step 1: Add facade exports**

Ensure users can write:

```python
from rakit import ChoiceFilter, FilterChoice, PageSizePolicy, ResourcePaginationPolicy
```

without importing private core modules.

- [ ] **Step 2: Convert showcase Orders to first-class filters**

Use realistic explicit definitions, for example:

```python
filters = (
    ChoiceFilter(
        filter_id="status",
        label="Status",
        field="status",
        choices=(
            FilterChoice(value="Paid", label="Paid"),
            FilterChoice(value="Pending review", label="Pending review"),
            FilterChoice(value="Processing", label="Processing"),
            FilterChoice(value="Fulfilled", label="Fulfilled"),
            FilterChoice(value="Refunded", label="Refunded"),
            FilterChoice(value="Cancelled", label="Cancelled"),
        ),
    ),
    NumberFilter(filter_id="total", label="Total", field="total"),
    DateRangeFilter(filter_id="created", label="Created", field="created"),
)
```

Set an explicit page-size policy such as `(25, 50, 100)` so the showcase demonstrates the same default contract through the public API rather than Web hard-coding.

If the showcase exposes generated REST for the same resource, expose only selected filter IDs explicitly; do not expose every Admin filter automatically.

- [ ] **Step 3: Build CSS through the official pipeline if template/source scanning changed output**

Run:

```bash
bun run css:build
```

Commit `packages/rakit-web/src/rakit_web/static/rakit.css` only if that command changes it. Never hand-edit generated CSS.

- [ ] **Step 4: Commit the feature slice**

```bash
git add packages/rakit/src/rakit/__init__.py examples/ui_showcase/main.py packages/rakit-web/src/rakit_web/static/rakit.css
git commit -m "feat(showcase): demonstrate resource query configuration"
```

---

### Task 8: Add focused regression coverage after feature completion

**Files:**
- Create: `packages/rakit-core/tests/test_resource_filters.py`
- Modify: `packages/rakit-core/tests/test_query.py`
- Modify: `packages/rakit-core/tests/test_generated_api_definitions.py`
- Modify: `packages/rakit-core/tests/test_generated_api_compilation.py`
- Modify: `packages/rakit-core/tests/test_generated_api_query.py`
- Create: `packages/rakit-web/tests/test_resource_query_configuration.py`
- Modify: existing generated REST tests under `packages/rakit-web/tests/`
- Modify: SQLAlchemy datasource/query tests under `packages/rakit-sqlalchemy/tests/`
- Modify: facade/import tests under the existing `rakit` package tests
- Modify: `tests/test_ui_showcase.py` only for public showcase declarations/rendering

**Interfaces:**
- Tests assert semantic contracts and security boundaries, not fragile attribute ordering or complete HTML snapshots.

- [ ] **Step 1: Cover core filter definitions and custom resolution**

Add cases for:

- built-in validation and value parsing;
- custom subclass resolving one semantic value to multiple AND predicates;
- custom filter emitting an undeclared predicate field -> rejected;
- duplicate/blank filter IDs/labels/choices/operators;
- explicit filter overriding same-named legacy synthesized filter;
- legacy `filter_fields` normalization preserving ID/field/operator behavior;
- `FilterSelection` provenance alongside flattened `ResourceQuery.filters`.

- [ ] **Step 2: Cover pagination contracts**

Add cases for:

- `OffsetPagination is PagePagination` compatibility;
- default `PageSizePolicy(25, (25,50,100))`;
- invalid size policies;
- page/limit-offset/cursor query construction;
- data source capability rejection for unsupported strategy.

- [ ] **Step 3: Cover generated API filter reuse and fail-closed exposure**

Add cases proving:

- `filters=("status",)` resolves the resource's shared `ChoiceFilter`;
- unexposed `internal_risk` remains rejected by REST even when Admin Web has it;
- unknown filter ID fails compile;
- direct legacy `ApiFilterDefinition` still compiles and executes;
- custom semantic API filter resolves to the same predicates as Web;
- invalid operator/value still returns generated API validation errors.

- [ ] **Step 4: Cover Admin Web presentation and URL state**

Add cases for:

- choice/boolean/custom choice groups render direct options;
- typed controls expose only definition-approved operators;
- active chip label/value derives from semantic selection;
- removing/clearing filters preserves validated search/sort/size/count state and resets navigation;
- malformed/unknown Web filter fragments do not widen allowed query state;
- legacy resource still renders compatibility builder;
- inactive sortable headers visibly advertise sorting, active directions remain accessible, non-sortable headers do not;
- allowed page sizes come from resource policy; single allowed size suppresses selector; disallowed URL value normalizes to default;
- PAGE vs LIMIT_OFFSET vs CURSOR navigation is truthful and never fabricates page numbers/cursors.

- [ ] **Step 5: Cover SQLAlchemy strategy/filter behavior**

Add tests proving:

- first-class filter predicate fields are accepted even when not listed as legacy Admin `filter_fields` because adapter claim receives effective predicate fields;
- undeclared query fields still fail;
- PAGE behavior remains byte-for-behavior compatible in result metadata;
- LIMIT_OFFSET executes correct offset/limit and next/previous behavior for exact and non-exact counts;
- cursor request is rejected for SQLAlchemy rather than emulated.

- [ ] **Step 6: Run focused suites**

Run package suites separately where `conftest.py` namespaces collide:

```bash
uv run pytest packages/rakit-core/tests/test_resource_filters.py packages/rakit-core/tests/test_query.py packages/rakit-core/tests/test_generated_api_definitions.py packages/rakit-core/tests/test_generated_api_compilation.py packages/rakit-core/tests/test_generated_api_query.py -q
uv run pytest packages/rakit-web/tests/test_resource_query_configuration.py -q
uv run pytest packages/rakit-sqlalchemy/tests -q
uv run pytest tests/test_ui_showcase.py -q
```

Expected: all pass.

- [ ] **Step 7: Commit the test phase**

```bash
git add packages/rakit-core/tests packages/rakit-web/tests packages/rakit-sqlalchemy/tests tests/test_ui_showcase.py
git commit -m "test(query): cover resource query configuration"
```

---

### Task 9: Final verification, PR review, and staging integration

**Files:**
- No product files unless verification identifies a real defect.
- PR: `ui-05d-resource-query-configuration -> ui-05-resource-experience`.

- [ ] **Step 1: Run formatting, lint, typing, and diff checks**

```bash
uv run ruff format --check .
uv run ruff check .
uv run ty check
git diff --check
```

Expected: all pass.

- [ ] **Step 2: Run the full repository test suite with coverage**

```bash
uv run pytest -n auto --cov
```

Expected: all tests pass; no unexplained coverage regression.

- [ ] **Step 3: Run release-like gates**

```bash
uv run mkdocs build --strict
uv run python scripts/check_artifacts.py
```

Expected: both pass.

- [ ] **Step 4: Review the complete diff against the integration branch**

Review specifically for:

- no automatic API exposure of Admin-only filters;
- no adapter-specific callback leaking into core filter contracts;
- no custom filter predicate field outside declared `predicate_fields`;
- no raw/unvalidated request values reflected into canonical links;
- existing legacy filter/API URLs remain accepted;
- page-size policy cannot widen beyond configured values through Web/API input;
- unsupported pagination strategies fail closed;
- SQLAlchemy does not fake cursor support;
- generated REST metadata matches actual result strategy;
- no UI-06/database/release scope creep;
- no temporary CI/debug files.

- [ ] **Step 5: Create/update the UI-05D PR and verify GitHub CI**

PR title:

```text
UI-05D resource query configuration
```

Base:

```text
ui-05-resource-experience
```

Keep the final UI-05 integration PR #21 to `main` draft.

- [ ] **Step 6: After UI-05D PR is green and review-clean, squash-merge it into `ui-05-resource-experience`**

This per-slice staging merge is already authorized by the user. Do **not** merge PR #21 (`ui-05-resource-experience -> main`) until final browser/visual acceptance.

- [ ] **Step 7: Re-run integrated UI-05 CI and browser acceptance**

Verify Dashboard + Resource List + Detail/Form surfaces again, with special visual focus on:

- Django-admin-style filter groups;
- active filter chips/remove links;
- inactive sort affordances and active direction;
- resource-configured rows-per-page;
- mobile resource list remains usable;
- dark theme remains readable.

Only after this acceptance should PR #21 be marked ready for merge to `main`.
