# UI-07A Responsive and Overflow Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every completed framework-owned Rakit Web surface intentionally usable at desktop, tablet, and mobile widths without changing operation semantics.

**Architecture:** Harden layout through existing Jinja/Tailwind structure, keeping data tables as contained horizontal-scroll regions and adapting control groups rather than shrinking typography indiscriminately. JavaScript changes are allowed only when an existing responsive control needs progressive-enhancement behavior that CSS/HTML cannot provide.

**Tech Stack:** Jinja2, Tailwind CSS v4, HTMX, lightweight vanilla JS, pytest, Bun.

**Spec:** `docs/superpowers/specs/2026-08-19-ui-07-ui-08-phase-a-hardening-design.md`

## Global Constraints

- Source implementation first, structural/non-test review second, regression tests last.
- No semantic accessibility redesign owned by UI-07B unless a responsive defect makes markup unusable.
- No new product capabilities or runtime security behavior.
- Target widths: approximately 1440, 1024, 768, and 390 CSS px.
- No accidental document-level horizontal scrolling.
- Wide data tables may scroll inside their own bounded region.
- Rebuild committed static CSS after any maintainer CSS change.

---

### Task 1: Harden Shell and Navigation Layout

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/templates/base.html`
- Modify: `packages/rakit-web/src/rakit_web/templates/components/admin_navigation.html`
- Modify: `packages/rakit-web/src/rakit_web/templates/components/admin_mobile_navigation.html`
- Modify if needed: `packages/rakit-web/src/rakit_web/assets/rakit.css`
- Regenerate if CSS changes: `packages/rakit-web/src/rakit_web/static/rakit.css`

**Interfaces:**
- Consumes: existing app/auth/system shell modes and mobile `<dialog>` navigation.
- Produces: stable page gutters, header behavior, bounded navigation, and no shell-level overflow at all target widths.

- [ ] **Step 1: Inspect source for width assumptions and overflow leaks**

Review `min-width`, fixed widths, sticky regions, truncated labels, header action clusters, and shell wrappers. Record only concrete defects that can affect the four target widths.

- [ ] **Step 2: Implement shell/navigation layout fixes**

Use responsive utility changes that preserve desktop sidebar behavior and the existing mobile drawer. Keep the mobile navigation width bounded by viewport space and keep long application titles truncatable without pushing the close/theme controls offscreen.

- [ ] **Step 3: Perform structural review before tests**

Confirm there is still one `main`, desktop navigation stays desktop-only, mobile dialog stays mobile-only, noscript navigation remains available, and no new absolute/fixed element can expand document width.

- [ ] **Step 4: Add regression contract coverage last**

Create `packages/rakit-web/tests/test_responsive_layout_contracts.py` with source/HTML assertions for the stable hooks and bounded-width classes required to prevent shell/mobile-nav regressions. Assert the mobile dialog remains viewport-bounded and the main content wrapper stays `min-w-0`.

- [ ] **Step 5: Run focused tests**

```powershell
uv run pytest packages/rakit-web/tests/test_responsive_layout_contracts.py packages/rakit-web/tests/test_accessibility_contracts.py -q
```

---

### Task 2: Harden Dashboard, Page Heading, Detail, and Form Layouts

**Files:**
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/dashboard/index.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/dashboard/_widget.html`
- Modify: `packages/rakit-web/src/rakit_web/templates/resources/list.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/resources/detail.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/forms/form.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/forms/delete_confirm.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/components/actions.html`

**Interfaces:**
- Consumes: existing heading/action hierarchy and form/detail primitives.
- Produces: action groups that wrap predictably, long titles/metadata that do not overflow, and forms/details that remain readable at 390 px.

- [ ] **Step 1: Implement responsive heading/action changes**

Ensure page-level heading/action areas use mobile-first vertical stacking and only switch to horizontal layout when there is enough room. Keep primary actions visible without forcing horizontal page scroll.

- [ ] **Step 2: Harden detail and form content**

Ensure long identifiers, file names, URLs, help text, validation messages, and field groups wrap or break safely. Preserve readable control sizing; do not solve overflow by reducing body text below the established design scale.

- [ ] **Step 3: Structural review**

Confirm action order remains primary/default/danger as established in UI-06 and form field/error associations are untouched.

- [ ] **Step 4: Extend responsive regression tests last**

Add assertions to `test_responsive_layout_contracts.py` for mobile-first heading/action stacking, safe long-value wrapping hooks/classes, and form/detail wrappers.

- [ ] **Step 5: Run focused tests**

```powershell
uv run pytest packages/rakit-web/tests/test_responsive_layout_contracts.py packages/rakit-web/tests/test_resource_detail_form_ui_maturity.py packages/rakit-web/tests/test_advanced_ui_maturity.py -q
```

---

### Task 3: Harden Resource Controls, Table, Filters, Bulk, and Pagination

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/templates/resources/_table.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/resources/_filters.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/static/rakit-ui.js`

**Interfaces:**
- Consumes: existing responsive filter fallback/drawer, resource table, bulk form, select-all behavior, and pagination model.
- Produces: contained table overflow, usable search/filter/bulk controls, and pagination that wraps rather than expanding the page.

- [ ] **Step 1: Implement resource-control wrapping and width constraints**

Keep search at full mobile width, keep filter controls reachable, prevent total-count/bulk helper copy from colliding with action buttons, and allow pagination controls to wrap naturally.

- [ ] **Step 2: Harden table containment**

Keep the table inside its `overflow-x-auto` region and prevent cell content from expanding ancestor layout. Long cell values must wrap/truncate according to existing presentation intent without changing underlying values.

- [ ] **Step 3: Inspect filter drawer/fallback at narrow widths**

Keep the drawer viewport-bounded and the no-JS `<details>` fallback usable. Do not replace the fallback with a JS-only path.

- [ ] **Step 4: Structural review**

Confirm GET search/sort/filter semantics, bulk submission semantics, current-page select-all scope, and pagination URLs are unchanged.

- [ ] **Step 5: Add regression tests last**

Extend `test_responsive_layout_contracts.py` with table-container, filter-drawer, bulk-control, and pagination-wrap contracts. Reuse stable `data-rakit-*` hooks where available rather than snapshotting full HTML.

- [ ] **Step 6: Run focused behavior tests**

```powershell
uv run pytest packages/rakit-web/tests/test_responsive_layout_contracts.py packages/rakit-web/tests/test_bulk_list_ui.py packages/rakit-web/tests/test_ui06_polish_crud_bulk.py -q
```

---

### Task 4: Harden Actions, Dialogs, Relationships, Uploads, Auth/System, and Custom Pages

**Files:**
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/actions/_form.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/actions/_confirm.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/actions/_bulk_review_content.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/actions/_bulk_delete_content.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/actions/_bulk_feedback_content.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/relationships/panel.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/relationships/to_one.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/relationships/to_many.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/relationships/inline_rows.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/relationships/options.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/relationships/preview_dialog.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/auth/login.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/system/page.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/pages/page.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/pages/rejected.html`
- Modify if shared dialog sizing needs it: `packages/rakit-web/src/rakit_web/assets/rakit.css`

**Interfaces:**
- Consumes: UI-06 modal/relationship/upload/auth/custom-page presentation.
- Produces: narrow-screen-safe operation flows without changing authorization or mutation behavior.

- [ ] **Step 1: Implement narrow dialog/content constraints**

Ensure framework dialogs keep viewport gutters, internal max-height/overflow, and centered presentation without exceeding narrow viewports. Mobile filter/navigation drawers remain drawers rather than inheriting centered dialog geometry.

- [ ] **Step 2: Harden relationship and upload layouts**

Allow relationship row controls, candidate selectors, reorder controls, file metadata, and policy text to wrap or stack without hiding critical operations.

- [ ] **Step 3: Harden auth/system/custom pages**

Ensure login controls, theme control, system messages, safe payload tables/mappings, and page actions remain usable at mobile width.

- [ ] **Step 4: Structural review**

Confirm all operation URLs/methods, confirmation tokens, CSRF/submission tokens, relationship mutation fields, and raw custom-page payload compatibility are unchanged.

- [ ] **Step 5: Add regression contracts last**

Extend `test_responsive_layout_contracts.py` for dialog viewport constraints and representative relationship/auth/page wrappers.

- [ ] **Step 6: Run focused tests**

```powershell
uv run pytest packages/rakit-web/tests/test_responsive_layout_contracts.py packages/rakit-web/tests/test_relationship_upload_ui_maturity.py packages/rakit-web/tests/test_auth_ui_maturity.py packages/rakit-web/tests/test_custom_page_ui_maturity.py -q
```

---

### Task 5: Rebuild Assets and Run Full UI-07A Gate

**Files:** generated CSS if source CSS changed; no new product scope.

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: CI-ready UI-07A child head.

- [ ] **Step 1: Rebuild CSS**

```powershell
bun run css:build
```

- [ ] **Step 2: Verify JavaScript syntax when JS changed**

Use the repository's available JS syntax/build check; at minimum ensure the modified static script parses successfully in the same way previous UI slices verified it.

- [ ] **Step 3: Run formatting, lint, and types**

```powershell
uv run ruff format --check .
uv run ruff check .
uv run ty check
```

- [ ] **Step 4: Run full repository tests**

```powershell
uv run pytest
uv run pytest --cov
```

- [ ] **Step 5: Run docs/artifact checks**

```powershell
uv run mkdocs build --strict
uv run python scripts/check_artifacts.py
```

- [ ] **Step 6: Inspect final child diff**

Confirm only responsive/overflow source, generated CSS, and regression-test changes are present. No UI-07B/07C semantics/copy redesign or unrelated refactor should be included.

- [ ] **Step 7: Open child PR and require fresh full GitHub CI before merge to epic**
