# UI-05C Resource Detail, Forms & Delete Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mature built-in record CRUD presentation across resource list/detail, create/edit forms, validation, and delete confirmation while preserving authorization and write-pipeline guarantees.

**Architecture:** Keep existing resource and write routes authoritative. Add only narrow presentation metadata: registered CRUD route paths are carried from Admin composition into resource list/detail rendering, and `form_routes.py` supplies safe form/delete context. Jinja/Tailwind own presentation. Feature work is completed and visually reviewed before the focused test phase.

**Tech Stack:** Python 3.12+, Starlette, Jinja2, HTMX, Tailwind CSS v4, server-rendered Lucide icons, pytest, Ruff, ty.

## Global Constraints

- Start only after UI-05B merges into `ui-05-resource-experience`.
- Feature branch: `ui-05c-resource-detail-forms`.
- Merge destination: `ui-05-resource-experience`, not `main`.
- Built-in CRUD only: Create/Edit/Delete when write routes are registered for the resource.
- Route-level authorization remains authoritative even when a registered CRUD affordance is rendered; this slice must not weaken middleware or mutation authorization.
- Domain actions, relationships, advanced bulk, advanced uploads, auth/session, and custom pages remain UI-06.
- Preserve UI-03 visible-detail-field-only title derivation.
- Never inspect hidden/policy-excluded fields for a prettier title or delete label.
- Preserve CSRF, submission/idempotency, concurrency, and delete-token behavior exactly.
- Preserve server validation and status-code/security behavior.
- No JavaScript-only critical CRUD path.
- Form layout definition remains authoritative.
- Use UI-04 field/help/error/file/button/alert primitives where compatible.
- `None` may render as `—`; empty string, zero, and false remain real values.
- Delete copy must match actual generic runtime semantics; do not promise irreversible physical deletion because adapters may implement deletion differently.
- Execution order: feature -> visual/manual review -> tests at end -> full verification.

## File Structure

- `packages/rakit-web/src/rakit_web/resource_routes.py` — `ResourceCrudPaths`, list/detail CRUD URLs, safe missing-value presentation.
- `packages/rakit-web/src/rakit_web/admin.py` — pass registered `WriteResourceBinding` paths into each `ResourceBinding`; no authorization semantics change.
- `packages/rakit-web/src/rakit_web/form_routes.py` — safe form breadcrumb/cancel context and delete label/cancel context; token behavior unchanged.
- `packages/rakit-web/src/rakit_web/templates/resources/list.html` — built-in Create affordance when registered.
- `packages/rakit-web/src/rakit_web/templates/resources/detail.html` — entity hierarchy, Edit/Delete affordances, `<dl>`, missing values.
- `packages/rakit-web/src/rakit_web/templates/forms/form.html` — create/edit hierarchy, fields, validation, layout, footer.
- `packages/rakit-web/src/rakit_web/templates/forms/delete_confirm.html` — explicit destructive decision page.
- `packages/rakit-web/src/rakit_web/templates/components/ui.html` — extend only for backward-compatible shared primitives.
- `packages/rakit-web/src/rakit_web/assets/rakit.css` and generated static CSS.
- `packages/rakit-web/src/rakit_web/static/rakit-ui.js` only for small existing-hook pending/focus enhancement if needed.
- `examples/ui_showcase` deterministic CRUD visual states.
- Create `packages/rakit-web/tests/test_resource_detail_form_ui_maturity.py` in the final test phase.

---

### Task 1: Expose Registered CRUD Paths to Resource Presentation

**Files:**
- Modify `packages/rakit-web/src/rakit_web/resource_routes.py`
- Modify `packages/rakit-web/src/rakit_web/admin.py`

**Interfaces:**
- Consumes existing `WriteResourceBinding.create_path`, `.update_path`, `.delete_path` and the `Admin._write_resource_bindings` registry.
- Produces presentation-only CRUD paths without importing `form_routes.py` into `resource_routes.py`.

- [ ] **Step 1: Add `ResourceCrudPaths` in `resource_routes.py`.**

```python
@dataclass(frozen=True)
class ResourceCrudPaths:
    create_path: str
    update_path: str
    delete_path: str
```

The update/delete strings retain their existing `{identity}` placeholders.

- [ ] **Step 2: Extend `ResourceBinding` with `crud_paths: ResourceCrudPaths | None = None`.**

This contains route-registration metadata only. It does not grant permission and does not replace route/mutation authorization.

- [ ] **Step 3: In `Admin.asgi()` resource binding construction, derive `ResourceCrudPaths` only when `self._write_resource_bindings.get(resource_id)` exists.**

Use the registered binding's exact `create_path`, `update_path`, and `delete_path`; otherwise pass `None`.

- [ ] **Step 4: Add safe list/detail CRUD URL context in `resource_routes.py`.**

List response:

- `create_url` = mounted create path when `crud_paths` exists, otherwise empty string.

Detail response, after identity has been successfully decoded/encoded through the existing codec:

- `edit_url` = mounted update path with `{identity}` replaced by the encoded identity;
- `delete_url` = mounted delete path with `{identity}` replaced by the encoded identity;
- both empty when `crud_paths` is absent.

Do not derive these URLs from labels or raw unvalidated identifiers.

- [ ] **Step 5: Keep authorization behavior untouched.**

These links indicate registered built-in routes. Requests to them still pass through the existing authorization middleware and mutation authorization. Do not add permission shortcuts or bypasses in presentation code.

- [ ] **Step 6: Commit composition/runtime presentation metadata.**

```powershell
git add `
  packages/rakit-web/src/rakit_web/resource_routes.py `
  packages/rakit-web/src/rakit_web/admin.py
git commit -m "feat(web): expose registered CRUD paths to resource views"
```

---

### Task 2: Mature Resource List Create Affordance and Record Detail

**Files:**
- Modify `packages/rakit-web/src/rakit_web/templates/resources/list.html`
- Modify `packages/rakit-web/src/rakit_web/templates/resources/detail.html`
- Modify `packages/rakit-web/src/rakit_web/resource_routes.py` only for safe display normalization
- Modify `packages/rakit-web/src/rakit_web/assets/rakit.css` only for reusable detail primitives

- [ ] **Step 1: Add Create action to the resource heading only when `create_url` is non-empty.**

Use the UI-04 primary/secondary action hierarchy and no domain-action assumptions.

- [ ] **Step 2: Preserve the current visible-field-only `record_view` title/identity algorithm.**

Never broaden lookup beyond `fields`/`cells` already supplied to the detail template.

- [ ] **Step 3: Refine detail breadcrumb/header.**

Keep Dashboard -> resource -> safe visible identity. Exactly one `<h1>`. Add Edit/Delete buttons only when their server-provided URLs are non-empty.

- [ ] **Step 4: Keep Edit and Delete visually separated.**

Edit uses primary/strong secondary treatment; Delete uses danger treatment and links to the explicit server-rendered confirmation route. Domain actions remain absent.

- [ ] **Step 5: Mature the semantic `<dl>`.**

Use semantic Rakit tokens, calm dividers, responsive stacking, and long-value wrapping. Avoid card-per-field layouts.

- [ ] **Step 6: Normalize `None` to `—` at the presentation boundary only.**

Do not replace `""`, `0`, or `False`.

- [ ] **Step 7: Commit list/detail feature work.**

```powershell
git add `
  packages/rakit-web/src/rakit_web/resource_routes.py `
  packages/rakit-web/src/rakit_web/templates/resources/list.html `
  packages/rakit-web/src/rakit_web/templates/resources/detail.html `
  packages/rakit-web/src/rakit_web/assets/rakit.css
git commit -m "style(web): mature built-in resource CRUD hierarchy"
```

---

### Task 3: Add Safe Form Page Context in `form_routes.py`

**Files:**
- Modify `packages/rakit-web/src/rakit_web/form_routes.py`

**Interfaces:**
- Consumes current `_form_response()` arguments, `binding.path`, server-built `action_path`, and validated `parent_identity`.
- Produces safe list/cancel breadcrumb context without parsing request referrers.

- [ ] **Step 1: Add `resource_url` to `_form_response()` template context.**

Use `mounted_path(request, binding.path)`.

- [ ] **Step 2: Add `cancel_url` to `_form_response()` context.**

For create, cancel to the resource list.

For update, preserve the current effective detail cancel destination using the already server-built update `action_path`: strip only the final `/edit` segment from that trusted server path before applying `mounted_path`. Do not inspect `Referer` and do not parse user-provided query values.

- [ ] **Step 3: Keep `label`, `title`, `operation`, action URL, CSRF/submission/concurrency tokens, layout, and validation context unchanged.**

- [ ] **Step 4: Commit form context work.**

```powershell
git add packages/rakit-web/src/rakit_web/form_routes.py
git commit -m "feat(web): add safe CRUD navigation context"
```

---

### Task 4: Mature Create/Edit Form Presentation

**Files:**
- Modify `packages/rakit-web/src/rakit_web/templates/forms/form.html`
- Modify `packages/rakit-web/src/rakit_web/assets/rakit.css`
- Modify `packages/rakit-web/src/rakit_web/templates/components/ui.html` only if a shared backward-compatible primitive needs extension

- [ ] **Step 1: Add breadcrumb/context using `resource_url`, `label`, `operation`, and current title.**

Keep exactly one page `<h1>`.

- [ ] **Step 2: Migrate old direct palette utilities to semantic Rakit roles.**

Use UI-04 field help/error/required/surface/button primitives. Remove decorative backdrop-blur/glass styling from the sticky footer.

- [ ] **Step 3: Preserve recursive `render_node()` semantics exactly.**

Do not change meanings of field, section, row, column, tabs, collapsible, relationship, or custom nodes.

- [ ] **Step 4: Refine fields.**

Keep explicit label association, existing description/error IDs, `aria-describedby`, `aria-invalid`, and server values. File fields use `.rakit-file-input`; no field-type guessing from names.

- [ ] **Step 5: Add visible + screen-reader required indicator only when `field.required` is true.**

Preserve actual required semantics already supplied by the runtime.

- [ ] **Step 6: Refine explicit sections/rows/columns/tabs/collapsible.**

Sections may use semantic panels; rows/columns remain layout helpers; tabs remain server-rendered/anchor accessible; collapsible remains native `<details>`.

- [ ] **Step 7: Keep relationship/custom behavior untouched.**

Advanced presentation stays UI-06.

- [ ] **Step 8: Replace the Cancel URL string manipulation in the template with server-provided `cancel_url`.**

- [ ] **Step 9: Commit form feature work.**

```powershell
git add `
  packages/rakit-web/src/rakit_web/templates/forms/form.html `
  packages/rakit-web/src/rakit_web/templates/components/ui.html `
  packages/rakit-web/src/rakit_web/assets/rakit.css
git commit -m "style(web): mature create and edit form presentation"
```

---

### Task 5: Mature Validation Summary and Submission Footer

**Files:**
- Modify `packages/rakit-web/src/rakit_web/templates/forms/form.html`
- Modify `packages/rakit-web/src/rakit_web/assets/rakit.css`
- Modify `packages/rakit-web/src/rakit_web/static/rakit-ui.js` only if existing hooks need small progressive enhancement

- [ ] **Step 1: Convert the validation summary to shared semantic danger/alert presentation.**

Retain `id="form-errors"`, `role="alert"`, `tabindex="-1"`, `data-rakit-focus-target="form-errors"`, safe summary links, and local field errors.

- [ ] **Step 2: Preserve every hidden write field.**

`csrf_token`, `submission_token`, and optional `concurrency_token` names/values remain unchanged.

- [ ] **Step 3: Use a solid semantic sticky action footer.**

Cancel secondary, Create/Save primary, practical narrow-screen stacking, no overlap with form content.

- [ ] **Step 4: If current HTMX form enhancement already supports pending state, reuse UI-04 readable loading/busy presentation.**

Do not create a JavaScript-only submission path and do not treat disabled UI as the idempotency mechanism.

- [ ] **Step 5: Commit validation/footer work.**

```powershell
git add `
  packages/rakit-web/src/rakit_web/templates/forms/form.html `
  packages/rakit-web/src/rakit_web/assets/rakit.css `
  packages/rakit-web/src/rakit_web/static/rakit-ui.js
git commit -m "style(web): refine form validation and submission hierarchy"
```

Stage `rakit-ui.js` only if it actually changed.

---

### Task 6: Add Safe Delete Context and Explicit Confirmation Page

**Files:**
- Modify `packages/rakit-web/src/rakit_web/form_routes.py`
- Modify `packages/rakit-web/src/rakit_web/templates/forms/delete_confirm.html`
- Modify `packages/rakit-web/src/rakit_web/assets/rakit.css` only if a reusable destructive-decision primitive is justified

**Interfaces:**
- Current `delete_get()` already supplies `action_url`, `csrf_token`, `delete_token`, and `submission_token`.
- This task adds safe presentation-only `label` and `cancel_url`.

- [ ] **Step 1: Extend `delete_get()` context with `label=binding.label`.**

Do not fetch/reflect hidden record fields merely to make the heading prettier.

- [ ] **Step 2: Add `cancel_url=mounted_path(request, binding.path)`.**

Cancel returns safely to the resource list. Do not trust `Referer`.

- [ ] **Step 3: Use truthful generic consequence copy.**

Because `WriteMutationService.delete()` is adapter-facing and the framework does not guarantee physical irreversible deletion, use wording such as:

`Deleting this record removes it through the configured resource adapter. Review this action before continuing.`

Do not claim `permanent` or `cannot be undone` at framework level.

- [ ] **Step 4: Render a single destructive heading and explicit action hierarchy.**

Heading may use safe `binding.label`; Cancel is secondary; submit is a danger button such as `Delete record` or `Delete <label>`.

- [ ] **Step 5: Preserve hidden inputs exactly.**

Keep `csrf_token`, `submission_token`, and `delete_token` unchanged. Do not add/remove confirmation semantics.

- [ ] **Step 6: Commit delete feature work.**

```powershell
git add `
  packages/rakit-web/src/rakit_web/form_routes.py `
  packages/rakit-web/src/rakit_web/templates/forms/delete_confirm.html `
  packages/rakit-web/src/rakit_web/assets/rakit.css
git commit -m "style(web): mature delete confirmation experience"
```

---

### Task 7: Expand CRUD Showcase and Perform Visual Acceptance

**Files:**
- Modify `examples/ui_showcase` through public APIs only
- Regenerate `packages/rakit-web/src/rakit_web/static/rakit.css`

- [ ] **Step 1:** Exercise detail title+identity, fallback title, long values, missing optional values, create, edit, multi-error validation, file field, long form, and delete confirmation where public APIs expose them.
- [ ] **Step 2:** Do not add showcase-only framework backdoors.
- [ ] **Step 3:** Build and run.

```powershell
bun run css:build
uv run python -m examples.ui_showcase.main
```

- [ ] **Step 4:** Inspect light/dark and narrow widths: wrapping, missing dash, required/help/error state, validation focus/links, file input, sections/tabs/details, footer, Cancel/danger separation.
- [ ] **Step 5:** Fix source defects and rebuild until accepted.
- [ ] **Step 6:** Commit showcase/generated CSS.

```powershell
git add examples/ui_showcase packages/rakit-web/src/rakit_web/static/rakit.css
git commit -m "build(web): finalize CRUD experience visual states"
```

---

### Task 8: Add Focused CRUD Tests After Feature Completion

**Files:**
- Create `packages/rakit-web/tests/test_resource_detail_form_ui_maturity.py`
- Modify existing form/resource tests only when the new presentation context needs direct coverage
- Modify `tests/test_ui_showcase.py` as needed

- [ ] **Step 1:** Test `ResourceCrudPaths` exists only for registered write resources and produces correct mounted Create/Edit/Delete URLs while leaving route authorization unchanged.
- [ ] **Step 2:** Test visible-detail-field-only title behavior and `None -> —` without changing valid falsy values.
- [ ] **Step 3:** Test list/detail CRUD links are absent when write routes are not registered.
- [ ] **Step 4:** Test form breadcrumb/context and server-provided safe Cancel URL.
- [ ] **Step 5:** Test labels, visible+accessible required marker, help/error IDs, `aria-describedby`, `aria-invalid`, file-input class, and multipart behavior.
- [ ] **Step 6:** Test validation summary keeps alert/focus/link semantics and local field errors.
- [ ] **Step 7:** Test CSRF/submission/concurrency fields remain present where applicable.
- [ ] **Step 8:** Test delete context/copy/Cancel/danger hierarchy and CSRF/submission/delete-token preservation.
- [ ] **Step 9:** Assert critical CRUD flows remain server-rendered/no-JS functional.
- [ ] **Step 10:** Run focused package suites including existing form/write/delete/CSRF/idempotency/concurrency tests discovered in the package.

```powershell
uv run pytest `
  packages/rakit-web/tests/test_resource_detail_form_ui_maturity.py `
  packages/rakit-web/tests/test_accessibility_contracts.py `
  -q
```

- [ ] **Step 11:** Run showcase tests separately if needed.

```powershell
uv run pytest tests/test_ui_showcase.py -q
```

- [ ] **Step 12:** Commit tests.

```powershell
git add packages/rakit-web/tests/test_resource_detail_form_ui_maturity.py tests/test_ui_showcase.py
git commit -m "test(web): cover resource CRUD experience contracts"
```

---

### Task 9: Final Verification and Integration Merge

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

- [ ] **Step 3:** Review for hidden-field exposure, token loss, authorization changes, untruthful delete copy, JavaScript-only behavior, or UI-06 scope creep.
- [ ] **Step 4:** Open PR `ui-05c-resource-detail-forms -> ui-05-resource-experience`.
- [ ] **Step 5:** Review and merge the slice into integration. This merge is pre-authorized; do not merge integration to `main`.
- [ ] **Step 6:** Run/record the combined UI-05 integration gate and leave `ui-05-resource-experience` ready for maintainer review.