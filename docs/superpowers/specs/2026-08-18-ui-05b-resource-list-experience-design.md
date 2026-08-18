# UI-05B Resource List Experience Design

## Status

Approved design for the second UI-05 slice.

This document supersedes the resource-list/search/filter/table/pagination portion of the original single-PR `UI-05 — Dashboard and Resource Experience` scope.

Approved sequence:

1. UI-05A Dashboard Experience
2. UI-05B Resource List Experience
3. UI-05C Resource Detail, Forms & Delete

UI-05B starts only after UI-05A has merged.

## Goal

Mature the highest-frequency Rakit resource browsing workflow into a compact, accessible, bookmarkable, server-authoritative experience for:

- resource heading/context;
- search;
- filters;
- active filter chips;
- sorting;
- table scanning;
- row selection presentation;
- exact/deferred/disabled count presentation;
- pagination;
- page-size selection;
- true-empty and no-match states.

The design must preserve the existing ResourceQuery contract, whitelist validation, sorting rules, bulk-selection behavior, and SSR-first architecture.

## Core Design Direction

Use a **search-first toolbar with an expandable filter panel**.

Do not use always-visible dense filter rows or per-column filter controls. Those approaches consume excessive vertical/horizontal space, become difficult on mobile, and encourage type-specific assumptions that the current resource metadata does not support safely.

The page hierarchy is:

1. breadcrumb;
2. resource heading/context plus built-in primary CRUD action when available;
3. search + filter trigger toolbar;
4. expanded filter builder when requested;
5. validated active filter chips;
6. count/selection context;
7. resource table;
8. count-aware pagination and page-size control.

## Security and Data-Flow Principle

Validated server state is authoritative.

The rendering flow is:

`untrusted query string -> existing parser/whitelists -> validated ResourceQuery -> presentation helpers/templates`

The UI must never derive trusted filter, sort, or capability state directly from raw request parameters when validated state is already available.

The following existing rules remain mandatory:

- filter fields are limited to `field_policy.filter_fields`;
- search exists only when search fields are exposed;
- sort fields are limited to `field_policy.sort_fields`;
- invalid/unapproved query state follows existing parser behavior;
- permission/capability checks remain upstream;
- bulk selection remains tied to rows with valid identities/detail URLs.

## Resource Heading

The page keeps one `<h1>` for the resource label, with breadcrumb and restrained supporting copy.

A built-in create action may appear in the heading area only when the existing resource/form runtime actually exposes create capability for the current user/resource. UI-05B must not fabricate a create route.

Domain actions remain UI-06.

## Search Contract

Search remains a normal GET operation against the resource list route.

Visual treatment:

- magnifier icon;
- one full-width/appropriate-width search input;
- no standalone `Search` button;
- Enter submits normally;
- optional clear affordance when search is active.

Search submission preserves validated:

- active filters;
- explicit sort;
- `per_page`;
- non-default count policy.

Search submission resets page to 1.

The no-JavaScript path must remain fully usable. HTMX may enhance the same GET path but must not become the source of truth.

## Filter Trigger

Filters use a dedicated button next to search.

Examples:

- `Filters`
- `Filters 2` when two validated filters are active.

The active-count badge counts filters only, not search.

The button must communicate expanded/collapsed state and control the filter panel semantically when enhancement is used.

The filter panel appears below the toolbar rather than in a dialog or narrow popover.

## Generic Filter Builder

The current Rakit resource metadata exposes filter fields and operators but does not yet provide a rich type-specific filter schema. UI-05B must therefore remain generic and capability-safe.

The baseline builder exposes:

- field selector;
- condition/operator selector;
- value control where the operator requires a value;
- Apply filter action.

Conceptual layout:

`Field [status]  Condition [equals]  Value [pending]  [Apply filter]`

The operator list must be derived from/support the existing `FilterOperator` contract rather than inventing a separate incompatible vocabulary.

### Operator Presentation

Human-readable labels may be used, but serialization remains the existing query contract:

`filter=<field>:<operator>:<value>`

Special cases:

- `is_null` should be presented as meaningful empty/not-empty choices rather than asking the user to type raw booleans where practical;
- `in` may use comma-separated generic input in this slice;
- type-aware date/number/enum controls require richer explicit schema/capabilities and are not inferred from field names.

Do not guess field types based on names such as `date`, `amount`, `status`, or `price`.

## Active Filter Chips

Only validated filters are rendered as active chips.

Each chip communicates field, human-readable operator, and value, for example:

- `Status equals pending ×`
- `Region in APAC, EMEA ×`

Removing one filter:

- removes only that filter instance;
- preserves search;
- preserves explicit sort;
- preserves `per_page`;
- preserves count policy;
- resets page to 1.

`Clear all filters` clears filters only. It does not silently clear search.

Search receives its own clear behavior.

## Sorting

Sorting remains table-header driven.

There is no separate sort dropdown in UI-05B.

Sortable headers:

- remain native form/button/link semantics compatible with existing GET behavior;
- keep `aria-sort` authoritative;
- may use restrained Lucide arrows/chevrons to improve scanning;
- preserve active search, filters, per-page value, and count policy;
- reset page to 1.

Existing multi-sort behavior must not be rewritten merely for presentation. If the current runtime preserves multiple explicit sorts, UI-05B continues to respect that contract.

## Table Structure

The table should be dense enough for operational work while retaining readable hit areas and spacing.

### Columns

- bulk-selection checkbox column: fixed compact width when applicable;
- normal text: left aligned;
- numeric values: right aligned only when safe presentation metadata/value typing makes this explicit;
- action affordance: right aligned;
- avoid excessive nowrap where long text should reasonably wrap.

UI-05B must not infer numeric/status semantics from field names.

### Record Link

The first meaningful rendered record cell may continue to link to detail when the row has a valid detail URL.

Do not make the entire `<tr>` clickable. Full-row click behavior conflicts with text selection, nested actions, bulk checkboxes, and keyboard/accessibility expectations.

### Missing Values

Missing display values should render as an em dash (`—`) rather than framework/runtime representations such as `None`, `null`, or an ambiguous empty cell where the view can safely distinguish absence.

This is presentation only and must not mutate stored/query values.

### Status Values

The framework must not automatically color a field because it is named `status`, nor map arbitrary domain strings such as `active`, `cancelled`, or `failed` to semantic colors without explicit presentation metadata.

Where no explicit semantic status contract exists, render the value as normal text.

The UI-04 `.rakit-status` primitive remains available for application/framework states that have explicit semantics.

## Row Selection and Bulk Boundary

UI-05B matures selection presentation only.

When bulk actions are available:

- checkboxes remain explicitly labeled per record;
- selected-count context should be visible when selection exists;
- selected rows may receive a restrained selected-state treatment;
- bulk controls already exposed by the runtime remain reachable.

UI-05B does not redesign bulk action confirmation, result handling, destructive grouping, selection policy, or advanced bulk workflows. Those remain UI-06.

## Empty State vs No Results

The table must distinguish two conditions.

### Truly Empty Resource

When there are no records and no active search/filters:

- heading/message such as `No orders yet`;
- supporting explanation;
- built-in create affordance only if create capability exists.

### No Matching Records

When validated search and/or filters are active but no records match:

- message such as `No matching orders`;
- guidance to change search/remove filters;
- clear search/filter affordance that preserves unrelated validated state where appropriate.

The previous generic `No records.` message is insufficient for both cases.

## Count Policies

Existing `CountPolicy` behavior remains authoritative.

### Exact Count

When total count is known, UI-05B may render:

- visible record range, e.g. `Showing 26–50 of 137`;
- numbered pagination when total pages can be computed correctly;
- Previous/Next;
- current page with `aria-current="page"`;
- non-interactive ellipsis.

### Deferred Count

While total is being resolved:

- communicate `Calculating total…` or equivalent;
- retain functional Previous/Next/current-page controls using information already available;
- do not fabricate a last page or numbered-page set before the total is known.

When the deferred count result is swapped in, the resulting count presentation must remain server-authored.

### Disabled Count

When total is unavailable by policy:

- explicitly state that total is unavailable/unknown;
- show current page and Previous/Next as supported;
- do not render fake numbered total-page navigation.

## Page Size

Built-in list UI defaults are locked to:

- default: 25;
- choices: 25, 50, 100.

Changing page size:

- preserves search;
- preserves validated filters;
- preserves explicit sorting;
- preserves count policy;
- resets page to 1.

Programmatic/custom `per_page` values remain supported. If a valid current resource query uses a custom value such as `17`, the UI must not silently replace it with 25. The page-size control may expose the current custom value alongside the standard 25/50/100 options.

## Pagination

Use the UI-04 pagination visual/semantic primitives where practical.

Desktop exact-count target:

- range/count on the left;
- Previous, numbered pages, ellipsis, Next;
- page-size control aligned to the right when space permits.

Mobile may simplify to Previous/current/Next plus a usable page-size control. Systematic responsive hardening remains UI-07, but the UI-05B baseline must be usable.

All generated links must preserve only validated query state.

## HTMX Enhancement

HTMX may enhance search/filter/sort/page/page-size interactions against the same server route and server-generated templates.

Requirements:

- normal GET remains first-class;
- URL/query state remains bookmarkable;
- no duplicate client-side filter/sort model;
- server response remains authoritative;
- loading/pending feedback reuses UI-04 primitives;
- focus/announcement behavior must not become worse than full navigation.

UI-05B may choose minimal enhancement instead of aggressive live-search behavior if debouncing/history/focus complexity would make the no-JS and server-authoritative contract harder to reason about.

## Runtime Changes

Unlike UI-05A, UI-05B is expected to require focused `resource_routes.py` presentation helpers because current templates do not have enough normalized data for rich filters/count-aware numbered pagination/query-preserving removal links.

Allowed runtime additions are narrowly presentation-oriented, such as:

- validated filter display models;
- validated filter removal/clear URLs;
- count-aware page/range metadata;
- page-size option metadata;
- query-preserving form/link helpers;
- safe cell presentation metadata when derivable from actual values/contracts.

Not allowed:

- changing filter authorization/whitelists;
- changing persistence/data-source query semantics;
- weakening invalid-query handling;
- creating a second query parser in templates/JS;
- guessing domain semantics from names.

## Expected Files

Primary:

- `packages/rakit-web/src/rakit_web/templates/resources/list.html`
- `packages/rakit-web/src/rakit_web/templates/resources/_table.html`
- `packages/rakit-web/src/rakit_web/templates/resources/_count.html`
- `packages/rakit-web/src/rakit_web/templates/components/ui.html` where shared list primitives need extension
- `packages/rakit-web/src/rakit_web/assets/rakit.css`
- generated static CSS
- `packages/rakit-web/src/rakit_web/resource_routes.py` for focused validated presentation data
- `examples/ui_showcase` for deterministic states

`rakit-ui.js` changes are optional and must remain progressive enhancement only.

## Accessibility

Must preserve/improve:

- one resource-page `<h1>`;
- labeled search;
- filter button expanded/control semantics;
- labeled field/operator/value controls;
- removable filters understandable without color alone;
- `aria-sort` on sortable columns;
- explicitly labeled row selection;
- `aria-current` on current page;
- disabled pagination semantics;
- keyboard-usable controls;
- visible focus;
- horizontal table overflow without hiding focusable controls.

## UI Showcase Acceptance

The deterministic showcase must exercise:

- many rows;
- active search;
- one active filter;
- multiple active filters;
- sortable columns and active sorting;
- selected rows when bulk is available;
- true empty resource;
- filtered/search no-results state;
- exact-count pagination;
- middle and last pages;
- deferred/disabled count presentation where publicly configurable;
- 25/50/100 page-size choices;
- a valid custom per-page value if the public API supports it;
- long cell values;
- missing optional values;
- light and dark themes.

## Testing Strategy

Per the approved workflow, implement the full UI-05B feature surface first, visually/manual-review it, then add/finalize tests.

Focused tests should cover stable contracts such as:

- search semantics and preservation;
- filter toggle/panel semantics;
- validated filter chips;
- remove/clear URLs;
- filter whitelist preservation;
- sort state and page reset;
- page-size 25/50/100 plus custom value;
- page-size page reset;
- exact/deferred/disabled count presentation;
- numbered pagination only when truthful;
- true-empty vs no-results messaging;
- row-selection labels;
- missing-value presentation;
- no accidental raw query rendering as trusted filter state.

Existing resource query, sorting, count, bulk-list, accessibility, and security behavior suites remain authoritative.

## Out of Scope

UI-05B does not redesign:

- dashboard;
- detail/create/edit/delete pages;
- domain record actions;
- advanced bulk flows;
- relationships;
- upload workflows;
- auth/session;
- custom pages;
- richer type-specific filter schema inference;
- release/publication behavior.

## Definition of Done

UI-05B is complete when:

- search/filter/sort/table/pagination form one coherent resource browsing workflow;
- all query links/forms preserve only validated state;
- standard page sizes are 25/50/100 without breaking valid custom values;
- exact/deferred/disabled count policies are represented truthfully;
- empty and no-results states are distinct;
- SSR/no-JS remains fully functional;
- showcase visual acceptance is approved;
- focused and existing regressions are green;
- Ruff, ty, diff check, full pytest/coverage, strict MkDocs, and artifact checks are green;
- the PR merges before UI-05C starts.
