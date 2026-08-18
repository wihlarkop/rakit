# UI-05B Resource List Experience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mature Rakit resource browsing into a compact server-authoritative workflow for search, generic filters, active filter chips, sorting, table scanning, selection, count-aware pagination, page size, and empty/no-results states.

**Architecture:** Keep `ResourceQuery`, `FilterOperator`, field whitelists, sorting rules, count policy, identity encoding, and data-source semantics authoritative in Python. `resource_routes.py` gains narrow validated presentation helpers and one explicit filter-builder normalization path. Jinja renders the complete GET-first experience; HTMX remains optional enhancement. Feature work is completed before the focused test phase.

**Tech Stack:** Python 3.12+, Starlette, Jinja2, HTMX, Tailwind CSS v4, server-rendered Lucide icons, pytest, Ruff, ty.

## Global Constraints

- Start only after UI-05A merges into `ui-05-resource-experience`.
- Feature branch: `ui-05b-resource-list-experience`.
- Merge destination: `ui-05-resource-experience`, not `main`.
- Preserve existing `ResourceQuery`, `FilterOperator`, `CountPolicy`, search/filter/sort whitelists, identity encoding, and bulk-selection semantics.
- Validated state flow remains: `raw GET -> parser/whitelist -> ResourceQuery -> presentation`.
- Never copy arbitrary raw `request.query_params` into trusted chips, sort links, pagination links, or hidden preserved state.
- Search remains native GET and has no standalone Search button.
- Filters use a panel below the toolbar, not a modal/popover.
- Sorting stays table-header driven.
- Search/filter/sort/page-size changes reset page to 1 by omitting `page` from the resulting URL.
- Built-in page-size choices are 25, 50, 100; a valid custom current `per_page` remains representable.
- Exact/deferred/disabled count policies are represented truthfully; numbered total-page navigation exists only when total is known.
- Do not infer numeric/status/domain semantics from field names.
- `None` may render as `—`; `""`, `0`, and `False` remain real values.
- Advanced bulk flows remain UI-06.
- Execution order: feature -> visual/manual review -> tests at end -> full verification.

## File Structure

- `packages/rakit-web/src/rakit_web/resource_routes.py` — validated query-preservation helpers, filter-builder normalization, filter display/removal state, pagination/range/page-size metadata, missing-value display normalization.
- `packages/rakit-web/src/rakit_web/templates/resources/list.html` — page heading and resource toolbar container.
- `packages/rakit-web/src/rakit_web/templates/resources/_table.html` — search/filter controls, chips, count/selection context, table, empty/no-results, pagination.
- `packages/rakit-web/src/rakit_web/templates/resources/_count.html` — deferred count fragment presentation.
- `packages/rakit-web/src/rakit_web/templates/components/ui.html` — extend only when a resource-list pattern is truly reusable.
- `packages/rakit-web/src/rakit_web/assets/rakit.css` — reusable list/filter/table primitives only.
- `packages/rakit-web/src/rakit_web/static/rakit.css` — generated with `bun run css:build`, never hand-edited.
- `packages/rakit-web/src/rakit_web/static/rakit-ui.js` — optional progressive enhancement only; no client query model.
- `examples/ui_showcase` — deterministic visual states.
- Create `packages/rakit-web/tests/test_resource_list_ui_maturity.py` in the final test phase.

---

### Task 1: Add Validated Query and Filter-Builder Presentation State

**Files:**
- Modify `packages/rakit-web/src/rakit_web/resource_routes.py`

**Interfaces:**
- Consumes existing `ResourceBinding.parse_query()`, `_parse_filters()`, `_serialize_filter()`, `_validated_query_params()`, `_page_url()`, `_sort_headers()`, `ResourceQuery`, `Filter`, `FilterOperator`, and `CountPolicy`.
- Produces validated template context and canonical GET URLs.

- [ ] **Step 1: Preserve the current canonical filter URL contract.**

Canonical URLs remain repeatable:

```text
filter=<field>:<operator>:<value>
```

Do not replace this contract with three permanent query parameters.

- [ ] **Step 2: Define filter-builder input names as a presentation-only GET alias.**

The filter panel submits:

```text
filter_field=<field>
filter_operator=<operator>
filter_value=<value>
```

These three parameters exist only to make a no-JavaScript HTML form possible. They are never treated as canonical query state.

- [ ] **Step 3: Add `_builder_filter(params: QueryParams, allowed_fields: set[str]) -> Filter | None`.**

Behavior:

- return `None` when all three builder inputs are absent;
- reject/ignore incomplete triples without creating a filter;
- field must be in `allowed_fields`;
- operator must be a real `FilterOperator`;
- `in` converts comma-separated non-empty values using the same semantics as canonical filters;
- `is_null` accepts only explicit `true`/`false` presentation values;
- other operators preserve the submitted string value;
- malformed `is_null` uses the same `RakitError(VALIDATION_FAILED, status_code=400)` discipline as canonical parsing.

Do not infer field type from the field name.

- [ ] **Step 4: Canonicalize builder submissions before listing data.**

At the start of `resource_list(request)`, when a valid builder filter exists:

1. parse the existing canonical query through the normal validated path;
2. append the validated builder filter to the validated filters;
3. preserve validated search, explicit sort, current `per_page`, and count policy;
4. omit `page` so the new filter starts on page 1;
5. generate a URL using canonical repeatable `filter=` parameters only;
6. return an HTTP redirect to that canonical resource URL.

After redirect, templates see only canonical validated query state. This avoids a second long-lived query vocabulary and works without JavaScript.

- [ ] **Step 5: Add one validated query-preservation helper.**

The helper must build parameter tuples from `ResourceQuery` plus validated explicit sorting and allow intentional omission of filters/search/sort/per_page/count policy/page. Never preserve raw request params wholesale.

- [ ] **Step 6: Add validated filter presentation models.**

For each `query.filters` item expose:

```text
field
operator token
human operator label
display value
serialized canonical value
remove_url
```

`remove_url` removes that one filter instance, preserves validated search/sort/per_page/count policy, and omits page.

Use a fixed human-readable label mapping over the existing `FilterOperator` enum. Do not add operators.

- [ ] **Step 7: Add `clear_filters_url` and `clear_search_url`.**

- clear filters: preserve search/sort/per_page/count policy;
- clear search: preserve filters/sort/per_page/count policy;
- both omit page.

- [ ] **Step 8: Expose generic filter-builder metadata.**

Provide allowed field names and existing operator tokens/labels. `is_null` is presented with meaningful true/false choices; `in` remains comma-separated generic input.

- [ ] **Step 9: Add page-size metadata.**

Always include 25/50/100. When the current valid `per_page` is not one of these, include that custom current value as selected instead of silently changing it.

- [ ] **Step 10: Add truthful exact-count pagination metadata.**

When `CountPolicy.EXACT` and total count is available, derive:

- first visible record index;
- last visible record index;
- total pages;
- bounded numbered page items with non-interactive ellipsis;
- Previous/Next canonical URLs.

For deferred/disabled count, do not create total-page items.

- [ ] **Step 11: Normalize cell display for `None` only.**

Keep stored/raw values untouched; provide `—` only as presentation.

- [ ] **Step 12: Commit runtime presentation work.**

```powershell
git add packages/rakit-web/src/rakit_web/resource_routes.py
git commit -m "feat(web): add validated resource list presentation state"
```

---

### Task 2: Build Search, Filter Panel, and Active Filter Chips

**Files:**
- Modify `packages/rakit-web/src/rakit_web/templates/resources/list.html`
- Modify `packages/rakit-web/src/rakit_web/templates/resources/_table.html`
- Modify `packages/rakit-web/src/rakit_web/assets/rakit.css` only for reusable primitives

- [ ] **Step 1: Keep breadcrumb and exactly one resource `<h1>`.**

Do not fabricate a Create route if the current context does not safely expose one; built-in CRUD route integration is completed in UI-05C.

- [ ] **Step 2: Replace the current search form with a search-first toolbar.**

Use Lucide `search`, one labeled `type="search"` input, preserved validated hidden state, and no standalone Search button. Native Enter submits GET.

- [ ] **Step 3: Add a Filters control and panel.**

Use a semantic `<details>`/`<summary>` baseline so the panel works without JavaScript. Label shows `Filters` plus validated active count. The panel sits below the toolbar.

- [ ] **Step 4: Render the builder form using the exact alias names from Task 1.**

```text
filter_field
filter_operator
filter_value
```

Preserve canonical existing `filter` values, validated search, explicit sort, per-page, and count policy as hidden fields. Omit page. Apply submits a normal GET; Task 1 canonicalizes it to canonical `filter=` URLs.

- [ ] **Step 5: Render active filter chips from validated presentation models only.**

Each chip displays field/operator/value and has a clear accessible removal link. Add `Clear all filters` separately; it does not clear search.

- [ ] **Step 6: Add an active-search clear affordance using `clear_search_url`.**

- [ ] **Step 7: Commit toolbar/filter feature work.**

```powershell
git add `
  packages/rakit-web/src/rakit_web/resource_routes.py `
  packages/rakit-web/src/rakit_web/templates/resources/list.html `
  packages/rakit-web/src/rakit_web/templates/resources/_table.html `
  packages/rakit-web/src/rakit_web/assets/rakit.css
git commit -m "feat(web): add resource search and filter experience"
```

---

### Task 3: Mature Table, Sorting, and Selection Presentation

**Files:**
- Modify `packages/rakit-web/src/rakit_web/templates/resources/_table.html`
- Modify `packages/rakit-web/src/rakit_web/assets/rakit.css`

- [ ] **Step 1: Migrate table shell/header/cell styling to semantic Rakit tokens.**

Keep intentional horizontal overflow and compact operational density.

- [ ] **Step 2: Refine sortable headers without changing sort semantics.**

Keep existing GET form/button behavior and `aria-sort`. Use restrained Lucide direction icons based only on server-provided `aria_sort`.

- [ ] **Step 3: Keep only the first meaningful/detail cell linked.**

Do not make the whole row clickable.

- [ ] **Step 4: Render Task 1 display values, including `None -> —`.**

Allow reasonable wrapping for long content; do not convert arbitrary values to status badges.

- [ ] **Step 5: Mature bulk-selection presentation only.**

Use `.rakit-checkbox`, preserve `name="selected"`, encoded identity value, and per-row accessible label. Existing bulk action behavior remains authoritative; advanced workflow presentation stays UI-06.

- [ ] **Step 6: Commit table feature work.**

```powershell
git add packages/rakit-web/src/rakit_web/templates/resources/_table.html packages/rakit-web/src/rakit_web/assets/rakit.css
git commit -m "style(web): mature resource table scanning and sorting"
```

---

### Task 4: Add Empty/No-Results and Count-Aware Pagination

**Files:**
- Modify `packages/rakit-web/src/rakit_web/templates/resources/_table.html`
- Modify `packages/rakit-web/src/rakit_web/templates/resources/_count.html`
- Modify `packages/rakit-web/src/rakit_web/templates/components/ui.html` only for backward-compatible pagination extension
- Modify `packages/rakit-web/src/rakit_web/assets/rakit.css`

- [ ] **Step 1: Distinguish true empty from no matching rows.**

True empty = no rows and no validated search/filters. No-results = no rows with validated search and/or filters. Use distinct copy and clear-state affordances.

- [ ] **Step 2: Render exact-count range and numbered pages.**

Use server-derived page items only. Current page uses `aria-current="page"`; ellipsis is non-interactive; disabled/available Previous/Next semantics reuse UI-04 pagination primitives.

- [ ] **Step 3: Keep deferred count honest.**

Preserve the existing deferred count HTMX fragment. Until total is known, show current page + Previous/Next only and `Calculating total…`.

- [ ] **Step 4: Keep disabled count honest.**

Show total unavailable/unknown and current page + Previous/Next only.

- [ ] **Step 5: Add native GET page-size control.**

Render custom current value when needed plus 25/50/100. Preserve validated search/filters/sort/count policy and omit page.

- [ ] **Step 6: Keep narrow layouts usable.**

Toolbar stacks, table scrolls, pagination wraps/simplifies, page-size remains reachable.

- [ ] **Step 7: Commit pagination/empty feature work.**

```powershell
git add `
  packages/rakit-web/src/rakit_web/templates/resources/_table.html `
  packages/rakit-web/src/rakit_web/templates/resources/_count.html `
  packages/rakit-web/src/rakit_web/templates/components/ui.html `
  packages/rakit-web/src/rakit_web/assets/rakit.css
git commit -m "feat(web): add truthful resource pagination and empty states"
```

---

### Task 5: Expand Showcase and Perform Visual Acceptance

**Files:**
- Modify `examples/ui_showcase` through public APIs only
- Regenerate `packages/rakit-web/src/rakit_web/static/rakit.css`

- [ ] **Step 1:** Ensure deterministic data covers many rows, missing optional values, long values, searchable/filterable/sortable fields, and valid bulk identities.
- [ ] **Step 2:** Exercise active search, one filter, multiple filters, no matches, true empty, middle/last exact pages, and custom per-page when publicly supported.
- [ ] **Step 3:** Exercise deferred/disabled count only if public showcase configuration supports it without private hooks.
- [ ] **Step 4:** Build and run.

```powershell
bun run css:build
uv run python -m examples.ui_showcase.main
```

- [ ] **Step 5:** Inspect light/dark and narrow layouts; fix source defects and rebuild until accepted.
- [ ] **Step 6:** Commit showcase/generated CSS.

```powershell
git add examples/ui_showcase packages/rakit-web/src/rakit_web/static/rakit.css
git commit -m "build(web): finalize resource list visual states"
```

---

### Task 6: Add Focused Tests After Feature Completion

**Files:**
- Create `packages/rakit-web/tests/test_resource_list_ui_maturity.py`
- Modify existing resource route/query tests only when new helpers need direct coverage
- Modify `tests/test_ui_showcase.py` as needed

- [ ] **Step 1:** Test builder alias validation and canonical redirect: allowed field/operator succeeds; disallowed/incomplete/malformed state cannot become a trusted active filter; canonical URL contains `filter=` and no `filter_field/filter_operator/filter_value`.
- [ ] **Step 2:** Test search preservation/page reset and absence of a standalone Search button.
- [ ] **Step 3:** Test validated chips, remove-one URL, clear-all-filter URL, and clear-search URL.
- [ ] **Step 4:** Test sorting/`aria-sort` preservation and page reset.
- [ ] **Step 5:** Test `None -> —` without changing `""`, `0`, or `False`; test detail links and labeled bulk checkboxes.
- [ ] **Step 6:** Test 25/50/100 plus valid custom page-size behavior and page reset.
- [ ] **Step 7:** Test exact/deferred/disabled count presentation and numbered pages only when truthful.
- [ ] **Step 8:** Test true-empty vs no-results messaging.
- [ ] **Step 9:** Run focused package regressions.

```powershell
uv run pytest `
  packages/rakit-web/tests/test_resource_list_ui_maturity.py `
  packages/rakit-web/tests/test_bulk_list_ui.py `
  packages/rakit-web/tests/test_accessibility_contracts.py `
  -q
```

Also run the existing resource route/query/count/sort suites discovered in the package.

- [ ] **Step 10:** Run showcase tests separately if fixture isolation requires it.

```powershell
uv run pytest tests/test_ui_showcase.py -q
```

- [ ] **Step 11:** Commit tests.

```powershell
git add packages/rakit-web/tests/test_resource_list_ui_maturity.py tests/test_ui_showcase.py
git commit -m "test(web): cover resource list experience contracts"
```

---

### Task 7: Final Verification and Integration Merge

- [ ] **Step 1:** Run static gates.

```powershell
uv run ruff format --check .
uv run ruff check .
uv run ty check
git diff --check
```

- [ ] **Step 2:** Run full repository gate.

```powershell
uv run pytest -n auto --cov
uv run mkdocs build --strict
uv run python scripts/check_artifacts.py
```

- [ ] **Step 3:** Review for raw-query trust, whitelist weakening, page-state loss, bulk behavior changes, and UI-06 scope creep.
- [ ] **Step 4:** Open PR `ui-05b-resource-list-experience -> ui-05-resource-experience`.
- [ ] **Step 5:** Review and merge the slice into integration. This merge is pre-authorized; do not merge integration to `main`.