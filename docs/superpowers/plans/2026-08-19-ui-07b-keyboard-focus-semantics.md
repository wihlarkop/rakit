# UI-07B Keyboard, Focus, and Semantics Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Rakit's framework-owned UI consistently operable by keyboard with visible, logical focus behavior and semantic markup matching the real interaction model.

**Architecture:** Preserve native HTML semantics wherever possible, using JavaScript only for progressive-enhancement responsibilities such as focus restoration, popover dismissal, dialog lifecycle, and select-all synchronization. Existing operation/security behavior stays authoritative; this slice changes interaction presentation and semantic contracts only.

**Tech Stack:** Jinja2, native HTML controls/dialog, vanilla JS, HTMX, Tailwind CSS v4, pytest.

**Spec:** `docs/superpowers/specs/2026-08-19-ui-07-ui-08-phase-a-hardening-design.md`

## Global Constraints

- Branch from the epic head after UI-07A merge.
- Source implementation first, structural/non-test review second, regression tests last.
- Preserve no-JS critical-operation paths.
- Prefer native button/link/input/dialog semantics over custom keyboard emulation.
- Do not change auth, authorization, CSRF, mutation, idempotency, or concurrency behavior.
- Do not add Playwright/axe infrastructure.

---

### Task 1: Harden Landmarks, Skip Link, and Global Focus Entry

**Files:**
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/base.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/components/admin_navigation.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/components/admin_mobile_navigation.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/static/rakit-shell.js`
- Modify as needed: `packages/rakit-web/src/rakit_web/static/rakit-ui.js`

**Interfaces:**
- Consumes: existing `#rakit-main-content`, skip link, shell navigation, live announcer, and focus helpers.
- Produces: predictable first-entry keyboard behavior and unambiguous landmarks.

- [ ] **Step 1: Implement any required global focus/landmark corrections**

Keep one main landmark. Ensure the skip link moves focus to `#rakit-main-content` without scrolling unrelated containers. Preserve desktop/mobile primary-navigation labels and avoid duplicate landmark ambiguity on the same rendered state.

- [ ] **Step 2: Review focus lifecycle source**

Inspect existing `rakitFocusTarget`, shell navigation open/close, and dialog return-focus behavior. Remove or adjust only behavior that can move focus unexpectedly, hide focus, or scroll an unrelated container.

- [ ] **Step 3: Structural review**

Confirm skip-link target exists on auth/system/app shells, navigation fallback remains available without JS, and no duplicate `id` or `aria-controls` target is introduced.

- [ ] **Step 4: Extend accessibility tests last**

Update `packages/rakit-web/tests/test_accessibility_contracts.py` to verify the representative shell variants contain the skip target, one main landmark, labeled navigation, and unique IDs.

- [ ] **Step 5: Run focused tests**

```powershell
uv run pytest packages/rakit-web/tests/test_accessibility_contracts.py -q
```

---

### Task 2: Harden Dialog, Popover, Theme, and Return-Focus Contracts

**Files:**
- Modify as needed: `packages/rakit-web/src/rakit_web/static/rakit-ui.js`
- Modify as needed: `packages/rakit-web/src/rakit_web/static/rakit-shell.js`
- Modify as needed: `packages/rakit-web/src/rakit_web/static/theme.js`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/components/theme_control.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/components/actions.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/actions/_confirm.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/relationships/preview_dialog.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/resources/_table.html`

**Interfaces:**
- Consumes: native `<dialog>`, `.rakit-popover`, existing `data-rakit-dialog-*` hooks, theme menu, action/bulk menus.
- Produces: Escape/click-away behavior where appropriate and consistent focus restoration to the opener.

- [ ] **Step 1: Normalize opener tracking and close behavior**

Keep native modal focus trapping. Ensure generic dialogs, bulk dialogs, relationship preview dialogs, mobile navigation, and supported popovers record a meaningful opener and return focus when closing/cancelling.

- [ ] **Step 2: Normalize Escape and click-away semantics**

Use Escape for dismissible overlays. Backdrop/click-away closes only surfaces whose existing contract already allows dismissal; destructive confirmation must not silently execute or lose state.

- [ ] **Step 3: Keep theme selection focus-stable**

Preserve `preventScroll` behavior so selecting System/Light/Dark does not move the page/sidebar unexpectedly. Theme controls remain actual buttons/inputs with accessible text.

- [ ] **Step 4: Structural review**

Confirm dialogs remain native dialogs, popover controls remain keyboard-native, no custom tabindex loop is introduced, and every icon-only close/menu trigger has an accessible name.

- [ ] **Step 5: Add keyboard/focus regression contracts last**

Create `packages/rakit-web/tests/test_keyboard_focus_contracts.py`. Assert source hooks for opener tracking, focus return, Escape handlers, and `preventScroll`; render representative pages to assert accessible names and valid `aria-controls` targets.

- [ ] **Step 6: Run focused tests**

```powershell
uv run pytest packages/rakit-web/tests/test_keyboard_focus_contracts.py packages/rakit-web/tests/test_accessibility_contracts.py packages/rakit-web/tests/test_dialog_positioning_contract.py -q
```

---

### Task 3: Harden Search, Filters, Sorting, Selection, Bulk, and Pagination Semantics

**Files:**
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/resources/_table.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/resources/_filters.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/static/rakit-ui.js`

**Interfaces:**
- Consumes: GET search/filter/sort, current-page select-all, bulk form, pagination.
- Produces: clear accessible names, state communication, and native keyboard operation without changing query semantics.

- [ ] **Step 1: Verify and correct sorting semantics**

Keep `th scope="col"`, `aria-sort`, and native submit buttons. The label must state the field and current sorted state when applicable.

- [ ] **Step 2: Verify selection semantics**

Keep contextual row checkbox names and the current-page select-all label. Ensure the selection count is exposed as meaningful text and select-all indeterminate state remains presentation-only rather than changing submitted identities.

- [ ] **Step 3: Verify filter/search semantics**

Search retains `role="search"`; filter triggers and drawers have explicit names/controls; clear-search/clear-filter controls remain keyboard-native.

- [ ] **Step 4: Structural review**

Confirm query hidden inputs, GET methods, pagination rel/URLs, and selected-record values are unchanged.

- [ ] **Step 5: Extend regression tests last**

Add rendered assertions to `test_keyboard_focus_contracts.py` and `test_accessibility_contracts.py` for sortable headers, row/select-all names, bulk action grouping, filter trigger controls, and pagination navigation labels.

- [ ] **Step 6: Run authoritative behavior tests**

```powershell
uv run pytest packages/rakit-web/tests/test_keyboard_focus_contracts.py packages/rakit-web/tests/test_accessibility_contracts.py packages/rakit-web/tests/test_bulk_list_ui.py packages/rakit-web/tests/test_ui06_polish_crud_bulk.py -q
```

---

### Task 4: Harden Form Error, Action, Relationship, Upload, Auth, and Page Semantics

**Files:**
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/forms/form.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/actions/_form.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/actions/_confirm.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/actions/_bulk_feedback_content.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/relationships/panel.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/relationships/to_one.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/relationships/to_many.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/relationships/inline_rows.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/relationships/options.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/auth/login.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/pages/page.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/system/page.html`

**Interfaces:**
- Consumes: existing form error IDs/descriptions, action hierarchy, relationship mutation controls, file fields, auth/system/custom page rendering.
- Produces: explicit labels/descriptions/status semantics and stable focus targets.

- [ ] **Step 1: Harden form error linkage**

Every invalid field must remain programmatically associated with its help/error text through stable IDs and `aria-describedby`; the error summary links to focusable/meaningful field targets.

- [ ] **Step 2: Harden action/relationship accessible names**

Ambiguous labels such as bare `Remove`, `Move`, or icon-only controls must include enough accessible context to identify the target record/relationship row while keeping visible copy concise.

- [ ] **Step 3: Harden status meaning**

Success/warning/danger/info feedback includes visible textual meaning. Icons remain supplementary and decorative where text already conveys state.

- [ ] **Step 4: Structural review**

Confirm all forms retain correct methods, tokens, mutation fields, and confirmation behavior; custom templates still receive raw payload context.

- [ ] **Step 5: Extend semantic tests last**

Update `test_accessibility_contracts.py` and `test_keyboard_focus_contracts.py` with representative invalid form, relationship action, upload help/error, auth error, system page, and custom page assertions. Keep duplicate-ID checks on representative complex pages.

- [ ] **Step 6: Run focused tests**

```powershell
uv run pytest packages/rakit-web/tests/test_accessibility_contracts.py packages/rakit-web/tests/test_keyboard_focus_contracts.py packages/rakit-web/tests/test_relationship_upload_ui_maturity.py packages/rakit-web/tests/test_auth_ui_maturity.py packages/rakit-web/tests/test_custom_page_ui_maturity.py -q
```

---

### Task 5: Run Full UI-07B Gate

**Files:** generated CSS only if a focus-style CSS change was required.

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: CI-ready UI-07B child head.

- [ ] **Step 1: Rebuild CSS if maintainer CSS changed**

```powershell
bun run css:build
```

- [ ] **Step 2: Run JS syntax verification when static JS changed**

- [ ] **Step 3: Run format/lint/types**

```powershell
uv run ruff format --check .
uv run ruff check .
uv run ty check
```

- [ ] **Step 4: Run complete tests and coverage**

```powershell
uv run pytest
uv run pytest --cov
```

- [ ] **Step 5: Run docs/artifact checks**

```powershell
uv run mkdocs build --strict
uv run python scripts/check_artifacts.py
```

- [ ] **Step 6: Inspect final diff for scope discipline**

No new product capability, auth/security redesign, or UI-07C copy/theme work should be present unless required to preserve keyboard visibility.

- [ ] **Step 7: Open child PR and require fresh full GitHub CI before merge to epic**
