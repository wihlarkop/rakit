# UI-06 Polish, Built-in CRUD, and Bulk Delete Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the reported UI-06 browser bugs and align resource CRUD/bulk defaults with the Django Admin mental model without weakening Rakit's existing mutation/action security pipeline.

**Architecture:** Keep CRUD as resource-generated routes driven by capabilities/permissions. Add one framework-owned bulk delete surface alongside compiled custom BULK actions, reuse the existing secure delete mutation service, and keep dialogs/popovers/select-all as progressive enhancement over server-rendered no-JS behavior.

**Tech Stack:** Python 3.12+, Starlette, Jinja2, native HTML `<dialog>`/`<details>`, small vanilla JS, Tailwind-based Rakit semantic tokens, pytest/ruff/ty.

**Spec:** `docs/superpowers/specs/2026-08-19-ui-06-polish-crud-bulk-design.md`

## Global Constraints

- `main` is never changed by this plan.
- Feature/source changes first, non-test review second, regression tests last.
- CRUD stays framework-generated and capability/permission-gated; custom actions stay user-registered.
- Built-in bulk default is only Delete selected.
- No-JavaScript paths remain functional.
- Existing CSRF, authorization, idempotency, confirmation, concurrency, mutation hook, and transaction contracts remain authoritative.
- Django-like ergonomic `ResourceAdmin` lifecycle overrides are deferred.

---

### Task 1: Theme and shared popover polish

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/templates/components/theme_control.html`
- Modify: `packages/rakit-web/src/rakit_web/templates/base.html`
- Modify: `packages/rakit-web/src/rakit_web/templates/components/admin_navigation.html`
- Modify: `packages/rakit-web/src/rakit_web/templates/components/actions.html`
- Modify: `packages/rakit-web/src/rakit_web/templates/resources/_table.html`
- Modify: `packages/rakit-web/src/rakit_web/static/theme.js`
- Modify: `packages/rakit-web/src/rakit_web/static/rakit-ui.js`

**Produces:** explicit up/down theme-menu placement and one shared click-away/Escape marker for action overflow menus.

- [ ] Add a `theme_menu_placement` template variable with `up` default for sidebar and `down` for auth/system shell.
- [ ] Ensure selecting a theme closes the menu and returns focus with `preventScroll`, avoiding the reported jump toward the page top.
- [ ] Mark action and bulk overflow menu bodies with `.rakit-popover` so the existing detail-popover close logic handles click-away/Escape.
- [ ] Review no-JS `<details>` behavior manually in template source before tests.

### Task 2: Stable select chevron presentation

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/assets/rakit.css`
- Modify: templates that render `.rakit-select` where a wrapper is required.
- Regenerate: `packages/rakit-web/src/rakit_web/static/rakit.css`

**Produces:** consistent right-side spacing and chevron placement independent of browser native-arrow quirks.

- [ ] Change `.rakit-select` to reserve explicit icon space and suppress the browser arrow only where the framework wrapper supplies a semantic chevron.
- [ ] Add a reusable select wrapper/icon pattern and apply it to filter operator selects and generated form selects without changing form names/values.
- [ ] Rebuild committed CSS and review dark/light token behavior.

### Task 3: Page-local select all

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/templates/resources/_table.html`
- Modify: `packages/rakit-web/src/rakit_web/static/rakit-ui.js`

**Produces:** a Gmail/Django-style header checkbox for all selectable rows on the currently rendered page.

- [ ] Render a header checkbox when bulk controls exist.
- [ ] Add explicit data attributes for header and row selectors.
- [ ] Enhance the form so header click checks/unchecks current-page rows, row changes update header checked/indeterminate state, and the selected count stays synchronized.
- [ ] Keep every row checkbox a normal named `selected` control for no-JS submission.

### Task 4: Built-in Delete selected semantics

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/admin.py`
- Modify: `packages/rakit-web/src/rakit_web/bulk_admin.py`
- Modify/create focused web adapter module only if needed to keep `bulk_admin.py` bounded.
- Modify: `packages/rakit-web/src/rakit_web/templates/resources/_table.html`
- Modify: `packages/rakit-web/src/rakit_web/templates/actions/bulk.html`

**Consumes:** compiled resource CRUD capability/permission state and existing `WriteMutationService.delete()` / confirmation-token pipeline.

**Produces:** framework-owned Delete selected launcher when delete is genuinely available, while custom compiled BULK actions remain additive.

- [ ] Resolve delete capability and exact compiled delete permission for each resource; do not infer from UI state alone.
- [ ] Expose a built-in Delete selected launcher independently from user `ActionDefinition` registration.
- [ ] Execute deletion through the existing authorized mutation service and operation/UoW seam; do not implement direct datasource deletion in the web layer.
- [ ] Preserve per-record identity validation and fail closed when a selected record is missing/unauthorized.
- [ ] Keep custom BULK actions untouched and additive.

### Task 5: Styled bulk feedback and dialog enhancement

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/bulk_review.py`
- Modify: `packages/rakit-web/src/rakit_web/action_routes.py` only if a shared renderer extraction is required.
- Modify: `packages/rakit-web/src/rakit_web/templates/actions/bulk.html`
- Modify/create: a small shared bulk feedback partial if needed.
- Modify: `packages/rakit-web/src/rakit_web/static/rakit-ui.js`

**Produces:** styled full-page no-JS bulk errors plus modal review/confirmation enhancement when JS is available.

- [ ] Replace empty-selection/generic bulk GET rejection with a template-backed Rakit feedback surface carrying the same HTTP status.
- [ ] Preserve 403/404 non-disclosure rules and existing availability semantics.
- [ ] Add an opt-in dialog enhancement for bulk GET review without changing the canonical GET/POST URLs.
- [ ] Ensure Cancel closes the enhanced dialog when appropriate and remains a normal owner-page link without JS.
- [ ] Ensure submit still posts the exact hidden CSRF/submission/selection/concurrency/confirmation values produced by the server.

### Task 6: Non-test review and regression tests last

**Files:**
- Add/modify focused tests under `packages/rakit-web/tests/` only after Tasks 1-5 source is complete.

- [ ] Review the final diff for accidental custom-action defaults, direct delete bypasses, JS-only mutation paths, mount-path regressions, or helper/debug artifacts.
- [ ] Add regression tests for theme placement/focus contract, popover markers, select presentation, header select-all markup, built-in Delete selected gating, custom BULK coexistence, styled empty-selection feedback, and no-JS form transport.
- [ ] Run `ruff format --check .`, `ruff check .`, `ty check`, focused tests, then the full pytest suite.
- [ ] Open a PR only to `ui-06-advanced-operations`, require fresh CI, and leave final browser acceptance to the maintainer before any UI-06 -> main PR.
