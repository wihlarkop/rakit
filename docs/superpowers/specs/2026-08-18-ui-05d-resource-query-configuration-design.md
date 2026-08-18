# UI-05D Resource Query Configuration — Design

Date: 2026-08-18
Status: approved design, implementation pending
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
8. Improve Admin Web filter UX toward Django Admin: named filter groups, direct choices where appropriate, readable active-filter chips, and no requirement for users to understand arbitrary backend operators.
9. Make sortable columns visibly sortable even before they are selected.
10. Make rows-per-page policy configurable per resource while retaining the existing 25/50/100 behavior by default.
11. Establish explicit pagination strategy types without forcing every adapter to support every strategy.
12. Preserve normal GET navigation and HTMX progressive enhancement.

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

### 2. Built-in filter types

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

`DateRangeFilter` may resolve one logical filter selection to two predicates, for example `created_at >= start` and `created_at <= end`.

### 3. Custom filters

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
        return ()
```

Custom filter resolution stays backend-neutral. If a future custom filter needs OR/nested expressions, that belongs to a later predicate-expression capability rather than being smuggled into adapter-specific callbacks now.

### 4. Resource ownership of filter definitions

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
- `label` derived from the field name;
- current `FilterOperator` behavior;
- the same canonical execution through `Filter`.

This compatibility path prevents UI-05D from forcing every existing resource to migrate immediately. New documentation should favor first-class resource filters.

### 5. Generated API exposure

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

For backwards compatibility, existing direct `ApiFilterDefinition(...)` values remain accepted during this migration. The generated compiler normalizes both forms into one compiled API-filter contract. Unknown resource filter IDs fail compilation; they must never silently become arbitrary field filters.

A resource can therefore contain:

```text
resource filter     Admin Web     Generated REST
status              yes           yes
internal_risk       yes           no
```

This is a hard security boundary.

### 6. Generated REST query syntax

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

Unknown filter IDs, unapproved operators, duplicated singleton inputs, or invalid values remain 400-class validation errors.

### 7. Admin Web filter experience

The resource list moves away from a generic “field + arbitrary operator + arbitrary text” interaction as the primary UX.

The Filters control opens a panel containing named filter groups. Presentation depends on filter definition:

- `ChoiceFilter`: direct choices, similar to Django Admin;
- `BooleanFilter`: All / Yes / No style choices;
- text/number/date filters: compact typed input plus only the operators allowed by that definition;
- date range: start/end controls;
- custom filters with choices: direct semantic choices.

The existing generic legacy filter builder remains available only for synthesized legacy field filters so current resource behavior is not lost.

Active filters continue to render as removable chips and Clear all remains available.

Canonical resource-list URLs remain server-owned GET query state. HTMX is an enhancement only.

The Web transport may keep its current repeatable canonical `filter=...` representation for backwards compatibility in UI-05D. The important change is that parsing resolves through registered filter IDs rather than treating all user-submitted field names/operators as inherently valid. If a future URL syntax migration is desired, it must be separately specified.

### 8. Query-state serialization

Web query-state helpers must preserve only state that survived validation against the resource definition. Search, sort, filter, count policy, and page-size changes must continue to reset navigation to the first page where appropriate.

Filter presentation must retain enough metadata to show the filter label and human choice label rather than exposing internal field/operator details when the definition is semantic.

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

Clicking a sortable column preserves validated filters/search/page-size and resets page to 1.

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
- user-submitted Web/API `per_page` values must obey the resource page-size policy once one is configured, rather than silently widening it.

Changing page size resets to page 1.

## Pagination strategy foundation

UI-05D establishes explicit pagination strategy types without requiring every adapter to support every type immediately.

### Compatibility naming

The existing `OffsetPagination(page, per_page)` is semantically page-number pagination. Breaking all callers solely to fix the name is not acceptable.

The design therefore introduces:

- `PagePagination(page, per_page)` as the canonical page-number model;
- existing `OffsetPagination` retained as a compatibility alias/deprecated public name for page-number pagination;
- `LimitOffsetPagination(offset, limit)` for true offset/limit pagination;
- `CursorPagination(cursor, limit)` for opaque cursor pagination.

`ResourceQuery.pagination` becomes a discriminated union of supported pagination request models.

### Adapter capabilities

Pagination support is capability-aware. An adapter declares which pagination strategies it can execute. SQLAlchemy continues to support page-number pagination first; support for true limit/offset is straightforward and may be included if implemented cleanly. Cursor support must not be faked for adapters that cannot provide a stable cursor contract.

Resource compilation/configuration fails closed when a resource requests a pagination strategy unsupported by its data-source capability profile.

### Result metadata

`PageResult` evolves without breaking existing page-number consumers. Strategy-specific result metadata must be explicit enough for Web/REST presentation:

- page pagination: current page, per-page, previous/next, optional total count;
- limit/offset: offset/limit, previous/next offsets or equivalent navigation metadata, optional total count;
- cursor: opaque previous/next cursor(s) as supported, no fabricated total page numbers.

The implementation may introduce sibling result models or a typed pagination-result metadata union if that keeps `PageResult` clearer than overloading many nullable fields.

### Admin presentation

Admin Web adapts to strategy:

- page strategy: numbered pagination when exact count is known, otherwise Previous/Next;
- limit/offset: Previous/Next style navigation, never fake page numbers unless a real page mapping exists;
- cursor: Previous/Next based on returned cursors, never total-pages UI.

UI-05D must not add client-side cursor state as the only source of truth; navigation remains encoded in GET URLs.

## Compiler and validation rules

Compilation/configuration must reject:

- duplicate resource filter IDs;
- blank filter IDs or labels;
- a generated API resource-filter reference that does not exist;
- generated API operators not supported by the referenced filter;
- malformed built-in choices;
- invalid page-size policies;
- requested pagination strategies unsupported by the selected data-source adapter where capability information is available at composition/compile time.

Runtime request parsing rejects or safely ignores only according to the existing surface contract. Generated REST remains strict/fail-closed with 400 errors for unapproved inputs. Admin Web may preserve its current tolerant behavior for malformed legacy query fragments, but must never widen allowed fields/operators because of malformed state.

## Compatibility and migration

UI-05D is intentionally additive-first.

The following existing code must continue to work:

```python
ResourceFieldPolicy(filter_fields=("status", "total"))
```

and:

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

## Public API and facade

New core filter and pagination configuration types that developers are expected to use must be exported through the appropriate Rakit public facade, not require imports from private implementation modules.

Public names should be covered by facade/import tests.

The implementation should avoid prematurely exporting internal compiled-normalization types.

## Testing strategy

The implementation follows the project's normal quality gates and adds focused coverage in these areas.

### Core

- built-in filter-definition validation;
- custom filter resolution;
- duplicate/blank filter IDs;
- legacy `filter_fields` normalization;
- API filter-ID resolution and fail-closed unknown IDs;
- backward compatibility for direct `ApiFilterDefinition`;
- page-size policy validation;
- page/limit-offset/cursor query model construction;
- capability negotiation for pagination strategy where applicable.

### Generated REST

- existing filter syntax remains valid;
- resource filter IDs resolve through the shared definition;
- semantic custom filter values resolve correctly;
- unexposed Web filters remain rejected;
- invalid operators/values remain rejected;
- existing direct API filter definitions continue to work.

### Admin Web

- Django-style choice/boolean/custom filter presentation;
- typed operator controls for text/number/date filters;
- active-chip labels use presentation metadata;
- clear/remove links preserve only validated state;
- legacy filter builder compatibility;
- sort icons for sortable inactive/ascending/descending columns;
- non-sortable columns have no affordance;
- configurable page-size selector and single-choice suppression;
- page reset on filter/search/sort/page-size changes;
- strategy-appropriate pagination presentation;
- SSR and HTMX paths produce equivalent authoritative state.

### Adapter / SQLAlchemy

- resolved filters continue to translate through existing filter translation;
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

1. core unified filter contracts and compatibility normalization;
2. generated API compilation/runtime reuse;
3. Admin Web filter parsing/presentation and Django-style UI;
4. sorting affordance polish;
5. page-size policy;
6. pagination strategy core/capability foundation and adapter support that is safe to include now;
7. showcase/docs/public facade updates;
8. focused tests, full verification, and final diff review.

If cursor pagination would require inventing an adapter-specific cursor encoding or unstable ordering semantics during implementation, UI-05D must stop at the typed capability foundation and leave that adapter implementation for a later capability-specific slice. The public model must not claim working cursor execution where no adapter can satisfy the contract.

## Acceptance criteria

UI-05D is complete when:

- one resource filter definition can drive both Admin Web and generated REST;
- API exposure is explicitly allowlisted and Web-only filters cannot leak externally;
- legacy Web and generated-API filter definitions remain compatible;
- Admin filtering feels like a named Django-admin-style filter system rather than a raw query builder for explicitly defined filters;
- active filters remain readable/removable and progressive enhancement remains intact;
- sortable inactive columns visibly advertise sortability;
- rows-per-page is resource-configurable with safe defaults;
- pagination strategy types and capability boundaries are explicit and existing page-number behavior is preserved;
- unsupported pagination behavior fails closed rather than being simulated;
- focused and full verification are green;
- PR #21 remains draft until the user completes browser visual acceptance and explicitly approves merge.
