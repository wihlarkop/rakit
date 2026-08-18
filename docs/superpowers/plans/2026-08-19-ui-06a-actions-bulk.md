# UI-06A Actions & Bulk Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add explicit Web-only action hierarchy and mature action/bulk interaction surfaces while preserving the existing action execution, authorization, availability, CSRF, idempotency, transaction, confirmation, and concurrency contracts.

**Architecture:** Keep `ActionDefinition` unchanged in `rakit-core`. Add immutable Web-only `ActionIntent` / `ActionPresentation` bindings keyed to the exact `ActionDefinition` objects, extend `ResourceWebPresentation` and add `PageWebPresentation`, then expose permission-filtered action links to templates. Use server-rendered `<details>` overflow groups and existing action routes so the critical flow remains fully usable without JavaScript.

**Tech Stack:** Python 3.12+, Starlette ASGI, Jinja2, HTMX progressive enhancement, Tailwind CSS 4.1.18, Bun asset build, pytest/pytest-anyio, Ruff, ty.

**Spec:** `docs/superpowers/specs/2026-08-19-ui-06-advanced-operations-auth-system-design.md`

## Global Constraints

- Work from `ui-06-advanced-operations`; implement UI-06A on a child branch and merge only into the integration branch after acceptance.
- Feature/source implementation comes first; regression tests are added at the end of the slice.
- Do not add fields to `rakit_core.actions.ActionDefinition`.
- `ActionIntent.DANGER` never implies confirmation; `needs_confirmation` remains core-authoritative.
- A mutating action is not automatically danger.
- At most one `PRIMARY` action is allowed per owner + `ActionScope`.
- Unknown action presentation ids fail closed before registration mutates application state.
- Permission checks hide action links the principal cannot invoke, but POST execution still independently authorizes and re-checks availability.
- `AVAILABLE`, `DISABLED`, and `HIDDEN` behavior remains authoritative in the existing action route pipeline.
- Preserve signed CSRF, submission, confirmation, and concurrency tokens exactly.
- Preserve action idempotency receipt/replay semantics exactly.
- Preserve `ActionSuccess`, `ActionRedirect`, `ActionRefresh`, `ActionRejected`, `ActionRendered`, `ActionAdvancedResponse`, and validation HTTP/HTMX semantics.
- Edit `packages/rakit-web/src/rakit_web/assets/rakit.css`; regenerate `packages/rakit-web/src/rakit_web/static/rakit.css` with `bun run css:build`. Never hand-edit generated CSS.
- Do not introduce a JavaScript-only action path. Overflow menus must work with native `<details>`.
- No release/tag/PyPI action.

---

## File Map

### Create
- `packages/rakit-web/src/rakit_web/action_presentation.py` — shared Web-only action intent, immutable binding registry, and validation helper.
- `packages/rakit-web/src/rakit_web/page_presentation.py` — `PageWebPresentation` container for PAGE action presentation.
- `packages/rakit-web/src/rakit_web/templates/components/actions.html` — reusable action-group / overflow macros.
- `packages/rakit-web/tests/test_advanced_ui_maturity.py` — slice-level presentation contract tests, added only after feature behavior exists.

### Modify
- `packages/rakit-web/src/rakit_web/resource_presentation.py` — add immutable `actions` mapping to `ResourceWebPresentation`.
- `packages/rakit-web/src/rakit_web/dashboard_admin.py` — validate and bind resource action presentation before/after normal registration.
- `packages/rakit-web/src/rakit_web/admin.py` — extend `register_page(..., web=...)` and install generic action-link template helper.
- `packages/rakit-web/src/rakit_web/page_admin.py` — pass PAGE action views/presentation into page rendering without changing page execution semantics.
- `packages/rakit-web/src/rakit_web/action_routes.py` — expose action presentation to form/confirm templates; keep execution unchanged.
- `packages/rakit-web/src/rakit_web/bulk_admin.py` — include intent in permission-filtered bulk action views.
- `packages/rakit-web/src/rakit_web/bulk_routes.py` — expose bulk policy/presentation values already available to the template.
- `packages/rakit-web/src/rakit_web/resource_routes.py` — register action-presentation template global and include encoded identity for record action links.
- `packages/rakit-web/src/rakit_web/templates/resources/list.html` — RESOURCE action group in the page header.
- `packages/rakit-web/src/rakit_web/templates/resources/detail.html` — RECORD action group merged with Edit/Delete hierarchy.
- `packages/rakit-web/src/rakit_web/templates/resources/_table.html` — mature selection-aware BULK action bar.
- `packages/rakit-web/src/rakit_web/templates/actions/_form.html` — semantic action form styling.
- `packages/rakit-web/src/rakit_web/templates/actions/_confirm.html` — authoritative review/confirmation surface.
- `packages/rakit-web/src/rakit_web/templates/actions/bulk.html` — selected-count, impact, execution-policy presentation.
- `packages/rakit-web/src/rakit_web/assets/rakit.css` — stable action menu / bulk bar primitives only where reusable.
- `packages/rakit-web/src/rakit_web/static/rakit.css` — generated CSS.
- `packages/rakit/src/rakit/__init__.py` — public exports for `ActionIntent`, `ActionPresentation`, and `PageWebPresentation`.
- `examples/ui_showcase/main.py` — deterministic normal/danger/disabled/form/preview/bulk scenarios.
- Existing regression suites: `packages/rakit-web/tests/test_actions.py`, `packages/rakit-web/tests/test_bulk_actions.py`, `packages/rakit-web/tests/test_bulk_list_ui.py`.

---

### Task 1: Add Web-only Action Presentation Contracts

**Files:**
- Create: `packages/rakit-web/src/rakit_web/action_presentation.py`
- Create: `packages/rakit-web/src/rakit_web/page_presentation.py`
- Modify: `packages/rakit-web/src/rakit_web/resource_presentation.py`
- Modify: `packages/rakit/src/rakit/__init__.py`

**Interfaces:**
- Consumes: `ActionDefinition.action_id`, `ActionDefinition.scope`.
- Produces: `ActionIntent`, `ActionPresentation`, `bind_action_web_presentation()`, `action_web_presentation()`, `validate_action_presentations()`, `PageWebPresentation`, and `ResourceWebPresentation.actions`.

- [ ] **Step 1: Create `action_presentation.py` with the immutable public contract**

Use this exact shape:

```python
from __future__ import annotations

import weakref
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from rakit_core.actions import ActionDefinition, ActionScope


class ActionIntent(StrEnum):
    DEFAULT = "default"
    PRIMARY = "primary"
    DANGER = "danger"


@dataclass(frozen=True, slots=True)
class ActionPresentation:
    intent: ActionIntent = ActionIntent.DEFAULT


_DEFAULT_ACTION_PRESENTATION = ActionPresentation()
_ACTION_PRESENTATIONS: dict[
    int,
    tuple[weakref.ReferenceType[ActionDefinition], ActionPresentation],
] = {}


def normalize_action_presentations(
    values: Mapping[str, ActionPresentation],
) -> Mapping[str, ActionPresentation]:
    normalized: dict[str, ActionPresentation] = {}
    for action_id, presentation in values.items():
        if not isinstance(action_id, str) or not action_id.strip():
            raise ValueError("Action presentation ids must be non-empty strings")
        if not isinstance(presentation, ActionPresentation):
            raise TypeError("Action presentations must contain ActionPresentation values")
        normalized[action_id] = presentation
    return MappingProxyType(normalized)
```

Add `validate_action_presentations(actions, presentations)` that:
1. rejects ids not present in `actions`;
2. groups declared actions by `ActionScope`;
3. counts only configured `PRIMARY` actions per scope;
4. raises `ValueError` when any scope has more than one primary.

Add binding/lookup using the same `id(definition) + weakref` pattern already used by `resource_presentation.py`.

- [ ] **Step 2: Extend `ResourceWebPresentation` without breaking existing construction**

Keep `filters` unchanged and add:

```python
actions: Mapping[str, ActionPresentation] = field(default_factory=dict)
```

In `__post_init__`, normalize it through `normalize_action_presentations()` and assign the `MappingProxyType` with `object.__setattr__`.

- [ ] **Step 3: Add `PageWebPresentation`**

```python
@dataclass(frozen=True, slots=True)
class PageWebPresentation:
    actions: Mapping[str, ActionPresentation] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "actions", normalize_action_presentations(self.actions))
```

Do not add page layout/color configuration.

- [ ] **Step 4: Export the three public types**

In `packages/rakit/src/rakit/__init__.py`, import/export:

```python
from rakit_web.action_presentation import ActionIntent, ActionPresentation
from rakit_web.page_presentation import PageWebPresentation
```

Keep every existing export intact.

- [ ] **Step 5: Run non-test structural verification**

```powershell
uv run ruff format packages/rakit-web/src/rakit_web/action_presentation.py packages/rakit-web/src/rakit_web/page_presentation.py packages/rakit-web/src/rakit_web/resource_presentation.py packages/rakit/src/rakit/__init__.py
uv run ruff check packages/rakit-web/src/rakit_web/action_presentation.py packages/rakit-web/src/rakit_web/page_presentation.py packages/rakit-web/src/rakit_web/resource_presentation.py packages/rakit/src/rakit/__init__.py
uv run ty check
```

Expected: clean; existing callers that construct `ResourceWebPresentation(filters=...)` still type-check.

- [ ] **Step 6: Commit the contract**

```powershell
git add packages/rakit-web/src/rakit_web/action_presentation.py packages/rakit-web/src/rakit_web/page_presentation.py packages/rakit-web/src/rakit_web/resource_presentation.py packages/rakit/src/rakit/__init__.py
git commit -m "feat(web): add action presentation policy"
```

---

### Task 2: Validate and Bind Presentation During Registration

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/dashboard_admin.py`
- Modify: `packages/rakit-web/src/rakit_web/admin.py`

**Interfaces:**
- Consumes: `resource_actions()`, `register_public_page()`, `validate_action_presentations()`.
- Produces: backward-compatible `Admin.register(..., web=ResourceWebPresentation(...))` and `Admin.register_page(..., web=PageWebPresentation(...))`.

- [ ] **Step 1: Validate resource action presentation before `super().register()` mutates state**

In `dashboard_admin.Admin.register`, derive the exact declarations once:

```python
declared_actions = resource_actions(
    admin_cls,
    existing_action_ids={str(action.action_id) for action in self.builder.actions},
)
validate_action_presentations(declared_actions, presentation.actions)
```

Convert `ValueError` / `TypeError` from presentation validation into the existing fail-closed `RakitError(code=CONFIG_INVALID_RESOURCE_POLICY, status_code=500)` shape with details containing `resource_id` and a stable `reason` such as `invalid_web_action_presentation`.

After `super().register(admin_cls)` succeeds, bind only configured declarations:

```python
for action in declared_actions:
    configured = presentation.actions.get(str(action.action_id))
    if configured is not None:
        bind_action_web_presentation(action, configured)
```

Do not bind defaults eagerly; lookup already returns `_DEFAULT_ACTION_PRESENTATION`.

- [ ] **Step 2: Extend page registration atomically**

Change the signature to:

```python
def register_page(
    self,
    definition: PageDefinition,
    *,
    actions: tuple[ActionDefinition, ...] = (),
    web: PageWebPresentation | None = None,
) -> None:
```

Before `register_public_page(...)`, validate:

```python
presentation = web or PageWebPresentation()
validate_action_presentations(actions, presentation.actions)
```

If validation fails, raise `RakitError(code=ErrorCode.CONFIG_INVALID, status_code=500)` with `page_id` and `reason="invalid_web_action_presentation"`. Only after validation succeeds call `register_public_page`; then bind configured PAGE actions.

- [ ] **Step 3: Verify registration remains source-compatible**

Run an import/compile smoke check without adding tests yet:

```powershell
uv run python -c "from rakit import Admin, ResourceWebPresentation, PageWebPresentation, ActionPresentation, ActionIntent; print(ActionIntent.DANGER.value)"
uv run ty check
```

Expected output contains `danger`; no type errors.

- [ ] **Step 4: Commit registration wiring**

```powershell
git add packages/rakit-web/src/rakit_web/dashboard_admin.py packages/rakit-web/src/rakit_web/admin.py
git commit -m "feat(web): bind action presentation at registration"
```

---

### Task 3: Add Reusable Action Hierarchy and Permission-Filtered Entry Points

**Files:**
- Create: `packages/rakit-web/src/rakit_web/templates/components/actions.html`
- Modify: `packages/rakit-web/src/rakit_web/admin.py`
- Modify: `packages/rakit-web/src/rakit_web/bulk_admin.py`
- Modify: `packages/rakit-web/src/rakit_web/resource_routes.py`
- Modify: `packages/rakit-web/src/rakit_web/templates/resources/list.html`
- Modify: `packages/rakit-web/src/rakit_web/templates/resources/detail.html`
- Modify: `packages/rakit-web/src/rakit_web/templates/resources/_table.html`

**Interfaces:**
- Consumes: compiled action routes, exact compiled permission, `action_web_presentation()`.
- Produces: template action views with `label`, `url`, `intent`; record links additionally receive encoded identity from the resource route.

- [ ] **Step 1: Install one permission-aware action-link helper on the shared template environment**

In `Admin.asgi()` after `templates = build_templates(...)`, register a synchronous Jinja global named `rakit_actions` that accepts `(request, owner_id, scope, identity_token="")`.

It must:
1. read the principal from request state;
2. return `()` for anonymous principals;
3. iterate only `compiled.action_routes` matching requested owner/scope;
4. require `compiled_action.permission.matches(principal, superuser_bypass=...)`;
5. substitute `{identity}` only for RECORD scope using the already encoded `identity_token`;
6. return mounted URLs through `mounted_path(request, route.path)`;
7. attach `action_web_presentation(definition).intent.value`.

Do not call availability resolvers here. Availability remains evaluated by the action GET/POST pipeline; the entry-point helper is only a permission-filtered navigation surface.

- [ ] **Step 2: Extend existing bulk action view data rather than creating a second permission model**

Change `bulk_action_views()` in `bulk_admin.py` to return:

```python
{
    "label": str(compiled_action.definition.label),
    "url": mounted_path(request, route.path),
    "intent": action_web_presentation(compiled_action.definition).intent.value,
}
```

Keep its exact compiled permission filter.

- [ ] **Step 3: Pass `encoded_identity` to record detail templates**

Add it to `resource_detail` context in `resource_routes.py` without altering identity decoding or CRUD URLs.

- [ ] **Step 4: Create the reusable Jinja action macro**

`templates/components/actions.html` implements two macros:

```jinja
{% macro action_link(action, secondary=false) -%}
  <a
    href="{{ action.url }}"
    class="rakit-button{% if action.intent == 'danger' %} rakit-button-danger{% elif secondary %} rakit-button-secondary{% endif %}"
  >{{ action.label }}</a>
{%- endmacro %}

{% macro action_group(actions, label='Actions') -%}
  {# One total action => direct. Multiple => PRIMARY direct, remaining in native details. #}
{%- endmacro %}
```

Deterministic grouping rule:
- zero actions: render nothing;
- one action: direct button/link using its intent;
- multiple actions: render the single PRIMARY directly when present; put every remaining DEFAULT/DANGER action under a native `<details>` “More” menu;
- place a top border before the first DANGER menu item when defaults precede it;
- if there is no PRIMARY, all actions live in “More” rather than arbitrarily promoting one.

The menu must use `<summary>` and links/buttons so no JavaScript is required.

- [ ] **Step 5: Add RESOURCE and RECORD action groups**

In `resources/list.html`:

```jinja
{% set resource_actions = rakit_actions(request, resource.resource_id, 'resource') %}
```

Place them beside the Create CTA using the shared macro.

In `resources/detail.html`:

```jinja
{% set record_actions = rakit_actions(request, resource.resource_id, 'record', encoded_identity) %}
```

Keep built-in Edit/Delete controls. Treat Delete as an existing destructive CRUD action and render custom RECORD actions with the shared macro adjacent to them. Do not route built-in Delete through `ActionPresentation`.

- [ ] **Step 6: Replace the bulk button row with a selection-aware hierarchy**

Keep the existing single GET form wrapping selection checkboxes. Before any selection, show neutral copy `0 selected` and keep bulk submit controls disabled using native `disabled`.

Within the same form:
- one bulk action => direct button;
- multiple actions => PRIMARY direct if configured, others in `<details>`;
- danger entries use danger treatment;
- `Clear selection` is a button with progressive JS enhancement only if already supported; absence of JS must not prevent changing selections manually.

Do not alter the `selected` checkbox names/values or action `formaction` URLs.

- [ ] **Step 7: Run template/build smoke verification**

```powershell
bun run css:build
uv run python -c "from rakit_web.resource_routes import build_templates; build_templates(())"
uv run ruff format --check .
uv run ruff check .
uv run ty check
```

- [ ] **Step 8: Commit entry-point hierarchy**

```powershell
git add packages/rakit-web/src/rakit_web/templates/components/actions.html packages/rakit-web/src/rakit_web/admin.py packages/rakit-web/src/rakit_web/bulk_admin.py packages/rakit-web/src/rakit_web/resource_routes.py packages/rakit-web/src/rakit_web/templates/resources/list.html packages/rakit-web/src/rakit_web/templates/resources/detail.html packages/rakit-web/src/rakit_web/templates/resources/_table.html packages/rakit-web/src/rakit_web/static/rakit.css
git commit -m "feat(web): add action hierarchy to resource surfaces"
```

---

### Task 4: Mature Action Forms, Preview/Confirmation, and Bulk Review

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/resource_routes.py`
- Modify: `packages/rakit-web/src/rakit_web/action_routes.py`
- Modify: `packages/rakit-web/src/rakit_web/bulk_routes.py`
- Modify: `packages/rakit-web/src/rakit_web/templates/actions/_form.html`
- Modify: `packages/rakit-web/src/rakit_web/templates/actions/_confirm.html`
- Modify: `packages/rakit-web/src/rakit_web/templates/actions/bulk.html`
- Modify: `packages/rakit-web/src/rakit_web/assets/rakit.css`
- Regenerate: `packages/rakit-web/src/rakit_web/static/rakit.css`

**Interfaces:**
- Consumes: existing `_field_views`, `ActionPreview`, `ActionAvailabilityDecision`, `BulkPolicy`, confirmation tokens.
- Produces: semantic-token action surfaces and intent-aware submit buttons.

- [ ] **Step 1: Register `rakit_action_web_presentation` in `build_templates()`**

Add:

```python
globals_["rakit_action_web_presentation"] = action_web_presentation
```

This gives all built-in templates safe read access to the exact action presentation binding.

- [ ] **Step 2: Add presentation and safe review fields to action template context**

Where action form/confirm template arguments are built, include:

```python
"action_presentation": action_web_presentation(action),
```

Do not change token generation or submitted field canonicalization.

- [ ] **Step 3: Replace old slate/red utility usage in `_form.html`**

Use semantic Rakit tokens and the mature form rhythm from `templates/forms/form.html`:
- breadcrumb/context heading;
- `rakit-alert rakit-alert-danger` for validation summary;
- `rakit-field-help` for descriptions;
- `rakit-error` for field-local errors;
- disabled state panel using neutral semantic styling;
- intent-aware submit button: danger only when `action_presentation.intent.value == 'danger'`; otherwise normal primary button.

Keep all hidden token inputs byte-for-byte equivalent in names and values.

- [ ] **Step 4: Turn `_confirm.html` into an authoritative review surface**

Render:
- preview title or action label;
- preview description;
- preview impact inside warning/neutral semantic note;
- safe confirmation fields as a `<dl>` when present;
- explicit copy that execution occurs only after submission;
- Cancel/Back plus intent-aware confirm CTA.

Remove the unconditional `rakit-button-danger`; danger comes only from `ActionPresentation`.

- [ ] **Step 5: Surface existing bulk execution semantics**

In `bulk_routes.py`, include template context values already present in `action.bulk_policy`, specifically:
- `selected_count`;
- execution policy value (`atomic` / `best_effort` when available from the existing policy object);
- synchronous maximum;
- whether confirmation is required by current bulk rules.

Do not invent partial-success semantics not present in `BulkPolicy` / execution result.

In `bulk.html`, render selected count prominently and show the execution policy only when it adds information. Use intent-aware final CTA.

- [ ] **Step 6: Add only stable reusable CSS primitives**

If templates need reusable menu/presentation styling, add classes such as `.rakit-action-menu` / `.rakit-action-menu-item` only if used by resource, record, and bulk surfaces. Keep one-off layout in template utilities.

Rebuild:

```powershell
bun run css:build
```

- [ ] **Step 7: Verify no source-runtime semantic changes were introduced**

```powershell
uv run ruff format --check .
uv run ruff check .
uv run ty check
```

Manually inspect diffs in `action_routes.py` / `bulk_routes.py`: changes must be template-context additions only, not authorization/idempotency/concurrency logic.

- [ ] **Step 8: Commit the mature action surfaces**

```powershell
git add packages/rakit-web/src/rakit_web/resource_routes.py packages/rakit-web/src/rakit_web/action_routes.py packages/rakit-web/src/rakit_web/bulk_routes.py packages/rakit-web/src/rakit_web/templates/actions packages/rakit-web/src/rakit_web/assets/rakit.css packages/rakit-web/src/rakit_web/static/rakit.css
git commit -m "feat(web): mature action and bulk review surfaces"
```

---

### Task 5: Exercise UI-06A in `examples/ui_showcase`

**Files:**
- Modify: `examples/ui_showcase/main.py`

**Interfaces:**
- Consumes: new public presentation types.
- Produces: deterministic browser states for normal, primary, danger, disabled, form, preview, confirmation, success, and bulk actions.

- [ ] **Step 1: Import the public presentation types**

Add to the existing `from rakit import (...)` list:

```python
ActionIntent,
ActionPresentation,
PageWebPresentation,
```

- [ ] **Step 2: Mark `refund_order` as danger through `ResourceWebPresentation`**

For `OrdersAdmin`, register with:

```python
web=ResourceWebPresentation(
    actions={
        "refund_order": ActionPresentation(intent=ActionIntent.DANGER),
    }
)
```

Do not add `danger` to the core `ActionDefinition`.

- [ ] **Step 3: Add deterministic additional showcase actions**

Add at least:
- one DEFAULT record action such as `duplicate_order`;
- one PRIMARY resource action such as `export_orders` only if the scenario has a meaningful direct CTA;
- one DISABLED action whose availability resolver returns `ActionAvailabilityDecision.disabled("Warehouse sync is currently unavailable.")`;
- one typed action form with validation;
- one BULK safe action;
- one BULK danger action with confirmation.

Use existing in-memory/domain executors; do not add a second action engine for the example.

- [ ] **Step 4: Ensure `/ui-lab` or existing resource routes expose every acceptance state**

The maintainer must be able to navigate to each state with deterministic data and demo credentials.

- [ ] **Step 5: Run showcase manually**

```powershell
uv run python -m examples.ui_showcase.main
```

Browser acceptance checklist before tests:
- resource action overflow hierarchy;
- record normal + danger action hierarchy;
- disabled reason after opening action;
- action form validation layout;
- preview/confirmation review screen;
- bulk 1 selected and many selected;
- bulk safe vs danger hierarchy;
- no-JS flow by disabling JavaScript and submitting through ordinary forms.

- [ ] **Step 6: Commit showcase scenarios**

```powershell
git add examples/ui_showcase/main.py
git commit -m "feat(examples): cover advanced action states"
```

---

### Task 6: Add Regression Tests Last and Run the UI-06A Gate

**Files:**
- Create: `packages/rakit-web/tests/test_advanced_ui_maturity.py`
- Modify as required by new assertions only: `packages/rakit-web/tests/test_actions.py`
- Modify as required by new assertions only: `packages/rakit-web/tests/test_bulk_actions.py`
- Modify: `packages/rakit-web/tests/test_bulk_list_ui.py`

**Interfaces:**
- Consumes: completed UI-06A behavior.
- Produces: durable contract coverage without changing the implementation.

- [ ] **Step 1: Add public presentation contract tests**

Use declaration-level tests such as:

```python
def test_resource_web_presentation_rejects_unknown_action_id() -> None:
    class Orders(ResourceAdmin):
        resource_id = "orders"
        path = "/orders"
        label = "Orders"
        singular_label = "Order"
        data_source = _DataSource()
        actions = (_action("refund", ActionScope.RECORD),)

    admin = _admin()
    with pytest.raises(RakitError) as exc_info:
        admin.register(
            Orders,
            web=ResourceWebPresentation(
                actions={"missing": ActionPresentation(intent=ActionIntent.DANGER)}
            ),
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.details["reason"] == "invalid_web_action_presentation"
```

Add a separate test proving two PRIMARY RECORD actions fail while one PRIMARY RECORD + one PRIMARY RESOURCE action is valid.

- [ ] **Step 2: Add default compatibility tests**

Assert:

```python
assert action_web_presentation(existing_action).intent is ActionIntent.DEFAULT
```

and existing `ResourceWebPresentation(filters=...)` remains constructible.

- [ ] **Step 3: Extend bulk list UI tests**

Verify unauthorized principals still see no labels/URLs, and danger/default intent only changes markup for authorized actions. Keep the existing exact permission expectations.

- [ ] **Step 4: Add HTML maturity assertions**

In `test_advanced_ui_maturity.py`, render representative action form/confirm/bulk pages and assert:
- semantic `text-rakit-*` / `rakit-alert-*` classes are used;
- unconditional old `text-slate-*`, `border-amber-200`, `bg-red-50` patterns are absent from these templates;
- danger confirm button appears only when the bound presentation intent is danger;
- disabled reason is rendered;
- confirmation hidden tokens remain present.

- [ ] **Step 5: Run focused tests**

```powershell
uv run pytest packages/rakit-web/tests/test_advanced_ui_maturity.py packages/rakit-web/tests/test_actions.py packages/rakit-web/tests/test_bulk_actions.py packages/rakit-web/tests/test_bulk_list_ui.py -q
```

Expected: PASS.

- [ ] **Step 6: Run static and full verification**

```powershell
bun run css:build
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
uv run mkdocs build --strict
uv run python scripts/check_artifacts.py
git status --short
```

Expected: all green; only intentional source/test/generated-CSS changes remain.

- [ ] **Step 7: Commit tests**

```powershell
git add packages/rakit-web/tests/test_advanced_ui_maturity.py packages/rakit-web/tests/test_actions.py packages/rakit-web/tests/test_bulk_actions.py packages/rakit-web/tests/test_bulk_list_ui.py
git commit -m "test(web): cover mature action presentation"
```

- [ ] **Step 8: Open the UI-06A PR against `ui-06-advanced-operations` and require fresh CI + browser acceptance**

The slice is complete only when PR CI is green and the maintainer accepts the browser states. Do not merge directly to `main`.
