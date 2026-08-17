# UI-05B Resource List Experience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mature Rakit resource browsing into a compact server-authoritative workflow for search, generic filters, active filter chips, sorting, table scanning, selection, count-aware pagination, page size, and empty/no-results states.

**Architecture:** Keep `ResourceQuery`, field whitelists, sorting rules, count policy, and data-source semantics authoritative in Python. Add narrow presentation helpers in `resource_routes.py` only where validated state must be normalized for templates. Jinja renders the complete GET-first experience; HTMX is optional progressive enhancement. Feature work precedes visual review, then focused tests are added/finalized at the end.

**Tech Stack:** Python 3.12+, Starlette, Jinja2, HTMX, Tailwind CSS v4, Lucide icons, pytest, Ruff, ty.

## Global Constraints

- Start only after UI-05A has merged into `ui-05-resource-experience`.
- Feature branch: `ui-05b-resource-list-experience`.
- Merge destination: `ui-05-resource-experience`, never `main` directly.
- Preserve existing `ResourceQuery`, `FilterOperator`, `CountPolicy`, sort whitelist, search whitelist, filter whitelist, identity encoding, and bulk-selection semantics.
- Validated state flows `raw query -> parser/whitelist -> ResourceQuery -> presentation`.
- Do not introduce a second query parser in Jinja or JavaScript.
- Search remains normal GET; Enter submits; no standalone Search button.
- Filters use an expandable panel below the toolbar, not a modal/popover.
- Active filter chips render validated filters only.
- Sorting remains table-header driven; no separate sort dropdown.
- Search/filter/sort/page-size changes reset page to 1 while preserving unrelated validated state.
- Built-in page-size UI choices are 25, 50, 100; valid custom `per_page` remains representable and must not be silently replaced.
- Exact/deferred/disabled count policies must be represented truthfully; do not invent total pages.
- Do not infer numeric/status/domain semantics from field names.
- Missing display values render as `—` when absence is safely distinguishable.
- Advanced bulk workflows remain UI-06.
- Feature first -> visual review -> tests at end -> full verification.

## File Structure

Runtime/presentation normalization:

- `packages/rakit-web/src/rakit_web/resource_routes.py` — validated filter display/removal URLs, query-preserving helpers, count/range/page metadata, page-size options, safe cell presentation metadata if needed.

Templates:

- `packages/rakit-web/src/rakit_web/templates/resources/list.html`
- `packages/rakit-web/src/rakit_web/templates/resources/_table.html`
- `packages/rakit-web/src/rakit_web/templates/resources/_count.html`
- `packages/rakit-web/src/rakit_web/templates/components/ui.html` only for truly reusable resource-list primitives.

Styling/assets:

- `packages/rakit-web/src/rakit_web/assets/rakit.css`
- generated `packages/rakit-web/src/rakit_web/static/rakit.css`
- `packages/rakit-web/src/rakit_web/static/rakit-ui.js` only if a small progressive enhancement is necessary; no client query model.

Showcase/tests:

- `examples/ui_showcase` deterministic list scenarios.
- Create `packages/rakit-web/tests/test_resource_list_ui_maturity.py`.
- Modify `tests/test_ui_showcase.py` only for new showcase contracts.
- Keep resource query/count/sort/bulk/accessibility suites green.

---

### Task 1: Add Validated Resource-List Presentation Metadata

**Files:**
- Modify `packages/rakit-web/src/rakit_web/resource_routes.py`

**Interfaces:**
- Consumes existing `ResourceQuery`, `_serialize_filter()`, `_validated_query_params()`, `_page_url()`, `_sort_headers()`, `OffsetPagination`, `CountPolicy`, and current `resource_list()` context.
- Produces template-ready dictionaries/lists derived only from validated query state.

- [ ] **Step 1: Inventory the current `resource_list()` template context and existing tests before changing helper names.**

Record current keys including `rows`, `fields`, `sort_headers`, `search_enabled`, `search_value`, `filter_values`, `per_page_value`, `pagination`, `count_url`, `resource_path`, `page`, and `query`. Preserve keys relied on by existing templates/tests unless the implementation updates both atomically.

- [ ] **Step 2: Add a single query-preservation helper for GET controls.**

Use validated query state plus explicit sorting to build reusable parameter tuples. Support controlled inclusion/exclusion of filters/search/sort/per_page/count policy and never copy raw `request.query_params` wholesale.

- [ ] **Step 3: Add validated filter presentation models.**

For each `query.filters` item expose at minimum: serialized value, field, operator token, human-readable operator label, display value, and a removal URL that removes only that validated filter instance while preserving search/sort/per_page/count policy and omitting page.

Human labels should be a fixed mapping over existing `FilterOperator` values. Do not invent operators or infer field type.

- [ ] **Step 4: Add clear-filter and clear-search URLs.**

`Clear all filters` preserves search/sort/per_page/count policy. `Clear search` preserves filters/sort/per_page/count policy. Both reset page by omitting it.

- [ ] **Step 5: Add filter-builder metadata.**

Expose approved filter field names and the existing supported operator vocabulary with fixed human-readable labels. For `is_null`, expose presentation choices equivalent to true/false without changing serialization semantics. `in` remains generic comma-separated input.

- [ ] **Step 6: Add truthful pagination metadata.**

For exact count, derive total pages, visible record range, numbered page items with bounded ellipsis, and Previous/Next URLs using validated params. For deferred/disabled count, expose current page + Previous/Next only and never fabricate last/numbered pages.

- [ ] **Step 7: Add page-size option metadata.**

Always expose 25/50/100. If the current valid `query.pagination.per_page` is not one of those values, prepend/include that custom value as selected. Generate GET-preservation fields/params without page.

- [ ] **Step 8: Normalize safe missing cell presentation.**

When a rendered field value is `None`, expose display `—`. Keep the raw object/value untouched. Do not coerce empty string, zero, or false into missing.

- [ ] **Step 9: Commit runtime presentation helpers.**

```powershell
git add packages/rakit-web/src/rakit_web/resource_routes.py
git commit -m "feat(web): add validated resource list presentation state"
```

---

### Task 2: Build Search, Filter Panel, and Active Filter Chips

**Files:**
- Modify `packages/rakit-web/src/rakit_web/templates/resources/list.html`
- Modify `packages/rakit-web/src/rakit_web/templates/resources/_table.html`
- Modify `packages/rakit-web/src/rakit_web/assets/rakit.css` only for reusable list/filter primitives

**Interfaces:**
- Consumes Task 1 validated template metadata.
- Produces GET-first search/filter controls; no JavaScript is required for correctness.

- [ ] **Step 1: Keep breadcrumb and one resource `<h1>`, then place built-in primary CRUD action only if an existing safe create route/capability is already present in template context.**

If no such context exists in UI-05B, do not fabricate the route; leave create-action integration to UI-05C/runtime inspection.

- [ ] **Step 2: Replace search row with search-first toolbar.**

Use Lucide `search` inside/adjacent to the control, one `type="search"` input, preserved hidden validated state, and no standalone Search button. Submit on Enter through native GET.

- [ ] **Step 3: Add Filters toggle/control.**

Use a secondary button labeled `Filters` plus validated active count. The filter panel sits below the toolbar. Prefer native `<details>`/`<summary>` or a small progressive-enhancement toggle that remains usable without JS; if using JS, retain semantic expanded/control attributes.

- [ ] **Step 4: Render generic filter builder.**

Controls: field selector, condition selector, value input/choice, Apply filter. Build a server-compatible GET representation that serializes into the existing repeatable `filter=<field>:<operator>:<value>` contract. If a small server-side normalization endpoint/form handler is required, keep it on the same resource GET route and fail closed to allowed fields/operators.

- [ ] **Step 5: Render validated active filter chips.**

Each chip contains human-readable field/operator/value and a remove link with an accessible name. `Clear all filters` is separate and does not clear search.

- [ ] **Step 6: Add search clear affordance when search is active.**

Use the validated clear-search URL from Task 1.

- [ ] **Step 7: Commit search/filter feature work.**

```powershell
git add packages/rakit-web/src/rakit_web/templates/resources/list.html packages/rakit-web/src/rakit_web/templates/resources/_table.html packages/rakit-web/src/rakit_web/assets/rakit.css packages/rakit-web/src/rakit_web/resource_routes.py
git commit -m "feat(web): add resource search and filter experience"
```

---

### Task 3: Mature Table, Sorting, and Selection Presentation

**Files:**
- Modify `packages/rakit-web/src/rakit_web/templates/resources/_table.html`
- Modify `packages/rakit-web/src/rakit_web/assets/rakit.css`
- Modify `packages/rakit-web/src/rakit_web/resource_routes.py` only if safe cell metadata needs refinement

- [ ] **Step 1: Convert table shell/header/cells to semantic Rakit tokens.**

Keep intentional horizontal overflow. Remove direct blue/slate role styling from modified resource table markup when semantic equivalents exist.

- [ ] **Step 2: Refine sortable headers.**

Keep existing form/button sort submissions and `aria-sort`. Add restrained Lucide sort direction icons based on server-provided `aria_sort`; do not construct sort state in JS.

- [ ] **Step 3: Preserve row identity link behavior.**

Only the first meaningful/detail-linked cell becomes a link. Do not make the whole row clickable.

- [ ] **Step 4: Render `—` for safe missing values.**

Use Task 1 normalized display value. Long values may wrap where practical; identifiers may remain nowrap when needed for table scanning.

- [ ] **Step 5: Refine bulk selection presentation without changing workflow.**

Use `.rakit-checkbox`, keep per-row accessible label, preserve `name="selected"` and encoded identity value, provide restrained selected-count context only through existing bulk enhancement/runtime mechanisms. Do not redesign confirmation/results.

- [ ] **Step 6: Keep domain status as plain text unless explicit semantic metadata exists.**

No auto-status badges from field names/strings.

- [ ] **Step 7: Commit table feature work.**

```powershell
git add packages/rakit-web/src/rakit_web/templates/resources/_table.html packages/rakit-web/src/rakit_web/assets/rakit.css packages/rakit-web/src/rakit_web/resource_routes.py
git commit -m "style(web): mature resource table scanning and sorting"
```

---

### Task 4: Implement Empty/No-Results and Count-Aware Pagination

**Files:**
- Modify `packages/rakit-web/src/rakit_web/templates/resources/_table.html`
- Modify `packages/rakit-web/src/rakit_web/templates/resources/_count.html`
- Modify `packages/rakit-web/src/rakit_web/templates/components/ui.html` only if pagination primitive requires a backward-compatible extension
- Modify `packages/rakit-web/src/rakit_web/assets/rakit.css`

- [ ] **Step 1: Distinguish true empty from no matching records.**

True empty requires no rows and no validated search/filters. No-results requires no rows with active validated search and/or filters. Use distinct copy and clear-state affordances. Do not invent Create if capability/context is unavailable.

- [ ] **Step 2: Render exact-count range and numbered pagination.**

Use server-derived pagination items. Current page uses `aria-current="page"`; ellipsis is non-interactive; Previous/Next explicit disabled/available semantics reuse UI-04 pagination primitives.

- [ ] **Step 3: Render deferred-count state truthfully.**

Keep `Calculating total…` server/HTMX count fragment behavior. Until total is known, show current page + Previous/Next only.

- [ ] **Step 4: Render disabled-count state truthfully.**

Show total unavailable/unknown plus current page + Previous/Next only.

- [ ] **Step 5: Add page-size GET control.**

Render selected custom value if needed plus 25/50/100. Changing selection submits a native GET form preserving validated search/filters/sort/count policy while omitting page.

- [ ] **Step 6: Keep mobile baseline usable.**

Toolbar stacks, table scrolls horizontally, pagination wraps/simplifies, and page-size remains reachable. UI-07 will do systematic hardening later.

- [ ] **Step 7: Commit pagination/empty-state feature work.**

```powershell
git add packages/rakit-web/src/rakit_web/templates/resources packages/rakit-web/src/rakit_web/templates/components/ui.html packages/rakit-web/src/rakit_web/assets/rakit.css packages/rakit-web/src/rakit_web/resource_routes.py
git commit -m "feat(web): add truthful resource pagination and empty states"
```

---

### Task 5: Expand Deterministic Resource-List Showcase and Visual QA

**Files:**
- Modify `examples/ui_showcase` data/resource definitions only through public APIs

- [ ] **Step 1: Ensure showcase data supports many rows, missing optional values, long values, sortable/filterable/searchable fields, and bulk identities.**

- [ ] **Step 2: Exercise URLs/states for active search, one filter, multiple filters, no matches, true empty resource, exact middle/last pages, and custom per-page when publicly supported.**

- [ ] **Step 3: Exercise deferred/disabled count only if the public resource API already exposes those policies in the showcase without private hooks.**

- [ ] **Step 4: Build Tailwind CSS and visually inspect light/dark + narrow layouts.**

```powershell
bun run css:build
uv run python -m examples.ui_showcase.main
```

- [ ] **Step 5: Fix source defects and rebuild until accepted.**

- [ ] **Step 6: Commit showcase and generated CSS.**

```powershell
git add examples/ui_showcase packages/rakit-web/src/rakit_web/static/rakit.css
git commit -m "build(web): finalize resource list visual states"
```

---

### Task 6: Add Focused Resource-List Tests After Feature Completion

**Files:**
- Create `packages/rakit-web/tests/test_resource_list_ui_maturity.py`
- Modify existing resource route/query tests only when a new presentation helper needs direct unit coverage
- Modify `tests/test_ui_showcase.py` as needed

- [ ] **Step 1: Test search semantics and preservation.**

Assert no standalone Search button, labeled search input, validated filter/sort/per_page/count preservation, and page reset.

- [ ] **Step 2: Test filter panel and validated chips.**

Assert allowed field/operator controls, validated active count, human labels, remove-one URL, clear-all-filter URL, clear-search URL, and no raw invalid filter reflected as active trusted state.

- [ ] **Step 3: Test sorting/header semantics.**

Assert `aria-sort`, sort value preservation, page reset, and no domain guessing.

- [ ] **Step 4: Test table/missing/selection semantics.**

Assert `—` only for `None`, detail link behavior, labeled checkboxes, and absence of whole-row click semantics.

- [ ] **Step 5: Test page-size behavior.**

Assert default/current metadata, 25/50/100, valid custom value visibility, preservation of unrelated validated state, and page reset.

- [ ] **Step 6: Test exact/deferred/disabled count presentation.**

Assert numbered pages only for truthful exact totals; deferred/disabled do not fabricate total pages.

- [ ] **Step 7: Test true-empty vs no-results copy/affordances.**

- [ ] **Step 8: Run focused package tests.**

```powershell
uv run pytest `
  packages/rakit-web/tests/test_resource_list_ui_maturity.py `
  packages/rakit-web/tests/test_bulk_list_ui.py `
  packages/rakit-web/tests/test_accessibility_contracts.py `
  packages/rakit-web/tests/test_pages.py `
  -q
```

Run existing resource query/count/sort suites discovered during implementation in the same package test phase.

- [ ] **Step 9: Run showcase tests separately if needed.**

```powershell
uv run pytest tests/test_ui_showcase.py -q
```

- [ ] **Step 10: Commit tests.**

```powershell
git add packages/rakit-web/tests tests/test_ui_showcase.py
git commit -m "test(web): cover resource list experience contracts"
```

---

### Task 7: Final Verification and Integration PR

- [ ] **Step 1: Run quality gates.**

```powershell
uv run ruff format --check .
uv run ruff check .
uv run ty check
git diff --check
```

- [ ] **Step 2: Run full repository gate.**

```powershell
uv run pytest -n auto --cov
uv run mkdocs build --strict
uv run python scripts/check_artifacts.py
```

- [ ] **Step 3: Inspect diff specifically for raw-query trust, whitelist weakening, page-state loss, bulk changes, and accidental UI-06 work.**

- [ ] **Step 4: Open PR `ui-05b-resource-list-experience -> ui-05-resource-experience`.**

- [ ] **Step 5: Review and merge the slice into integration.**

This merge is pre-authorized. Do not merge integration to `main`.