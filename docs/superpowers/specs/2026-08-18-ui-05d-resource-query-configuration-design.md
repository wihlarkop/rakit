# UI-05D Resource Query Configuration — Design

Date: 2026-08-18
Status: design approved in chat; written-spec review pending
Branch: `ui-05-resource-experience`

## Purpose

UI-05D turns Rakit resource querying into one backend-neutral capability shared by the Admin Web experience and generated REST API. The immediate user-facing goal is a Django-admin-like filter experience, clearer sortable-column affordances, configurable rows-per-page, and a query model that can grow beyond page-number pagination without coupling adapters to the Web transport.

The implementation must preserve Rakit's existing principles: fail closed, explicit external exposure, progressive enhancement, typed public APIs, capability-aware adapters, and no hidden coupling between Web and persistence implementations.

## Current State

Rakit already has most of the execution foundation required for this work:

- `ResourceQuery` carries sorting, filters, search, pagination, and count policy.
- `Filter` and `FilterOperator` are backend-neutral.
- the Admin Web resource list parses filter query parameters into `Filter` objects;
- generated REST has `ApiFilterDefinition`, validates submitted filters, and also resolves them into `Filter` objects before constructing `ResourceQuery`;
- SQLAlchemy and other data sources consume `ResourceQuery` rather than Web-specific request state.

The gap is primarily the definition/configuration layer. Admin Web currently exposes arbitrary operators for fields listed in `ResourceFieldPolicy.filter_fields`, while generated REST separately defines filters in `ResourceApiDefinition.filters`. This duplicates policy and makes a richer Django-admin-style filter UX difficult without creating another parallel filter system.

The current `OffsetPagination` name also represents page-number pagination (`page`, `per_page`) rather than a true limit/offset transport. UI-05D must avoid breaking existing callers while creating room for explicit pagination strategies.

## Goals

1. Introduce first-class resource filter definitions in `rakit-core`.
2. Let Admin Web and generated REST reuse the same filter definition/resolution logic.
3. Keep generated REST filter exposure explicitly allowlisted and fail closed.
4. Provide useful built-in filter types plus a custom-filter extension point.
5. Preserve existing resources that only declare `field_policy.filter_fields`.
6. Preserve existing generated API definitions that use `ApiFilterDefinition` directly.
7. Keep canonical query execution in backend-neutral `Filter` / `ResourceQuery` objects.
8. Preserve validated semantic filter identity separately from flattened backend predicates so Web presentation and URL reconstruction remain correct.
9. Improve Admin Web filter UX toward Django Admin: named filter groups, direct choices where appropriate, readable active-filter chips, and no requirement for users to understand arbitrary backend operators.
10. Make sortable columns visibly sortable even before they are selected.
11. Make rows-per-page policy configurable per resource while retaining the existing 25/50/100 behavior by default.
12. Establish explicit pagination strategy types without forcing every adapter to support every strategy.
13. Preserve normal GET navigation and HTMX progressive enhancement.

## Non-goals

UI-05D will not introduce:

- arbitrary boolean predicate expression trees (`OR`, nested `AND`, `NOT`);
- a generic query-language DSL;
- automatic API exposure for every Admin Web filter;
- persistence-specific filter definitions;
- automatic relationship joins hidden inside core filter primitives;
- client-side-only filtering or pagination;
- release, tag, or PyPI work;
- UI-06 action/relationship/auth/custom-page redesign.

Custom filters in this phase may resolve one submitted value to zero, one, or multiple backend-neutral `Filter` predicates. Multiple predicates are AND-composed by the existing `ResourceQuery.filters` semantics.

## Architecture

### 1. Resource filter definitions

Add a focused core module, expected to be `rakit_core.filters`, containing the public filter-definition contract and built-in implementations.

The common contract has these responsibilities:

- stable `filter_id` used by transports;
- human-readable `label` used by Admin Web;
- declared supported operators where operator selection is meaningful;
- input parsing/validation;
- optional presentation choices;
- resolution into zero or more backend-neutral `Filter` objects.

The contract must not depend on Starlette, Jinja, SQLAlchemy, or generated REST.

Conceptually:

```python
class ResourceFilter:
    filter_id: str
    label: str

    def resolve(
        self,
        *,
        operator: FilterOperator,
        raw_value: object,
    ) -> tuple[Filter, ...]: ...
```

The exact implementation may use an abstract base class or another typed immutable contract, but callers must be able to understand and use the filter without reading its internals.

### 2. Resolved filter selection

A semantic filter cannot be represented only by its flattened backend predicates. For example, `stock=low` may resolve to `on_hand <= 10`; if only the predicate survives, Web can no longer render the label “Stock level: Low stock” or rebuild the canonical removal URL.

Introduce an internal/core-normalization value, conceptually:

```python
ResolvedFilterSelection(
    filter_id="stock",
    operator=FilterOperator.EQ,
    canonical_value="low",
    predicates=(
        Filter(
            field="on_hand",
            operator=FilterOperator.LTE,
            value=10,
        ),
    ),
)
```

Responsibilities:

- retain the validated resource filter ID;
- retain the validated operator;
- retain a transport-safe canonical value for serialization/presentation;
- contain the one-or-more backend-neutral `Filter` predicates produced by the definition.

`ResourceQuery` remains the execution contract adapters consume. Its `filters` are the flattened predicates from all resolved selections. Transport layers may retain the resolved selections alongside the `ResourceQuery` for presentation and canonical URL generation.

UI-05D should not force adapters to understand semantic filter IDs or presentation labels.

### 3. Built-in filter types

UI-05D provides a small practical set rather than a mini query framework:

- `ChoiceFilter`
- `BooleanFilter`
- `TextFilter`
- `NumberFilter`
- `DateFilter`
- `DateRangeFilter`

A field-backed base/helper may be used internally to avoid duplication.

Built-ins are explicit. Rakit must not infer `ChoiceFilter` merely because a field is named `status`, nor infer persistence behavior from Python/SQL types at this layer.

Examples:

```python
ChoiceFilter(
    filter_id="status",
    label="Status",
    field="status",
    choices=(
        FilterChoice("pending", "Pending"),
        FilterChoice("paid", "Paid"),
        FilterChoice("cancelled", "Cancelled"),
    ),
)
```

```python
NumberFilter(
    filter_id="total",
    label="Total",
    field="total",
    operators=(FilterOperator.GTE, FilterOperator.LTE),
)
```

Built-ins validate/coerce their own logical inputs before producing predicates. Number/date filters therefore do not rely on a Web-only parser to decide what a valid number/date means.

`DateRangeFilter` resolves two canonical selections for the same logical filter ID, normally `GTE` for the start and `LTE` for the end. This keeps the existing repeatable filter URL shape composable and avoids inventing an encoded range mini-format.

### 4. Custom filters

Developers may provide custom filter implementations with semantic choices. A custom filter is allowed to translate one public value into multiple ordinary `Filter` objects.

Conceptual example:

```python
class LowStockFilter(ResourceFilter):
    filter_id = "stock"
    label = "Stock level"

    def choices(self):
        return (
            FilterChoice("low", "Low stock"),
            FilterChoice("out", "Out of stock"),
        )

    def resolve(self, *, operator, raw_value):
        if raw_value == "low":
            return (
                Filter(
                    field="on_hand",
                    operator=FilterOperator.LTE,
                    value=10,
                ),
            )
        if raw_value == "out":
            return (
                Filter(
                    field="on_hand",
                    operator=FilterOperator.EQ,
                    value=0,
                ),
            )
        raise ValueError("unsupported stock filter value")
```

Invalid custom values must fail validation rather than resolve silently to an unfiltered query. “No filter selected” is represented by absence of a submitted selection, not by an invalid value resolving to `()`.

Custom filter resolution stays backend-neutral. If a future custom filter needs OR/nested expressions, that belongs to a later predicate-expression capability rather than being smuggled into adapter-specific callbacks now.

### 5. Resource ownership of filter definitions

`ResourceDefinition` becomes the owner of reusable filter definitions.

Expected shape:

```python
ResourceDefinition(
    ...,
    filters=(
        ChoiceFilter(...),
        LowStockFilter(),
    ),
)
```

Filter IDs must be unique within a resource. Invalid or duplicate definitions fail at compile/configuration time.

`ResourceFieldPolicy.filter_fields` remains supported for compatibility. When a resource has no explicit first-class definition for a legacy filter field, the compiler/runtime synthesizes a legacy field filter with:

- `filter_id == field name`;
- label derived from the field name;
- current `FilterOperator` behavior;
- the same canonical execution through `Filter`.

This compatibility path prevents UI-05D from forcing every existing resource to migrate immediately. New documentation should favor first-class resource filters.

If an explicit filter definition uses the same ID as a legacy `filter_fields` entry, the explicit definition wins; the legacy entry is not synthesized twice.

### 6. Generated API exposure

Admin availability and external API exposure are deliberately separate concerns.

A filter being configured on a resource means it may be presented by Admin Web. It does **not** mean generated REST may expose it.

Generated API remains explicit and fail closed.

Preferred ergonomic form:

```python
ResourceApiDefinition(
    exposure=ApiExposure.READ_ONLY,
    filters=("status", "total"),
)
```

Each string references a registered resource filter ID. Compilation resolves that ID to the same filter definition used by Admin Web.

For backwards compatibility, `ResourceApiDefinition.filters` accepts either resource filter-ID strings or existing direct `ApiFilterDefinition(...)` values during this migration. The generated compiler normalizes both forms into one compiled API-filter contract. Unknown resource filter IDs fail compilation; they must never silently become arbitrary field filters.

A resource can therefore contain:

```text
resource filter     Admin Web     Generated REST
status              yes           yes
internal_risk       yes           no
```

This is a hard security boundary.

Direct legacy `ApiFilterDefinition` continues to execute as a field-backed API-only filter; it does not implicitly add an Admin Web filter.

### 7. Generated REST query syntax

Keep the current generated REST syntax stable:

```text
?filter[status]=paid
?filter[total][gte]=100
```

For semantic/custom filters:

```text
?filter[stock]=low
```

The transport parser performs only transport concerns (parameter shape, duplication, basic token parsing), then delegates semantic validation/resolution to the compiled reusable filter definition.

Unknown filter IDs, unapproved operators, duplicated identical filter keys, or invalid values remain 400-class validation errors.

A Web-only resource filter that is omitted from `ResourceApiDefinition.filters` must be rejected by generated REST even though the same definition exists on the resource.

### 8. Admin Web canonical filter URL

Keep the existing repeatable Web syntax for backwards compatibility:

```text
?filter=<filter_id>:<operator>:<value>
```

For legacy synthesized filters, `filter_id == field`, so existing URLs remain valid.

Examples:

```text
?filter=status:eq:paid
?filter=total:gte:100
?filter=stock:eq:low
?filter=created_at:gte:2026-08-01&filter=created_at:lte:2026-08-31
```

The first segment is now interpreted as a registered filter ID, not as permission to access an arbitrary field.

The parser resolves each submitted selection through the matching definition, retains a `ResolvedFilterSelection` for presentation/serialization, and flattens its predicates into `ResourceQuery.filters` for execution.

Malformed or unknown Admin Web filter selections keep the current tolerant Web philosophy: they are dropped from canonical state rather than widening permissions or causing arbitrary execution. Invalid values for a known first-class filter are also dropped from canonical Web state and must never be reflected back into links.

Generated REST remains stricter and returns 400 for corresponding invalid API requests.

### 9. Admin Web filter experience

The resource list moves away from a generic “field + arbitrary operator + arbitrary text” interaction as the primary UX.

The Filters control opens a panel containing named filter groups. Presentation depends on filter definition:

- `ChoiceFilter`: direct choices, similar to Django Admin;
- `BooleanFilter`: All / Yes / No style choices;
- text/number/date filters: compact typed input plus only the operators allowed by that definition;
- date range: start/end controls;
- custom filters with choices: direct semantic choices.

The existing generic legacy filter builder remains available only for synthesized legacy field filters so current resource behavior is not lost.

Active filters continue to render as removable chips and Clear all remains available.

Chip presentation is driven by the originating `ResolvedFilterSelection`, not reconstructed from flattened backend predicates. Semantic filters therefore show human labels/choice labels rather than internal field names such as `on_hand <= 10` unless the filter definition intentionally exposes that text.

Canonical resource-list URLs remain server-owned GET query state. HTMX is an enhancement only.

### 10. Query-state serialization

Web query-state helpers preserve only state that survived validation against the resource definition.

The authoritative validated state used to build links includes:

- resolved filter selections;
- normalized search;
- validated explicit sorting;
- validated page-size choice;
- count policy;
- current pagination navigation state.

Filter/search/sort/page-size changes reset page-number navigation to page 1. Equivalent reset semantics apply to other pagination strategies by clearing stale offset/cursor state.

No unvalidated raw request parameter may be reflected into generated links.

## Sorting affordance

UI-05D keeps existing multi-sort semantics but makes sort capability visible.

For list-table headers:

- non-sortable field: no sort icon;
- sortable but not active: neutral bidirectional sort affordance;
- active ascending: ascending icon/state;
- active descending: descending icon/state.

Accessible behavior remains authoritative:

- primary active sort uses `aria-sort="ascending"` or `aria-sort="descending"`;
- secondary active multi-sort columns retain an accessible indication without pretending they are primary;
- icon-only visual state is never the sole source of meaning.

Clicking a sortable column preserves validated filters/search/page-size and resets navigation to the first page/current-strategy origin.

## Page-size policy

Rows-per-page becomes resource-configurable while preserving current defaults.

Introduce an immutable page-size configuration, expected shape:

```python
PageSizePolicy(
    default=25,
    allowed=(25, 50, 100),
)
```

Rules:

- default remains 25;
- default allowed choices remain 25/50/100;
- `default` must be present in `allowed`;
- all values must respect the framework hard maximum already enforced by pagination;
- duplicate/non-positive values fail configuration;
- if exactly one size is allowed, Admin Web does not render a page-size selector;
- programmatic construction of `ResourceQuery` remains possible within hard safety bounds;
- user-submitted Web/API page sizes must obey the resource page-size policy once one is configured.

Invalid submitted size behavior is intentionally surface-specific:

- Admin Web: fall back to the resource default and emit only the validated default in canonical links;
- generated REST: reject the request with 400 because external API query contracts remain strict.

Changing page size clears stale pagination state and starts from the strategy origin.

## Pagination strategy foundation

UI-05D establishes explicit pagination strategy types without requiring every adapter to support every type immediately.

### Compatibility naming

The existing `OffsetPagination(page, per_page)` is semantically page-number pagination. Breaking all callers solely to fix the name is not acceptable.

The design therefore introduces:

- `PagePagination(page, per_page)` as the canonical page-number model;
- existing `OffsetPagination` retained as a compatibility alias/deprecated public name for page-number pagination;
- `LimitOffsetPagination(offset, limit)` for true offset/limit pagination;
- `CursorPagination(cursor, limit)` for opaque cursor pagination.

`ResourceQuery.pagination` becomes a typed union of supported pagination request models.

Compatibility must preserve existing code that directly constructs `OffsetPagination(page=..., per_page=...)` or reads `.page`, `.per_page`, and `.offset` from the current page-number model.

### Resource pagination configuration

A resource may choose its preferred pagination strategy/configuration. Page-number remains the default, so existing resources require no changes.

The configuration owns the default page-size policy for that resource. Strategy-specific configuration is explicit rather than inferred from a datasource implementation.

### Adapter capabilities

Pagination support is capability-aware. An adapter declares which pagination strategies it can execute. SQLAlchemy continues to support page-number pagination first; true limit/offset may be implemented in this slice if the adapter contract remains simple and fully tested. Cursor support must not be faked for adapters that cannot provide a stable cursor contract.

Resource composition/compilation fails closed when a resource explicitly requests a pagination strategy unsupported by the selected data-source capability profile at the point where both are known.

A generic `ResourceDefinition` may exist before an adapter is selected; therefore adapter compatibility validation belongs to composition/capability negotiation, not to the standalone model constructor.

### Result metadata

Strategy-specific result metadata must be explicit enough for Web/REST presentation:

- page pagination: current page, per-page, previous/next, optional total count;
- limit/offset: offset/limit, previous/next navigation metadata, optional total count;
- cursor: opaque previous/next cursor(s) as supported, no fabricated total page numbers.

Prefer a typed pagination-result metadata union over adding many unrelated nullable fields to the existing `PageResult`. Existing page-number properties should remain available through compatibility helpers/properties where practical.

### Admin presentation

Admin Web adapts to strategy:

- page strategy: numbered pagination when exact count is known, otherwise Previous/Next;
- limit/offset: Previous/Next style navigation, never fake page numbers unless a real page mapping exists;
- cursor: Previous/Next based on returned cursors, never total-pages UI.

UI-05D must not add client-side cursor state as the only source of truth; navigation remains encoded in GET URLs.

If no shipping adapter can satisfy cursor execution without inventing unstable ordering/encoding during implementation, UI-05D ships the typed cursor request/result capability contract plus fail-closed capability negotiation, but does not claim cursor execution support for SQLAlchemy or any other adapter.

## Compiler and validation rules

Compilation/configuration must reject:

- duplicate resource filter IDs;
- blank filter IDs or labels;
- a generated API resource-filter reference that does not exist;
- generated API operators not supported by the referenced filter;
- malformed built-in choices;
- invalid page-size policies;
- requested pagination strategies unsupported by the selected data-source adapter where capability information is available at composition time.

Runtime request parsing follows surface contracts:

- generated REST: strict, fail closed, 400 on unapproved/invalid query input;
- Admin Web: tolerant canonicalization, dropping malformed/unapproved query fragments without ever widening policy.

## Compatibility and migration

UI-05D is intentionally additive-first.

The following existing Web configuration must continue to work:

```python
ResourceFieldPolicy(filter_fields=("status", "total"))
```

The following existing generated API configuration must continue to work:

```python
ResourceApiDefinition(
    filters=(
        ApiFilterDefinition(
            name="status",
            field="status",
            operators=(FilterOperator.EQ,),
        ),
    ),
)
```

Compatibility is implemented by normalization into the new compiled filter contract, not by maintaining permanently separate execution paths.

Existing generated REST URLs remain valid.

Existing resource Web filter URLs remain valid for legacy synthesized filters.

No migration silently exposes a Web-only filter to generated REST.

Existing page-number query construction remains the default and keeps current safety bounds.

## Public API and facade

New core filter and pagination configuration types that developers are expected to use must be exported through the appropriate Rakit public facade, not require imports from private implementation modules.

Expected public families include the filter definitions/choices, page-size policy, canonical page-pagination type, and any resource pagination configuration type required by normal application code.

Public names must be covered by facade/import tests. Internal compiled-normalization types such as `ResolvedFilterSelection` should remain internal unless a concrete public extension need requires exposing them.

## Testing strategy

The implementation follows the project's normal quality gates and adds focused coverage in these areas.

### Core

- built-in filter-definition validation and input coercion;
- custom filter resolution;
- resolved selection preserves semantic identity plus flattened predicates;
- duplicate/blank filter IDs;
- explicit filter overriding same-ID legacy synthesis;
- legacy `filter_fields` normalization;
- API filter-ID resolution and fail-closed unknown IDs;
- backward compatibility for direct `ApiFilterDefinition`;
- page-size policy validation;
- page/limit-offset/cursor query-model construction;
- capability negotiation for pagination strategy where applicable.

### Generated REST

- existing filter syntax remains valid;
- resource filter IDs resolve through the shared definition;
- semantic custom filter values resolve correctly;
- Web-only filters remain rejected;
- invalid operators/values remain rejected;
- invalid page size is rejected;
- existing direct API filter definitions continue to work.

### Admin Web

- Django-style choice/boolean/custom filter presentation;
- typed operator controls for text/number/date filters;
- active-chip labels use originating selection metadata;
- clear/remove links serialize original semantic selections, not flattened predicates;
- malformed/unapproved filters disappear from canonical state;
- legacy filter-builder compatibility;
- sort icons for sortable inactive/ascending/descending columns;
- non-sortable columns have no affordance;
- configurable page-size selector and single-choice suppression;
- invalid page size falls back to configured default;
- page/cursor/offset reset semantics on filter/search/sort/page-size changes;
- strategy-appropriate pagination presentation;
- SSR and HTMX paths produce equivalent authoritative state.

### Adapter / SQLAlchemy

- resolved predicates continue to translate through existing filter translation;
- page-number behavior remains unchanged;
- any newly supported pagination strategy is covered by contract tests;
- unsupported strategy fails explicitly rather than producing approximate behavior.

### Quality gates

Before completion:

```text
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest -n auto --cov
uv run mkdocs build --strict
uv run python scripts/check_artifacts.py
git diff --check
```

Generated Tailwind CSS must be rebuilt through the existing `bun run css:build` pipeline whenever source CSS/templates introduce new utilities. Generated CSS must never be edited manually.

## Implementation sequencing

The implementation plan should be split into coherent checkpoints:

1. core unified filter contracts, resolved-selection normalization, and legacy compatibility;
2. generated API compilation/runtime reuse with explicit filter-ID exposure;
3. Admin Web filter parsing/state/presentation and Django-style UI;
4. sorting affordance polish;
5. page-size policy;
6. pagination strategy core/capability foundation and adapter support that is safe to include now;
7. showcase/docs/public facade updates;
8. focused tests, full verification, and final diff review.

Cursor adapter execution is conditional only on an existing adapter being able to satisfy a stable cursor contract without invented semantics. The typed capability foundation itself is part of UI-05D.

## Acceptance criteria

UI-05D is complete when:

- one resource filter definition can drive both Admin Web and generated REST;
- API exposure is explicitly allowlisted and Web-only filters cannot leak externally;
- semantic filter origin survives resolution so Web chips/links remain correct even when one selection maps to multiple predicates;
- legacy Web and generated-API filter definitions remain compatible;
- Admin filtering feels like a named Django-admin-style filter system rather than a raw query builder for explicitly defined filters;
- active filters remain readable/removable and progressive enhancement remains intact;
- sortable inactive columns visibly advertise sortability;
- rows-per-page is resource-configurable with safe defaults and surface-appropriate invalid-input behavior;
- pagination strategy types and capability boundaries are explicit and existing page-number behavior is preserved;
- unsupported pagination behavior fails closed rather than being simulated;
- focused and full verification are green;
- PR #21 remains draft until the user completes browser visual acceptance and explicitly approves merge.
