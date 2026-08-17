# UI-05C Resource Detail, Forms & Delete Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mature built-in record CRUD presentation across resource detail, create/edit forms, validation, and delete confirmation while preserving all authorization and write-pipeline guarantees.

**Architecture:** Keep existing detail/form/delete route behavior authoritative. Jinja/Tailwind own presentation; runtime changes are allowed only when a template lacks safe already-authorized context such as a CRUD URL or record label. Feature work is completed and visually reviewed first, then focused tests are added/finalized, followed by the full repository gate.

**Tech Stack:** Python 3.12+, Starlette, Jinja2, HTMX, Tailwind CSS v4, Lucide icons, pytest, Ruff, ty.

## Global Constraints

- Start only after UI-05B has merged into `ui-05-resource-experience`.
- Feature branch: `ui-05c-resource-detail-forms`.
- Merge destination: `ui-05-resource-experience`, not `main`.
- Built-in CRUD only: Create, Edit, Delete where current routes/capabilities expose them.
- Domain actions, relationships, advanced bulk, advanced upload workflows, auth/session, and custom pages remain UI-06.
- Preserve visible-detail-field-only title derivation from UI-03.
- Preserve field/detail policy; never inspect hidden fields for display convenience.
- Preserve CSRF, submission/idempotency, concurrency, delete, and confirmation tokens exactly.
- Preserve server validation and HTTP/security semantics.
- Do not create JavaScript-only create/edit/delete flows.
- Form layout definition remains authoritative; do not flatten it into a fixed form grid.
- Use UI-04 field/help/error/file/button/alert primitives where compatible.
- Missing safe display values use `—`; do not treat empty string, zero, or false as missing.
- Delete copy must match actual adapter/runtime semantics; do not claim permanent/irreversible deletion without evidence.
- Feature first -> visual review -> tests at end -> full verification.

## File Structure

Primary templates:

- `packages/rakit-web/src/rakit_web/templates/resources/detail.html`
- `packages/rakit-web/src/rakit_web/templates/forms/form.html`
- `packages/rakit-web/src/rakit_web/templates/forms/delete_confirm.html`
- `packages/rakit-web/src/rakit_web/templates/components/ui.html` only for backward-compatible shared primitives.

Styling/assets:

- `packages/rakit-web/src/rakit_web/assets/rakit.css`
- generated `packages/rakit-web/src/rakit_web/static/rakit.css`
- `packages/rakit-web/src/rakit_web/static/rakit-ui.js` only for small pending/focus enhancement if current server/HTMX mechanisms need it.

Runtime context, only when necessary:

- existing form/resource/write route modules discovered during implementation; add safe presentation context rather than parsing referrers/raw request data.

Showcase/tests:

- `examples/ui_showcase` CRUD states.
- Create `packages/rakit-web/tests/test_resource_detail_form_ui_maturity.py`.
- Modify `tests/test_ui_showcase.py` as needed.
- Preserve existing forms/write-pipeline/CSRF/idempotency/concurrency/delete/accessibility suites.

---

### Task 1: Mature Resource Detail Hierarchy and Built-In CRUD Affordances

**Files:**
- Modify `packages/rakit-web/src/rakit_web/templates/resources/detail.html`
- Modify focused runtime context only if safe edit/delete/create URLs are not already available
- Modify `packages/rakit-web/src/rakit_web/assets/rakit.css` only for reusable detail primitives

**Interfaces:**
- Consumes current `resource`, `fields`, `cells`, request/root-path context, and existing visible-field title heuristic.
- Produces one `<h1>`, record identity/context, semantic `<dl>`, missing-value presentation, and built-in CRUD actions only when safely available.

- [ ] **Step 1: Preserve the current visible-field-only `record_view` title/identity algorithm.**

Do not broaden lookup beyond `fields`/`cells` already supplied to the detail template.

- [ ] **Step 2: Refine breadcrumb and header hierarchy.**

Keep Dashboard -> resource -> visible record identity. Use semantic Rakit text roles and one entity-focused `<h1>`.

- [ ] **Step 3: Add built-in Edit/Delete affordances only from safe route/capability context.**

If the current detail route does not expose safe CRUD URLs/capabilities, inspect the existing form registration/route model and add a narrow presentation context helper in Python. Do not fabricate URLs from labels or assume every resource is writable.

- [ ] **Step 4: Mature the `<dl>` information layout.**

Use calm row dividers, stronger value hierarchy, responsive stacking, and wrapping for long values. Avoid card-per-field presentation.

- [ ] **Step 5: Render `—` for `None` values only.**

Do not replace valid falsy values.

- [ ] **Step 6: Commit detail feature work.**

```powershell
git add packages/rakit-web/src/rakit_web/templates/resources/detail.html packages/rakit-web/src/rakit_web/assets/rakit.css packages/rakit-web/src/rakit_web/*.py
git commit -m "style(web): mature resource detail workflow"
```

Stage only runtime Python files actually changed.

---

### Task 2: Mature Create/Edit Form Page and Field Presentation

**Files:**
- Modify `packages/rakit-web/src/rakit_web/templates/forms/form.html`
- Modify `packages/rakit-web/src/rakit_web/assets/rakit.css`
- Modify `packages/rakit-web/src/rakit_web/templates/components/ui.html` only if shared form primitives need backward-compatible extension

**Interfaces:**
- Consumes current `title`, `operation`, `layout`, `issues`, `summary_issues`, `action_url`, `csrf_token`, `submission_token`, `concurrency_token`, `has_file_fields`, and layout node objects.
- Produces the same POST forms and hidden fields with improved semantics/presentation.

- [ ] **Step 1: Add breadcrumb/context while preserving one `<h1>`.**

Use existing safe route/resource context only. If unavailable, keep a simpler operation context rather than guessing a parent URL.

- [ ] **Step 2: Convert direct old palette utilities to semantic Rakit roles in modified form markup.**

Use UI-04 field help/error/required/surface/button primitives. Avoid decorative backdrop blur/glass effects.

- [ ] **Step 3: Preserve recursive `render_node()` layout behavior.**

Do not change node kind meanings: field, section, row, column, tabs, collapsible, relationship, custom.

- [ ] **Step 4: Refine field rendering.**

Keep explicit `<label for>`. Build `aria-describedby` from description/error IDs exactly as current behavior. Preserve `aria-invalid`. Use `.rakit-file-input` for file fields and `.rakit-input`/other existing control classes for current supported field renderer types. Do not invent schema types from names.

- [ ] **Step 5: Add visible required indicator only from existing `field.required`.**

Include a visible marker plus screen-reader text; retain the actual `required` attribute where the runtime currently supplies it.

- [ ] **Step 6: Refine sections/rows/columns/tabs/collapsible styling.**

Sections may use semantic panels because the definition explicitly requests a section. Rows/columns are layout only. Tabs remain server-rendered/anchor accessible. Collapsible remains native `<details>`.

- [ ] **Step 7: Preserve relationship/custom placeholders untouched behaviorally.**

Advanced presentation remains UI-06.

- [ ] **Step 8: Commit form feature work.**

```powershell
git add packages/rakit-web/src/rakit_web/templates/forms/form.html packages/rakit-web/src/rakit_web/templates/components/ui.html packages/rakit-web/src/rakit_web/assets/rakit.css
git commit -m "style(web): mature create and edit form presentation"
```

---

### Task 3: Mature Validation Summary and Form Action Footer

**Files:**
- Modify `packages/rakit-web/src/rakit_web/templates/forms/form.html`
- Modify `packages/rakit-web/src/rakit_web/assets/rakit.css`
- Modify `packages/rakit-web/src/rakit_web/static/rakit-ui.js` only if needed for existing focus/pending hooks

- [ ] **Step 1: Convert validation summary to shared semantic danger/alert presentation.**

Retain `id="form-errors"`, `role="alert"`, `tabindex="-1"`, `data-rakit-focus-target="form-errors"`, summary links, and safe issue text.

- [ ] **Step 2: Keep field-level errors alongside summary.**

Do not remove duplicate contextual field messages; summary is navigation, field error is local explanation.

- [ ] **Step 3: Replace decorative sticky-footer styling with a solid semantic surface/border.**

Preserve sticky usability, Cancel secondary action, and primary Create/Save action. Ensure narrow stacking/touch usability and enough bottom spacing so fields are not obscured.

- [ ] **Step 4: Preserve hidden write-pipeline fields exactly.**

`csrf_token`, `submission_token`, and optional `concurrency_token` names/values remain unchanged.

- [ ] **Step 5: Add pending presentation only through existing HTMX/browser-safe enhancement.**

If the form is already HTMX-enhanced, use readable pending label + spinner + busy state without making submission JS-only. Do not treat UI disabling as the idempotency guarantee.

- [ ] **Step 6: Commit validation/footer feature work.**

```powershell
git add packages/rakit-web/src/rakit_web/templates/forms/form.html packages/rakit-web/src/rakit_web/assets/rakit.css packages/rakit-web/src/rakit_web/static/rakit-ui.js
git commit -m "style(web): refine form validation and submission hierarchy"
```

---

### Task 4: Build Explicit Delete Confirmation

**Files:**
- Modify `packages/rakit-web/src/rakit_web/templates/forms/delete_confirm.html`
- Modify the existing delete route/context module only if safe record/detail/list context is missing
- Modify `packages/rakit-web/src/rakit_web/assets/rakit.css` only if reusable destructive-decision styling is needed

**Interfaces:**
- Must preserve current form `action_url`, `csrf_token`, `submission_token`, `delete_token`, plus any existing concurrency/confirmation token present in route context.

- [ ] **Step 1: Inspect actual delete runtime/adapter semantics before choosing consequence copy.**

If the contract guarantees irreversible physical deletion, `This action cannot be undone` is allowed. If adapters may soft-delete/archive or semantics are generic, use truthful wording such as `Deleting this record may remove it from normal application views. Review this action before continuing.` Do not lie for visual clarity.

- [ ] **Step 2: Add breadcrumb/context only from safe server context.**

Never use untrusted `Referer` parsing as the authoritative cancel path.

- [ ] **Step 3: Add one destructive heading, explanatory consequence copy, and safe record identity/context when already authorized/available.**

Fallback to resource-singular/generic `record` wording if a safe record label is unavailable.

- [ ] **Step 4: Add visible Cancel and danger submit hierarchy.**

Cancel must work without JavaScript. Danger label should be explicit, e.g. `Delete order` or safe generic `Delete record`.

- [ ] **Step 5: Preserve all hidden integrity/security fields exactly.**

Never remove/rename `csrf_token`, `submission_token`, or `delete_token`; retain any existing additional token.

- [ ] **Step 6: Commit delete feature work.**

```powershell
git add packages/rakit-web/src/rakit_web/templates/forms/delete_confirm.html packages/rakit-web/src/rakit_web/assets/rakit.css packages/rakit-web/src/rakit_web/*.py
git commit -m "style(web): mature delete confirmation experience"
```

Stage only Python files actually changed.

---

### Task 5: Expand CRUD Showcase and Perform Visual Acceptance

**Files:**
- Modify `examples/ui_showcase` only through public Rakit APIs
- Regenerate `packages/rakit-web/src/rakit_web/static/rakit.css`

- [ ] **Step 1: Ensure deterministic detail cases include visible name+identity, fallback title, long values, and missing optional value.**

- [ ] **Step 2: Exercise create and edit forms with help/required states, multiple validation errors, file field, and a sufficiently long layout to evaluate sticky footer.**

- [ ] **Step 3: Exercise delete confirmation through the real built-in route if public APIs expose it.**

Do not add showcase-only framework backdoors.

- [ ] **Step 4: Build CSS and run showcase.**

```powershell
bun run css:build
uv run python -m examples.ui_showcase.main
```

- [ ] **Step 5: Inspect detail/create/edit/error/delete in light/dark and narrow width.**

Check long wrapping, missing dash, validation focus/links, file field, section/tab/details presentation, sticky footer, Cancel/danger separation, and no clipped controls.

- [ ] **Step 6: Fix source defects/rebuild until accepted, then commit showcase/generated CSS.**

```powershell
git add examples/ui_showcase packages/rakit-web/src/rakit_web/static/rakit.css
git commit -m "build(web): finalize CRUD experience visual states"
```

---

### Task 6: Add Focused CRUD Tests After Feature Completion

**Files:**
- Create `packages/rakit-web/tests/test_resource_detail_form_ui_maturity.py`
- Modify existing form/delete route tests only for new safe presentation context
- Modify `tests/test_ui_showcase.py` as needed

- [ ] **Step 1: Test detail title/breadcrumb/context semantics.**

Assert visible-field-only title behavior remains intact and hidden fields are not consulted. Test `None -> —` without altering zero/false/empty-string behavior.

- [ ] **Step 2: Test built-in CRUD action visibility only when safe routes/capabilities exist.**

- [ ] **Step 3: Test form heading/field contracts.**

Assert label association, visible+accessible required marker, help/error IDs in `aria-describedby`, `aria-invalid`, file-input class, and existing multipart behavior.

- [ ] **Step 4: Test validation summary preservation.**

Assert `role="alert"`, focus target/tabindex, safe summary links, and field-local error messages.

- [ ] **Step 5: Test hidden write tokens.**

Assert CSRF/submission/concurrency hidden inputs are still present where applicable.

- [ ] **Step 6: Test delete semantics/presentation.**

Assert explicit consequence text chosen from actual runtime semantics, safe Cancel path, danger submit, and CSRF/submission/delete token preservation.

- [ ] **Step 7: Assert critical CRUD paths remain server-rendered/no-JS functional.**

- [ ] **Step 8: Run focused package suites.**

```powershell
uv run pytest `
  packages/rakit-web/tests/test_resource_detail_form_ui_maturity.py `
  packages/rakit-web/tests/test_accessibility_contracts.py `
  packages/rakit-web/tests/test_actions.py `
  -q
```

Also run the existing form/write/delete/CSRF/idempotency/concurrency suites identified during implementation.

- [ ] **Step 9: Run showcase tests separately if needed.**

```powershell
uv run pytest tests/test_ui_showcase.py -q
```

- [ ] **Step 10: Commit tests.**

```powershell
git add packages/rakit-web/tests tests/test_ui_showcase.py
git commit -m "test(web): cover resource CRUD experience contracts"
```

---

### Task 7: Final Verification and Integration PR

- [ ] **Step 1: Run static gates.**

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

- [ ] **Step 3: Review diff for hidden-field exposure, token loss, permission/capability assumptions, untruthful delete copy, JavaScript-only behavior, or accidental UI-06 scope.**

- [ ] **Step 4: Open PR `ui-05c-resource-detail-forms -> ui-05-resource-experience`.**

- [ ] **Step 5: Review and merge the slice into integration.**

This merge is pre-authorized. Do not merge integration to `main`.

- [ ] **Step 6: After merge, run the combined UI-05 integration gate from `ui-05-resource-experience` and leave it ready for maintainer review.**