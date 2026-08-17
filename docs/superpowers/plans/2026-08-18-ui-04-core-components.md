# UI-04 Core Components Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mature reusable Rakit UI primitives for actions, fields, status/feedback, dialogs/popovers, pagination, and loading while preserving SSR + HTMX behavior and keeping resource/dashboard workflow redesign out of UI-04.

**Architecture:** Use the approved hybrid model: semantic `.rakit-*` CSS primitives provide theme-aware visual/state behavior, thin Jinja macros own stable semantic markup, direct Tailwind utilities remain for local layout, and `rakit-ui.js` is changed only for focused progressive enhancement. No Python component framework, SPA runtime, or resource query behavior is introduced.

**Tech Stack:** Python 3.12+, Starlette ASGI, Jinja2, HTMX, Tailwind CSS 4.1.18, Bun, server-rendered Lucide SVG helper, native HTML dialog/popover primitives, pytest/pytest-anyio/pytest-cov/pytest-xdist, Ruff, ty.

## Global Constraints

- Preserve SSR + HTMX progressive enhancement; no JavaScript-only critical flow.
- Preserve fail-closed capability, permission, CSRF, authentication, idempotency, transaction, and concurrency semantics.
- Tailwind CSS v4 remains the primary styling engine.
- Edit `packages/rakit-web/src/rakit_web/assets/rakit.css`; regenerate `packages/rakit-web/src/rakit_web/static/rakit.css` with `bun run css:build`. Never hand-edit generated CSS.
- Use existing semantic Rakit design tokens; do not introduce ad-hoc product colors.
- Use `@apply` only for stable reusable `.rakit-*` primitives. Local layout remains direct Tailwind utilities.
- Keep light, dark, and system themes first-class.
- Preserve visible focus, practical touch targets, semantic labels/descriptions, reduced-motion behavior, and no color-only state communication.
- Icon-only controls require an accessible name; decorative SVGs remain `aria-hidden="true"` through the existing Rakit icon helper.
- `rakit-chip` remains an entity/filter-like primitive; status is modeled separately through `.rakit-status`.
- Common macro state must use explicit parameters. Do not broaden `attrs|safe` to user-controlled values.
- UI-04 pagination is semantic/visual only. Default `25`, choices `25 / 50 / 100`, query preservation, page reset rules, and resource pagination layout remain UI-05.
- UI-04 does not redesign dashboard, resource tables/search/filter, CRUD form page layout, delete pages, actions/bulk/relationships/uploads, auth/session surfaces, or custom pages.
- `examples/ui_showcase` and `/ui-lab` must use default framework styling only; no private showcase stylesheet.
- No tag, GitHub Release, PyPI, or TestPyPI action.

## File Structure

- `packages/rakit-web/src/rakit_web/assets/rakit.css` — source of reusable component classes and state selectors.
- `packages/rakit-web/src/rakit_web/static/rakit.css` — generated Tailwind output; regenerate only via Bun.
- `packages/rakit-web/src/rakit_web/templates/components/ui.html` — thin Jinja macros for semantic action/status/feedback/pagination/loading markup.
- `packages/rakit-web/src/rakit_web/static/rakit-ui.js` — existing progressive enhancement; extend only for generic dialog trigger/close behavior if required by Task 3.
- `packages/rakit-web/tests/test_ui_primitives.py` — new focused semantic contract suite for UI-04.
- `examples/ui_showcase/templates/ui_lab.html` — deterministic visual acceptance examples using the default primitives.
- `tests/test_ui_showcase.py` — showcase-level regression coverage for the UI Lab states/interactions.

---

### Task 1: Action, Status, Alert, and Loading Primitives

**Files:**
- Create: `packages/rakit-web/tests/test_ui_primitives.py`
- Modify: `packages/rakit-web/src/rakit_web/templates/components/ui.html`
- Modify: `packages/rakit-web/src/rakit_web/assets/rakit.css`

**Interfaces:**
- Consumes: `build_templates(())` from `rakit_web.resource_routes`; existing `rakit_icon()` Jinja global; existing semantic Rakit color/radius/focus tokens.
- Produces Jinja macros:
  - `button(label, variant="primary", type="button", disabled=false, loading=false, aria_label=none, attrs="")`
  - `icon_button(icon, aria_label, variant="quiet", type="button", disabled=false, attrs="")`
  - `status(label, variant="neutral")`
  - `alert(message, variant="info", urgent=false, title="")`
  - `loading(label="Loading")`
- Produces CSS primitives: `.rakit-icon-button`, `.rakit-status` + five semantic variants, `.rakit-alert` + five semantic variants, `.rakit-loading`, `.rakit-spinner`.

- [ ] **Step 1: Write failing macro contract tests**

Create `packages/rakit-web/tests/test_ui_primitives.py` with a helper that renders `components/ui.html` through the real template environment:

```python
from rakit_web.resource_routes import build_templates


def _render(source: str) -> str:
    template = build_templates(()).env.from_string(source)
    return template.render()


def test_button_variants_disabled_and_loading_are_semantic() -> None:
    rendered = _render(
        """
        {% from "components/ui.html" import button %}
        {{ button("Save") }}
        {{ button("Cancel", variant="secondary") }}
        {{ button("Delete", variant="danger", disabled=true) }}
        {{ button("Publish", loading=true) }}
        """
    )

    assert 'class="rakit-button"' in rendered
    assert "rakit-button-secondary" in rendered
    assert "rakit-button-danger" in rendered
    assert "disabled" in rendered
    assert 'aria-busy="true"' in rendered
    assert "rakit-spinner" in rendered
    assert ">Publish<" in rendered


def test_icon_button_requires_visible_accessible_name_contract() -> None:
    rendered = _render(
        """
        {% from "components/ui.html" import icon_button %}
        {{ icon_button("x", "Close dialog") }}
        """
    )

    assert "rakit-icon-button" in rendered
    assert 'aria-label="Close dialog"' in rendered
    assert '<svg aria-hidden="true"' in rendered


def test_status_and_alert_roles_do_not_depend_on_color_alone() -> None:
    rendered = _render(
        """
        {% from "components/ui.html" import status, alert %}
        {{ status("Published", variant="success") }}
        {{ status("Pending review", variant="warning") }}
        {{ alert("Changes saved", variant="success") }}
        {{ alert("Unable to save", variant="danger", urgent=true) }}
        """
    )

    assert "rakit-status-success" in rendered
    assert ">Published<" in rendered
    assert "rakit-status-warning" in rendered
    assert 'role="status"' in rendered
    assert 'role="alert"' in rendered


def test_loading_macro_keeps_readable_context() -> None:
    rendered = _render(
        """
        {% from "components/ui.html" import loading %}
        {{ loading("Loading orders") }}
        """
    )

    assert "rakit-loading" in rendered
    assert "rakit-spinner" in rendered
    assert "Loading orders" in rendered
    assert 'role="status"' in rendered
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```powershell
uv run pytest packages/rakit-web/tests/test_ui_primitives.py -q
```

Expected: failures because the new macros/classes do not yet exist and the existing `button()` macro lacks explicit disabled/loading semantics.

- [ ] **Step 3: Replace the current button macro with explicit common state parameters**

In `templates/components/ui.html`, preserve the trusted internal `attrs` escape hatch but make common semantics explicit. Use static variant branches so Tailwind classes are not dynamically constructed:

```jinja2
{% macro button(label, variant="primary", type="button", disabled=false, loading=false, aria_label=none, attrs="") -%}
  <button
    type="{{ type }}"
    class="rakit-button{% if variant == 'secondary' %} rakit-button-secondary{% elif variant == 'quiet' %} rakit-button-quiet{% elif variant == 'danger' %} rakit-button-danger{% endif %}"
    {% if aria_label %}aria-label="{{ aria_label }}"{% endif %}
    {% if loading %}aria-busy="true"{% endif %}
    {% if disabled or loading %}disabled{% endif %}
    {% if attrs %}{{ attrs|safe }}{% endif %}
  >
    {% if loading %}<span class="rakit-spinner" aria-hidden="true"></span>{% endif %}
    <span>{{ label }}</span>
  </button>
{%- endmacro %}
```

Keep `attrs|safe` limited to existing framework-owned call sites. Do not pass request/user values into it as part of UI-04.

- [ ] **Step 4: Add the new semantic macros**

Add explicit branch-based macros to `components/ui.html`:

```jinja2
{% macro icon_button(icon, aria_label, variant="quiet", type="button", disabled=false, attrs="") -%}
  <button
    type="{{ type }}"
    class="rakit-icon-button{% if variant == 'secondary' %} rakit-button-secondary{% elif variant == 'danger' %} rakit-button-danger{% endif %}"
    aria-label="{{ aria_label }}"
    {% if disabled %}disabled{% endif %}
    {% if attrs %}{{ attrs|safe }}{% endif %}
  >{{ rakit_icon(icon, class_name="size-4") }}</button>
{%- endmacro %}

{% macro status(label, variant="neutral") -%}
  <span class="rakit-status{% if variant == 'success' %} rakit-status-success{% elif variant == 'warning' %} rakit-status-warning{% elif variant == 'danger' %} rakit-status-danger{% elif variant == 'info' %} rakit-status-info{% else %} rakit-status-neutral{% endif %}">{{ label }}</span>
{%- endmacro %}

{% macro alert(message, variant="info", urgent=false, title="") -%}
  <div class="rakit-alert{% if variant == 'success' %} rakit-alert-success{% elif variant == 'warning' %} rakit-alert-warning{% elif variant == 'danger' %} rakit-alert-danger{% elif variant == 'neutral' %} rakit-alert-neutral{% else %} rakit-alert-info{% endif %}" role="{{ 'alert' if urgent else 'status' }}">
    {% if title %}<p class="font-semibold">{{ title }}</p>{% endif %}
    <p>{{ message }}</p>
  </div>
{%- endmacro %}

{% macro loading(label="Loading") -%}
  <span class="rakit-loading" role="status">
    <span class="rakit-spinner" aria-hidden="true"></span>
    <span>{{ label }}</span>
  </span>
{%- endmacro %}
```

Do not add automatic status/alert icons yet; text plus semantic styling already satisfies the non-color-only requirement and avoids icon saturation.

- [ ] **Step 5: Add CSS primitives for action hierarchy, status, alerts, and loading**

In `assets/rakit.css`, extend `@layer components` with stable classes using existing Rakit tokens. Keep touch targets and focus behavior consistent with UI-03:

```css
.rakit-icon-button {
  @apply inline-flex size-10 shrink-0 items-center justify-center rounded-rakit-sm border border-transparent bg-transparent text-rakit-text-muted transition hover:bg-rakit-surface-subtle hover:text-rakit-text disabled:cursor-not-allowed disabled:opacity-50;
}

.rakit-status {
  @apply inline-flex min-h-6 items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold leading-5;
}

.rakit-status-neutral { @apply border-rakit-border bg-rakit-surface-subtle text-rakit-text-muted; }
.rakit-status-success { @apply border-rakit-success/30 bg-rakit-success-subtle text-rakit-text; }
.rakit-status-warning { @apply border-rakit-warning/30 bg-rakit-warning-subtle text-rakit-text; }
.rakit-status-danger { @apply border-rakit-danger/30 bg-rakit-danger-subtle text-rakit-text; }
.rakit-status-info { @apply border-rakit-info/30 bg-rakit-info-subtle text-rakit-text; }

.rakit-alert {
  @apply rounded-rakit-md border p-4 text-sm leading-6 text-rakit-text;
}

.rakit-alert-neutral { @apply border-rakit-border bg-rakit-surface-subtle; }
.rakit-alert-success { @apply border-rakit-success/30 bg-rakit-success-subtle; }
.rakit-alert-warning { @apply border-rakit-warning/30 bg-rakit-warning-subtle; }
.rakit-alert-danger { @apply border-rakit-danger/30 bg-rakit-danger-subtle; }
.rakit-alert-info { @apply border-rakit-info/30 bg-rakit-info-subtle; }

.rakit-loading { @apply inline-flex items-center gap-2 text-sm text-rakit-text-muted; }
.rakit-spinner {
  width: 1rem;
  height: 1rem;
  border: 2px solid color-mix(in oklab, currentColor 28%, transparent);
  border-top-color: currentColor;
  border-radius: 9999px;
  animation: rakit-spin 0.8s linear infinite;
}
```

Add a source-level keyframe outside component declarations:

```css
@keyframes rakit-spin {
  to { transform: rotate(360deg); }
}
```

Existing reduced-motion rules must still stop/short-circuit animation rather than creating a separate motion system.

- [ ] **Step 6: Run focused tests and existing theme/accessibility contracts**

Run:

```powershell
uv run pytest `
  packages/rakit-web/tests/test_ui_primitives.py `
  packages/rakit-web/tests/test_ui_foundation.py `
  packages/rakit-web/tests/test_accessibility_contracts.py `
  -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 1**

```powershell
git add `
  packages/rakit-web/src/rakit_web/assets/rakit.css `
  packages/rakit-web/src/rakit_web/templates/components/ui.html `
  packages/rakit-web/tests/test_ui_primitives.py

git commit -m "style(web): add semantic action and feedback primitives"
```

---

### Task 2: Field and Control State Primitives

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/assets/rakit.css`
- Modify: `packages/rakit-web/tests/test_ui_primitives.py`
- Modify: `examples/ui_showcase/templates/ui_lab.html` only for deterministic field examples needed by this task

**Interfaces:**
- Consumes: existing `.rakit-input`, `.rakit-select`, `.rakit-error` classes.
- Produces: `.rakit-textarea`, `.rakit-checkbox`, `.rakit-radio`, `.rakit-file-input`, `.rakit-field-help`, `.rakit-field-required`, plus consistent `[aria-invalid="true"]`, `:disabled`, and `:read-only` treatment across text-like controls.
- Does not create generic form Jinja macros or change form runtime data flow.

- [ ] **Step 1: Add failing source/markup contracts for field states**

Append tests to `test_ui_primitives.py`:

```python
from importlib.resources import files


def test_field_primitives_cover_textarea_choice_file_and_state_contracts() -> None:
    css = files("rakit_web").joinpath("assets", "rakit.css").read_text()

    for selector in (
        ".rakit-textarea",
        ".rakit-checkbox",
        ".rakit-radio",
        ".rakit-file-input",
        ".rakit-field-help",
        ".rakit-field-required",
        '[aria-invalid="true"]',
        ":read-only",
        ":disabled",
    ):
        assert selector in css
```

Add a showcase-level semantic test only after the UI Lab examples are added in Step 4.

- [ ] **Step 2: Verify RED**

```powershell
uv run pytest packages/rakit-web/tests/test_ui_primitives.py::test_field_primitives_cover_textarea_choice_file_and_state_contracts -q
```

Expected: FAIL because the new field primitives are missing.

- [ ] **Step 3: Add field/control CSS classes without changing runtime form rendering**

In `assets/rakit.css`, keep text-like controls visually aligned:

```css
.rakit-textarea {
  @apply block min-h-24 w-full resize-y rounded-rakit-sm border border-rakit-border-strong bg-rakit-surface px-3 py-2 text-sm text-rakit-text shadow-rakit-sm placeholder:text-rakit-text-muted focus:border-rakit-focus;
}

.rakit-checkbox,
.rakit-radio {
  @apply size-4 border-rakit-border-strong bg-rakit-surface text-rakit-brand-600 accent-rakit-brand-600 disabled:cursor-not-allowed disabled:opacity-50;
}

.rakit-file-input {
  @apply block w-full rounded-rakit-sm border border-rakit-border-strong bg-rakit-surface p-1.5 text-sm text-rakit-text shadow-rakit-sm disabled:cursor-not-allowed disabled:opacity-50;
}

.rakit-file-input::file-selector-button {
  margin-right: 0.75rem;
  min-height: 2rem;
  border: 0;
  border-radius: var(--radius-rakit-sm);
  background: var(--color-rakit-surface-subtle);
  padding-inline: 0.75rem;
  color: var(--color-rakit-text);
  font: inherit;
  font-weight: 500;
  cursor: pointer;
}

.rakit-field-help { @apply mt-1.5 text-sm leading-5 text-rakit-text-muted; }
.rakit-field-required { @apply ml-1 text-rakit-danger; }
```

Apply common state selectors to `.rakit-input`, `.rakit-select`, and `.rakit-textarea`:

```css
.rakit-input[aria-invalid="true"],
.rakit-select[aria-invalid="true"],
.rakit-textarea[aria-invalid="true"] {
  @apply border-rakit-danger;
}

.rakit-input:disabled,
.rakit-select:disabled,
.rakit-textarea:disabled {
  @apply cursor-not-allowed bg-rakit-surface-subtle opacity-60;
}

.rakit-input:read-only,
.rakit-textarea:read-only {
  @apply bg-rakit-surface-subtle;
}
```

Do not remove the existing `.rakit-error`; it remains the server-rendered error-message primitive.

- [ ] **Step 4: Expand only the UI Lab Fields section with representative native controls**

In `examples/ui_showcase/templates/ui_lab.html`, add deterministic examples using the new classes and explicit relationships:

```html
<textarea class="rakit-textarea" id="lab-notes">Handle with care</textarea>
<input class="rakit-input" id="lab-readonly" value="ORD-1080" readonly />
<input class="rakit-input" id="lab-disabled" value="Managed by system" disabled />
<input class="rakit-input" id="lab-invalid" aria-invalid="true" aria-describedby="lab-invalid-error" />
<div class="rakit-error" id="lab-invalid-error" role="alert">This field is required.</div>
<label class="flex items-center gap-2"><input class="rakit-checkbox" type="checkbox" checked /> Featured</label>
<label class="flex items-center gap-2"><input class="rakit-radio" type="radio" name="lab-plan" checked /> Standard</label>
<input class="rakit-file-input" type="file" aria-label="Product image" />
```

Keep this in the existing UI Lab section; do not redesign CRUD form pages.

- [ ] **Step 5: Add UI Lab error-association regression coverage**

Append to `tests/test_ui_showcase.py` in the existing UI Lab test or a focused new test:

```python
assert 'class="rakit-textarea"' in ui_lab.text
assert 'class="rakit-checkbox"' in ui_lab.text
assert 'class="rakit-radio"' in ui_lab.text
assert 'class="rakit-file-input"' in ui_lab.text
assert 'aria-invalid="true"' in ui_lab.text
assert 'aria-describedby="lab-invalid-error"' in ui_lab.text
assert 'id="lab-invalid-error"' in ui_lab.text
```

- [ ] **Step 6: Run field/UI Lab tests**

Run separately to avoid the repository's two-`conftest.py` collision:

```powershell
uv run pytest packages/rakit-web/tests/test_ui_primitives.py -q
uv run pytest tests/test_ui_showcase.py -q
```

Expected: both PASS.

- [ ] **Step 7: Commit Task 2**

```powershell
git add `
  packages/rakit-web/src/rakit_web/assets/rakit.css `
  packages/rakit-web/tests/test_ui_primitives.py `
  examples/ui_showcase/templates/ui_lab.html `
  tests/test_ui_showcase.py

git commit -m "style(web): normalize field control states"
```

---

### Task 3: Dialog and Popover Foundation

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/assets/rakit.css`
- Modify: `packages/rakit-web/src/rakit_web/static/rakit-ui.js`
- Modify: `packages/rakit-web/tests/test_ui_primitives.py`
- Modify: `examples/ui_showcase/templates/ui_lab.html`
- Modify: `tests/test_ui_showcase.py`

**Interfaces:**
- Consumes: existing native `<dialog>` support and existing `rakitDialogReturnFocus`/preview-dialog behavior in `rakit-ui.js`.
- Produces CSS: `.rakit-dialog-title`, `.rakit-dialog-description`, `.rakit-dialog-body`, `.rakit-dialog-footer`, `.rakit-popover`.
- Produces progressive enhancement contract:
  - trigger: `data-rakit-dialog-trigger="<dialog-id>"`
  - close control: `data-rakit-dialog-close`
  - generic dialog remains in DOM after close; preview dialogs keep their existing append/remove lifecycle.
- Uses the browser-native `popover`/`popovertarget` behavior for lightweight popovers instead of adding custom popover JavaScript.

- [ ] **Step 1: Write failing dialog/popover semantic tests**

Append to `test_ui_primitives.py`:

```python
def test_dialog_and_popover_primitives_have_stable_semantic_hooks() -> None:
    css = files("rakit_web").joinpath("assets", "rakit.css").read_text()
    ui_script = files("rakit_web").joinpath("static", "rakit-ui.js").read_text()

    for selector in (
        ".rakit-dialog-title",
        ".rakit-dialog-description",
        ".rakit-dialog-body",
        ".rakit-dialog-footer",
        ".rakit-popover",
    ):
        assert selector in css

    assert "data-rakit-dialog-trigger" in ui_script
    assert "data-rakit-dialog-close" in ui_script
    assert "showModal()" in ui_script
```

- [ ] **Step 2: Verify RED**

```powershell
uv run pytest packages/rakit-web/tests/test_ui_primitives.py::test_dialog_and_popover_primitives_have_stable_semantic_hooks -q
```

Expected: FAIL because the component hooks are not yet present.

- [ ] **Step 3: Add reusable dialog/popover presentation classes**

Extend `assets/rakit.css`:

```css
.rakit-dialog-title { @apply text-base font-semibold text-rakit-text; }
.rakit-dialog-description { @apply mt-1 text-sm leading-6 text-rakit-text-muted; }
.rakit-dialog-body { @apply px-5 py-4; }
.rakit-dialog-footer { @apply flex flex-wrap justify-end gap-2 border-t border-rakit-border bg-rakit-surface-subtle px-5 py-4; }

.rakit-popover {
  @apply max-w-sm rounded-rakit-md border border-rakit-border bg-rakit-surface p-3 text-sm text-rakit-text shadow-rakit-lg;
}
```

Keep `.rakit-dialog` as the native `<dialog>` container and preserve short-viewport scrolling already present from UI-03.

- [ ] **Step 4: Add a small generic dialog trigger/close helper without changing preview semantics**

In `rakit-ui.js`, introduce focused helpers near the existing dialog functions:

```javascript
function rakitOpenDialog(dialog, trigger) {
  if (!(dialog instanceof HTMLDialogElement) || dialog.open) return;
  rakitDialogReturnFocus = trigger instanceof HTMLElement ? trigger : null;
  dialog.showModal();
  dialog.querySelector("[data-rakit-dialog-initial-focus]")?.focus();
  dialog.addEventListener("close", rakitReturnFocus, { once: true });
}

function rakitCloseDialog(control) {
  const dialog = control.closest("dialog");
  if (dialog instanceof HTMLDialogElement && dialog.open) dialog.close("cancel");
}
```

Extend the existing delegated click listener before relationship-specific branches:

```javascript
const dialogTrigger = target.closest("[data-rakit-dialog-trigger]");
if (dialogTrigger instanceof HTMLElement) {
  const dialogId = dialogTrigger.dataset.rakitDialogTrigger;
  const dialog = dialogId ? document.getElementById(dialogId) : null;
  if (dialog instanceof HTMLDialogElement) rakitOpenDialog(dialog, dialogTrigger);
  return;
}

const dialogClose = target.closest("[data-rakit-dialog-close]");
if (dialogClose instanceof HTMLElement) {
  rakitCloseDialog(dialogClose);
  return;
}
```

Do not refactor the destructive preview-dialog lifecycle in this task; keep its existing append/remove behavior intact.

- [ ] **Step 5: Add deterministic interactive UI Lab examples**

Add a dialog trigger and native dialog with labeling relationships:

```html
<button class="rakit-button rakit-button-secondary" type="button" data-rakit-dialog-trigger="lab-dialog">Open dialog</button>
<dialog class="rakit-dialog" id="lab-dialog" aria-labelledby="lab-dialog-title" aria-describedby="lab-dialog-description">
  <div class="rakit-dialog-body">
    <h3 class="rakit-dialog-title" id="lab-dialog-title">Archive product?</h3>
    <p class="rakit-dialog-description" id="lab-dialog-description">This example demonstrates reusable dialog structure without changing a real record.</p>
  </div>
  <div class="rakit-dialog-footer">
    <button class="rakit-button rakit-button-secondary" type="button" data-rakit-dialog-close data-rakit-dialog-initial-focus>Cancel</button>
    <button class="rakit-button rakit-button-danger" type="button" data-rakit-dialog-close>Archive example</button>
  </div>
</dialog>
```

Add a native lightweight popover with no new JS:

```html
<button class="rakit-button rakit-button-secondary" type="button" popovertarget="lab-popover">Open popover</button>
<div class="rakit-popover" id="lab-popover" popover>Lightweight contextual choices belong here.</div>
```

- [ ] **Step 6: Add showcase semantic regression assertions**

Assert the UI Lab contains:

```python
assert 'data-rakit-dialog-trigger="lab-dialog"' in ui_lab.text
assert 'aria-labelledby="lab-dialog-title"' in ui_lab.text
assert 'aria-describedby="lab-dialog-description"' in ui_lab.text
assert 'data-rakit-dialog-close' in ui_lab.text
assert 'popovertarget="lab-popover"' in ui_lab.text
assert 'id="lab-popover" popover' in ui_lab.text
```

- [ ] **Step 7: Run regression suites that exercise existing dialog/action behavior**

```powershell
uv run pytest `
  packages/rakit-web/tests/test_ui_primitives.py `
  packages/rakit-web/tests/test_actions.py `
  packages/rakit-web/tests/test_accessibility_contracts.py `
  -q

uv run pytest tests/test_ui_showcase.py -q
```

Expected: PASS; destructive preview behavior remains unchanged.

- [ ] **Step 8: Commit Task 3**

```powershell
git add `
  packages/rakit-web/src/rakit_web/assets/rakit.css `
  packages/rakit-web/src/rakit_web/static/rakit-ui.js `
  packages/rakit-web/tests/test_ui_primitives.py `
  examples/ui_showcase/templates/ui_lab.html `
  tests/test_ui_showcase.py

git commit -m "feat(web): add reusable dialog and popover primitives"
```

---

### Task 4: Pagination Primitive and Macro

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/templates/components/ui.html`
- Modify: `packages/rakit-web/src/rakit_web/assets/rakit.css`
- Modify: `packages/rakit-web/tests/test_ui_primitives.py`
- Modify: `examples/ui_showcase/templates/ui_lab.html`
- Modify: `tests/test_ui_showcase.py`

**Interfaces:**
- Produces macro: `pagination(page_items, previous_href=none, next_href=none, label="Pagination")`.
- `page_items` is a sequence of mappings with keys:
  - normal page: `{"label": "1", "href": "?page=1", "current": false, "ellipsis": false}`
  - current page: `{"label": "2", "href": none, "current": true, "ellipsis": false}`
  - ellipsis: `{"label": "…", "href": none, "current": false, "ellipsis": true}`
- Produces CSS: `.rakit-pagination`, `.rakit-pagination-link`, `.rakit-pagination-current`, `.rakit-pagination-disabled`, `.rakit-pagination-ellipsis`, `.rakit-pagination-size`.
- Does not construct resource URLs or implement page-size/query rules.

- [ ] **Step 1: Write failing pagination macro contract**

Append to `test_ui_primitives.py`:

```python
def test_pagination_macro_marks_current_disabled_and_ellipsis_semantics() -> None:
    rendered = _render(
        """
        {% from "components/ui.html" import pagination %}
        {{ pagination(
          [
            {"label": "1", "href": "?page=1", "current": false, "ellipsis": false},
            {"label": "2", "href": none, "current": true, "ellipsis": false},
            {"label": "…", "href": none, "current": false, "ellipsis": true},
            {"label": "8", "href": "?page=8", "current": false, "ellipsis": false},
          ],
          previous_href=none,
          next_href="?page=3",
        ) }}
        """
    )

    assert 'aria-label="Pagination"' in rendered
    assert 'aria-disabled="true"' in rendered
    assert 'aria-current="page"' in rendered
    assert "rakit-pagination-ellipsis" in rendered
    assert 'href="?page=3"' in rendered
```

- [ ] **Step 2: Verify RED**

```powershell
uv run pytest packages/rakit-web/tests/test_ui_primitives.py::test_pagination_macro_marks_current_disabled_and_ellipsis_semantics -q
```

Expected: FAIL because `pagination` is not defined.

- [ ] **Step 3: Implement the thin pagination macro without query logic**

Add to `components/ui.html`:

```jinja2
{% macro pagination(page_items, previous_href=none, next_href=none, label="Pagination") -%}
<nav class="rakit-pagination" aria-label="{{ label }}">
  {% if previous_href %}
    <a class="rakit-pagination-link" href="{{ previous_href }}">Previous</a>
  {% else %}
    <span class="rakit-pagination-disabled" aria-disabled="true">Previous</span>
  {% endif %}

  <ol class="flex items-center gap-1" role="list">
    {% for item in page_items %}
      <li>
        {% if item.ellipsis %}
          <span class="rakit-pagination-ellipsis" aria-hidden="true">{{ item.label }}</span>
        {% elif item.current %}
          <span class="rakit-pagination-current" aria-current="page">{{ item.label }}</span>
        {% else %}
          <a class="rakit-pagination-link" href="{{ item.href }}" aria-label="Page {{ item.label }}">{{ item.label }}</a>
        {% endif %}
      </li>
    {% endfor %}
  </ol>

  {% if next_href %}
    <a class="rakit-pagination-link" href="{{ next_href }}">Next</a>
  {% else %}
    <span class="rakit-pagination-disabled" aria-disabled="true">Next</span>
  {% endif %}
</nav>
{%- endmacro %}
```

The caller owns every URL. Do not add page-count calculations or resource query serialization.

- [ ] **Step 4: Add pagination CSS classes**

In `assets/rakit.css`:

```css
.rakit-pagination { @apply flex flex-wrap items-center justify-between gap-3 text-sm; }
.rakit-pagination-link { @apply inline-flex min-h-9 min-w-9 items-center justify-center rounded-rakit-sm border border-rakit-border bg-rakit-surface px-3 font-medium text-rakit-text transition hover:bg-rakit-surface-subtle; }
.rakit-pagination-current { @apply inline-flex min-h-9 min-w-9 items-center justify-center rounded-rakit-sm border border-rakit-brand-600 bg-rakit-brand-subtle px-3 font-semibold text-rakit-brand-700 dark:text-rakit-brand-200; }
.rakit-pagination-disabled { @apply inline-flex min-h-9 items-center justify-center rounded-rakit-sm border border-rakit-border bg-rakit-surface-subtle px-3 text-rakit-text-subtle; }
.rakit-pagination-ellipsis { @apply inline-flex min-h-9 min-w-9 items-center justify-center text-rakit-text-muted; }
.rakit-pagination-size { @apply inline-flex items-center gap-2 text-sm text-rakit-text-muted; }
```

- [ ] **Step 5: Add deterministic pagination UI Lab example**

Import/use the macro in `ui_lab.html` with fixed dummy URLs and show page-size styling separately:

```jinja2
{% from "components/ui.html" import pagination %}
{{ pagination(
  [
    {"label": "1", "href": "#page-1", "current": false, "ellipsis": false},
    {"label": "2", "href": none, "current": true, "ellipsis": false},
    {"label": "3", "href": "#page-3", "current": false, "ellipsis": false},
    {"label": "…", "href": none, "current": false, "ellipsis": true},
    {"label": "8", "href": "#page-8", "current": false, "ellipsis": false},
  ],
  previous_href=none,
  next_href="#page-3",
) }}
<label class="rakit-pagination-size">Rows per page <select class="rakit-select w-24"><option>25</option><option>50</option><option>100</option></select></label>
```

These are visual fixtures only; they do not alter resource pagination behavior.

- [ ] **Step 6: Run primitive + showcase tests**

```powershell
uv run pytest packages/rakit-web/tests/test_ui_primitives.py -q
uv run pytest tests/test_ui_showcase.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 4**

```powershell
git add `
  packages/rakit-web/src/rakit_web/templates/components/ui.html `
  packages/rakit-web/src/rakit_web/assets/rakit.css `
  packages/rakit-web/tests/test_ui_primitives.py `
  examples/ui_showcase/templates/ui_lab.html `
  tests/test_ui_showcase.py

git commit -m "style(web): add pagination primitive"
```

---

### Task 5: Complete UI Lab State Matrix, Build Assets, and Run the PR Gate

**Files:**
- Modify: `examples/ui_showcase/templates/ui_lab.html`
- Modify: `tests/test_ui_showcase.py`
- Modify: `packages/rakit-web/src/rakit_web/static/rakit.css` only through `bun run css:build`
- Modify: source/test files from Tasks 1–4 only if verification exposes a real defect

**Interfaces:**
- Consumes every UI-04 primitive/macro from Tasks 1–4.
- Produces the final deterministic UI Lab acceptance matrix and generated CSS for the PR.

- [ ] **Step 1: Ensure UI Lab imports and demonstrates the final macro surface**

At the top of `ui_lab.html`, import the macros used by the lab:

```jinja2
{% from "components/ui.html" import button, icon_button, status, alert, loading, pagination %}
```

Ensure the page visibly demonstrates:
- primary / secondary / quiet / danger;
- disabled and loading button states;
- one icon-only control with accessible name;
- default / read-only / disabled / invalid text controls;
- textarea, select, checkbox, radio, file input;
- neutral / success / warning / danger / info status badges;
- neutral / success / warning / danger / info alerts;
- dialog and native popover;
- current / disabled / ellipsis pagination states;
- standalone loading/pending treatment.

Use the macros rather than duplicating semantic markup when a UI-04 macro exists.

- [ ] **Step 2: Add a single showcase matrix regression test**

Add or extend a focused test in `tests/test_ui_showcase.py` after authenticated `/ui-lab` fetch:

```python
assert "rakit-icon-button" in ui_lab.text
assert "rakit-status-neutral" in ui_lab.text
assert "rakit-status-success" in ui_lab.text
assert "rakit-status-warning" in ui_lab.text
assert "rakit-status-danger" in ui_lab.text
assert "rakit-status-info" in ui_lab.text
assert "rakit-alert-success" in ui_lab.text
assert "rakit-alert-danger" in ui_lab.text
assert 'role="alert"' in ui_lab.text
assert "rakit-loading" in ui_lab.text
assert 'aria-busy="true"' in ui_lab.text
assert "rakit-pagination-current" in ui_lab.text
assert 'aria-current="page"' in ui_lab.text
assert 'aria-disabled="true"' in ui_lab.text
assert 'data-rakit-dialog-trigger="lab-dialog"' in ui_lab.text
assert 'popovertarget="lab-popover"' in ui_lab.text
```

Do not turn this into a full HTML snapshot.

- [ ] **Step 3: Run formatting before building generated assets**

```powershell
uv run ruff format .
uv run ruff format --check .
uv run ruff check .
uv run ty check
git diff --check
```

Expected: all PASS.

- [ ] **Step 4: Regenerate committed Tailwind CSS from the maintainer source**

```powershell
bun install --frozen-lockfile
bun run css:build
```

Then verify the only generated styling change is the expected asset:

```powershell
git status --short
```

`packages/rakit-web/src/rakit_web/static/rakit.css` may be modified. Never edit it manually.

- [ ] **Step 5: Run focused UI-04 and authoritative regression suites**

Run package-root tests together:

```powershell
uv run pytest `
  packages/rakit-web/tests/test_ui_primitives.py `
  packages/rakit-web/tests/test_ui_foundation.py `
  packages/rakit-web/tests/test_theme.py `
  packages/rakit-web/tests/test_accessibility_contracts.py `
  packages/rakit-web/tests/test_actions.py `
  packages/rakit-web/tests/test_bulk_list_ui.py `
  -q
```

Run root showcase separately because the repository has a different root `conftest.py`:

```powershell
uv run pytest tests/test_ui_showcase.py -q
```

Expected: PASS.

- [ ] **Step 6: Run the complete repository verification gate**

```powershell
uv run ruff format --check .
uv run ruff check .
uv run ty check
git diff --check
uv run pytest -n auto --cov
uv run mkdocs build --strict
uv run python scripts/check_artifacts.py
```

Expected:
- coverage remains >= 85%;
- only known non-blocking Starlette TestClient deprecation warnings may remain;
- docs strict build passes;
- artifact consistency passes.

- [ ] **Step 7: Perform manual visual/keyboard acceptance in the showcase**

Run:

```powershell
uv run python -m examples.ui_showcase.main
```

Inspect `http://127.0.0.1:8000/ui-lab` in light and dark modes. Verify:
- button hierarchy is obvious without excessive brand color;
- disabled labels remain readable;
- loading buttons retain their action label;
- icon buttons have a practical target and visible focus;
- all five status/alert variants are distinguishable by text as well as color;
- textarea/checkbox/radio/file controls match the design system;
- invalid field error relationship remains clear;
- dialog opens, initial focus is predictable, Escape works, cancel closes, and focus returns to the trigger;
- native popover light-dismisses/Escape-closes;
- pagination current/disabled/ellipsis states are clear;
- no new component breaks the collapsed desktop sidebar or mobile drawer;
- Tab, Shift+Tab, Enter, Space, and Escape remain usable;
- reduced-motion preference does not gate content.

- [ ] **Step 8: Commit generated CSS and final UI Lab polish**

```powershell
git add `
  packages/rakit-web/src/rakit_web/static/rakit.css `
  examples/ui_showcase/templates/ui_lab.html `
  tests/test_ui_showcase.py `
  packages/rakit-web/src/rakit_web/assets/rakit.css `
  packages/rakit-web/src/rakit_web/templates/components/ui.html `
  packages/rakit-web/src/rakit_web/static/rakit-ui.js `
  packages/rakit-web/tests/test_ui_primitives.py

git commit -m "style(web): complete UI-04 core component matrix"
```

If some listed files have no final unstaged changes because they were committed in Tasks 1–4, `git add` simply leaves them unchanged.

- [ ] **Step 9: Verify clean branch state and prepare the PR**

```powershell
git status --short
git log -6 --oneline
```

Expected: clean working tree. Push `ui-04-core-components` and open a draft PR against `main`. Do not merge until final diff review, verification evidence, and maintainer visual approval are complete.

---

## Deferred Follow-up: Rakit-Owned Database Table Prefixing

The maintainer has separately proposed prefixing Rakit-owned database tables with `rakit_` so application/domain tables are visually distinct from framework infrastructure. This is **not part of UI-04** and must not be implemented from this plan.

When scheduled as its own design/plan, evaluate:
- prefix only framework-owned infrastructure tables, never arbitrary user/domain tables;
- default names such as `rakit_sessions`, `rakit_roles`, `rakit_role_bindings`, and `rakit_idempotency_keys` based on the actual table inventory at that time;
- isolate Rakit's migration-version table as `rakit_alembic_version` so host-application Alembic history cannot collide;
- prefer portable prefixing across SQLite/MySQL/PostgreSQL over relying only on PostgreSQL schemas;
- use explicit rename/data-preserving migrations rather than drop/recreate;
- decide separately whether prefix customization is justified; default fixed `rakit_` is preferred until a concrete override use case exists.
