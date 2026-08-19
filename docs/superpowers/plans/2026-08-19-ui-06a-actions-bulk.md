# UI-06A Actions & Bulk Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add explicit Web-only action hierarchy and mature action/bulk interaction surfaces while preserving the existing action execution, authorization, availability, CSRF, idempotency, transaction, confirmation, and concurrency contracts.

**Architecture:** Keep `ActionDefinition` unchanged in `rakit-core`. Add immutable Web-only `ActionIntent` / `ActionPresentation` bindings keyed to the exact `ActionDefinition` objects, extend `ResourceWebPresentation` and add `PageWebPresentation`, and build context-aware server-side action entry views for PAGE/RESOURCE/RECORD surfaces. BULK launch controls remain selection-blind until selected identities reach the server; the bulk GET resolves per-target availability before any action form is rendered. Native `<details>` provides overflow without JavaScript, and the baseline bulk form remains submit-able without JavaScript.

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
- Permission checks hide action entry points the principal cannot invoke; POST execution still independently authorizes and re-checks availability.
- PAGE/RESOURCE/RECORD entry views resolve availability with the same principal/target context available to the action GET: `HIDDEN` is omitted, `DISABLED` is visible but non-invokable with its safe reason, `AVAILABLE` links normally.
- BULK list launch controls cannot evaluate per-record availability before selection reaches the server. They therefore remain permission-filtered at list time; the first context-bearing bulk GET must return 404 for any HIDDEN target decision and a disabled review surface for DISABLED before execution is possible. POST still re-checks every target against fresh state.
- Preserve signed CSRF, submission, confirmation, and concurrency tokens exactly.
- Preserve action idempotency receipt/replay semantics exactly.
- Preserve `ActionSuccess`, `ActionRedirect`, `ActionRefresh`, `ActionRejected`, `ActionRendered`, `ActionAdvancedResponse`, and validation HTTP/HTMX semantics.
- Edit `packages/rakit-web/src/rakit_web/assets/rakit.css`; regenerate `packages/rakit-web/src/rakit_web/static/rakit.css` with `bun run css:build`. Never hand-edit generated CSS.
- Do not introduce a JavaScript-only action path. Overflow menus must work with native `<details>`.
- Bulk action controls in base HTML must remain usable without JavaScript. JavaScript may update selected-count text and temporarily disable controls while selection is empty, but failure/absence of JS must leave ordinary form submission possible.
- No release/tag/PyPI action.

---

## File Map

### Create
- `packages/rakit-web/src/rakit_web/action_presentation.py` — shared Web-only action intent, immutable binding registry, and validation helper.
- `packages/rakit-web/src/rakit_web/page_presentation.py` — `PageWebPresentation` container for PAGE action presentation.
- `packages/rakit-web/src/rakit_web/action_views.py` — Web-internal async PAGE/RESOURCE/RECORD entry-view resolver.
- `packages/rakit-web/src/rakit_web/templates/components/actions.html` — reusable action-group / overflow macros.
- `packages/rakit-web/tests/test_advanced_ui_maturity.py` — slice-level presentation contract tests, added only after feature behavior exists.

### Modify
- `packages/rakit-web/src/rakit_web/resource_presentation.py` — add immutable `actions` mapping to `ResourceWebPresentation`.
- `packages/rakit-web/src/rakit_web/dashboard_admin.py` — validate and bind resource action presentation before/after normal registration.
- `packages/rakit-web/src/rakit_web/admin.py` — extend `register_page(..., web=...)`; wire action-view providers into resource/page bindings.
- `packages/rakit-web/src/rakit_web/page_admin.py` — add optional async PAGE action-view provider to `PageBinding`/page route composition.
- `packages/rakit-web/src/rakit_web/page_routes.py` — await PAGE action views and pass them to templates without changing page execution.
- `packages/rakit-web/src/rakit_web/action_routes.py` — expose action presentation to form/confirm templates; keep execution unchanged.
- `packages/rakit-web/src/rakit_web/bulk_admin.py` — include intent in permission-filtered bulk list launch views.
- `packages/rakit-web/src/rakit_web/bulk_routes.py` — selection-aware GET availability presentation and existing bulk policy context.
- `packages/rakit-web/src/rakit_web/resource_routes.py` — await RESOURCE/RECORD action views; pass encoded identity and action views to templates.
- `packages/rakit-web/src/rakit_web/templates/resources/list.html` — RESOURCE action group in page header.
- `packages/rakit-web/src/rakit_web/templates/resources/detail.html` — RECORD action group merged with Edit/Delete hierarchy.
- `packages/rakit-web/src/rakit_web/templates/resources/_table.html` — mature selection-aware BULK action bar.
- `packages/rakit-web/src/rakit_web/templates/actions/_form.html` — semantic action form styling.
- `packages/rakit-web/src/rakit_web/templates/actions/_confirm.html` — authoritative review/confirmation surface.
- `packages/rakit-web/src/rakit_web/templates/actions/bulk.html` — selected-count, availability, impact, execution-policy presentation.
- `packages/rakit-web/src/rakit_web/assets/rakit.css` — stable action menu / bulk bar primitives only where reusable.
- `packages/rakit-web/src/rakit_web/static/rakit.css` — generated CSS.
- `packages/rakit-web/src/rakit_web/static/rakit-ui.js` — optional selected-count/disabled-state enhancement only; no critical bulk logic.
- `packages/rakit/src/rakit/__init__.py` — public exports for `ActionIntent`, `ActionPresentation`, and `PageWebPresentation`.
- `examples/ui_showcase/main.py` — deterministic normal/danger/disabled/form/preview/bulk scenarios.
- Existing regression suites: `packages/rakit-web/tests/test_actions.py`, `test_bulk_actions.py`, `test_bulk_list_ui.py`, `test_public_resource_composition.py`, `test_public_page_composition.py`.

---

### Task 1: Add Web-only Action Presentation Contracts

**Files:**
- Create: `packages/rakit-web/src/rakit_web/action_presentation.py`
- Create: `packages/rakit-web/src/rakit_web/page_presentation.py`
- Modify: `packages/rakit-web/src/rakit_web/resource_presentation.py`
- Modify: `packages/rakit/src/rakit/__init__.py`

**Interfaces:**
- Consumes: `ActionDefinition.action_id`, `ActionDefinition.scope`.
- Produces: `ActionIntent`, `ActionPresentation`, immutable presentation mappings, binding/lookup, `PageWebPresentation`, and `ResourceWebPresentation.actions`.

- [ ] **Step 1: Create the immutable shared action presentation contract**

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
```

Add `normalize_action_presentations(values)` that validates non-empty string ids and `ActionPresentation` values and returns `MappingProxyType`.

Add `validate_action_presentations(actions, presentations)` that:
1. rejects presentation ids not present in `actions`;
2. groups the declared actions by `ActionScope`;
3. counts only configured `PRIMARY` actions per scope;
4. raises `ValueError` when any scope has more than one configured primary.

Add `bind_action_web_presentation()` / `action_web_presentation()` using the same `id(definition) + weakref` cleanup pattern as `resource_presentation.py`.

- [ ] **Step 2: Extend `ResourceWebPresentation` backward-compatibly**

Keep `filters` unchanged and add:

```python
actions: Mapping[str, ActionPresentation] = field(default_factory=dict)
```

Normalize it in `__post_init__`. Existing `ResourceWebPresentation(filters=...)` must remain valid.

- [ ] **Step 3: Add `PageWebPresentation`**

```python
@dataclass(frozen=True, slots=True)
class PageWebPresentation:
    actions: Mapping[str, ActionPresentation] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "actions", normalize_action_presentations(self.actions))
```

Do not add page layout/color configuration.

- [ ] **Step 4: Export only the intended public types**

In `packages/rakit/src/rakit/__init__.py`, export:

```python
from rakit_web.action_presentation import ActionIntent, ActionPresentation
from rakit_web.page_presentation import PageWebPresentation
```

Do not export the binding registry or later internal action-view types.

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
- Produces: backward-compatible `Admin.register(..., web=...)` and `Admin.register_page(..., web=...)` with atomic fail-closed validation.

- [ ] **Step 1: Validate resource action presentation before `super().register()` mutates state**

In `dashboard_admin.Admin.register`, derive the declarations before the mutation:

```python
declared_actions = resource_actions(
    admin_cls,
    existing_action_ids={str(action.action_id) for action in self.builder.actions},
)
validate_action_presentations(declared_actions, presentation.actions)
```

Convert presentation `ValueError` / `TypeError` into the existing `RakitError(code=CONFIG_INVALID_RESOURCE_POLICY, status_code=500)` shape with `resource_id` and `reason="invalid_web_action_presentation"`.

After `super().register(admin_cls)` succeeds, bind only explicitly configured actions from `declared_actions`. `resource_actions()` returns the same immutable `ActionDefinition` objects that `super().register()` adds to the builder, so the identity binding remains exact.

- [ ] **Step 2: Extend page registration atomically**

Change the public signature to:

```python
def register_page(
    self,
    definition: PageDefinition,
    *,
    actions: tuple[ActionDefinition, ...] = (),
    web: PageWebPresentation | None = None,
) -> None:
```

Validate `presentation = web or PageWebPresentation()` against `actions` **before** `register_public_page(...)`. On failure raise `RakitError(code=ErrorCode.CONFIG_INVALID, status_code=500)` with `page_id` and `reason="invalid_web_action_presentation"`. After registration, bind only configured PAGE actions.

- [ ] **Step 3: Verify source compatibility**

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

### Task 3: Build Context-aware PAGE/RESOURCE/RECORD Action Entry Views

**Files:**
- Create: `packages/rakit-web/src/rakit_web/action_views.py`
- Create: `packages/rakit-web/src/rakit_web/templates/components/actions.html`
- Modify: `packages/rakit-web/src/rakit_web/admin.py`
- Modify: `packages/rakit-web/src/rakit_web/resource_routes.py`
- Modify: `packages/rakit-web/src/rakit_web/page_admin.py`
- Modify: `packages/rakit-web/src/rakit_web/page_routes.py`
- Modify: `packages/rakit-web/src/rakit_web/templates/resources/list.html`
- Modify: `packages/rakit-web/src/rakit_web/templates/resources/detail.html`

**Interfaces:**
- Consumes: compiled action routes, exact compiled permission, principal, optional record identity/record, `resolve_availability()`, `action_web_presentation()`.
- Produces: immutable Web action views with `label`, mounted `url`, `intent`, `availability`, and safe `reason`.

- [ ] **Step 1: Define a Web-internal action view**

In `action_views.py`:

```python
@dataclass(frozen=True, slots=True)
class ActionView:
    action_id: str
    label: str
    url: str
    intent: ActionIntent
    availability: ActionAvailability
    reason: str | None = None
```

Do not export it from `rakit`.

- [ ] **Step 2: Implement an async resolver using the same target context as action GET**

Create an async function that receives:

```python
async def resolve_action_views(
    *,
    request: Request,
    routes: tuple[tuple[RouteDefinition, CompiledActionDefinition], ...],
    owner_id: str,
    scope: ActionScope,
    superuser_bypass: bool,
    identity: RecordIdentity | None = None,
    record: object | None = None,
) -> tuple[ActionView, ...]:
    ...
```

For each matching action:
1. require an authenticated principal;
2. require exact `compiled.permission.matches(...)`;
3. require `principal.subject_id` for an operation authorization;
4. construct `OperationAuthorization.for_requirement(...)` with the same owner/action id and optional target identity as action routes;
5. build `ActionContext(definition=..., scope=..., identity=..., record=..., authorization=..., principal=...)`;
6. `await resolve_availability(...)`;
7. omit `HIDDEN` entirely;
8. include DISABLED with its safe reason and AVAILABLE normally;
9. mount route URL, substituting `{identity}` only for RECORD scope;
10. attach `action_web_presentation(definition).intent`.

Do not run preview/executor or issue action tokens here.

- [ ] **Step 3: Make resource routes await the resolver before template rendering**

Extend `ResourceBinding` with an optional async callback:

```python
ActionViewProvider = Callable[
    [Request, ActionScope, RecordIdentity | None, object | None],
    Awaitable[tuple[ActionView, ...]],
]

action_views: ActionViewProvider | None = None
```

In `resource_list`, call with `(RESOURCE, None, None)` and add `resource_actions` to context.

In `resource_detail`, after record load and identity decode, call with `(RECORD, identity, record)` and add `record_actions` plus `encoded_identity` to context.

In `Admin.asgi()`, create the provider before building resource routes; it may close over `compiled_app.action_routes`, `self._superuser_bypass`, and the resource id. No write-token service is needed for view resolution.

- [ ] **Step 4: Make page routes await the same resolver**

Extend `PageBinding`/`build_admin_page_routes` with an optional PAGE action-view provider. Before rendering a page template, resolve PAGE actions with no record target and add `page_actions` to context.

Do not change page handler execution, PRG, or idempotency.

- [ ] **Step 5: Create deterministic native action macros**

`templates/components/actions.html` implements:
- zero actions => nothing;
- one AVAILABLE action => direct link/button;
- one DISABLED action => disabled button/non-link plus safe reason;
- multiple => single PRIMARY visible when present; all remaining DEFAULT/DANGER items in native `<details>` “More”;
- DISABLED items remain non-links and expose reason;
- DANGER entries are visually separated inside overflow;
- if no PRIMARY exists, do not arbitrarily promote a DEFAULT; all actions live in More.

The macro must not require JavaScript.

- [ ] **Step 6: Add RESOURCE and RECORD actions to mature headers**

In `resources/list.html`, render `resource_actions` beside Create.

In `resources/detail.html`, render `record_actions` beside existing Edit/Delete. Built-in Delete remains the existing destructive CRUD path and is **not** routed through `ActionPresentation`.

- [ ] **Step 7: Run structural verification**

```powershell
uv run ruff format packages/rakit-web/src/rakit_web/action_views.py packages/rakit-web/src/rakit_web/admin.py packages/rakit-web/src/rakit_web/resource_routes.py packages/rakit-web/src/rakit_web/page_admin.py packages/rakit-web/src/rakit_web/page_routes.py
uv run ruff check packages/rakit-web/src/rakit_web/action_views.py packages/rakit-web/src/rakit_web/admin.py packages/rakit-web/src/rakit_web/resource_routes.py packages/rakit-web/src/rakit_web/page_admin.py packages/rakit-web/src/rakit_web/page_routes.py
uv run ty check
uv run python -c "from rakit_web.resource_routes import build_templates; build_templates(()).env.get_template('components/actions.html')"
```

- [ ] **Step 8: Commit context-aware action entry views**

```powershell
git add packages/rakit-web/src/rakit_web/action_views.py packages/rakit-web/src/rakit_web/admin.py packages/rakit-web/src/rakit_web/resource_routes.py packages/rakit-web/src/rakit_web/page_admin.py packages/rakit-web/src/rakit_web/page_routes.py packages/rakit-web/src/rakit_web/templates/components/actions.html packages/rakit-web/src/rakit_web/templates/resources/list.html packages/rakit-web/src/rakit_web/templates/resources/detail.html
git commit -m "feat(web): add context-aware action hierarchy"
```

---

### Task 4: Mature BULK Launch, Selection-aware Availability, Forms, and Review

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/bulk_admin.py`
- Modify: `packages/rakit-web/src/rakit_web/bulk_routes.py`
- Modify: `packages/rakit-web/src/rakit_web/templates/resources/_table.html`
- Modify: `packages/rakit-web/src/rakit_web/templates/actions/_form.html`
- Modify: `packages/rakit-web/src/rakit_web/templates/actions/_confirm.html`
- Modify: `packages/rakit-web/src/rakit_web/templates/actions/bulk.html`
- Modify: `packages/rakit-web/src/rakit_web/assets/rakit.css`
- Modify optionally: `packages/rakit-web/src/rakit_web/static/rakit-ui.js`
- Regenerate: `packages/rakit-web/src/rakit_web/static/rakit.css`

**Interfaces:**
- Consumes: permission-filtered bulk declarations, selected identities, existing `_load_selection`, per-target `resolve_availability`, `BulkPolicy`, action presentation, confirmation/concurrency/idempotency tokens.
- Produces: no-JS-safe list launch controls plus selection-aware bulk form availability/review.

- [ ] **Step 1: Add intent to the existing permission-filtered bulk launcher views**

`bulk_action_views()` continues to filter exact compiled permission and returns:

```python
{
    "label": str(compiled_action.definition.label),
    "url": mounted_path(request, route.path),
    "intent": action_web_presentation(compiled_action.definition).intent.value,
}
```

Do not pretend list-time bulk launcher availability is target-aware; no selection has reached the server yet.

- [ ] **Step 2: Keep base bulk controls functional without JavaScript**

In `_table.html`:
- keep the existing GET form and `name="selected"` checkboxes;
- render selected count text initially as `0 selected` or `Select records to run a bulk action`;
- **do not** put native `disabled` on every bulk action submit control in the base HTML;
- one action => direct submit button;
- multiple => PRIMARY direct if configured, remaining actions in native `<details>`;
- danger action uses danger treatment;
- every button keeps its real `formaction` so selecting checkboxes and submitting works with JavaScript disabled.

Optional JS may observe selection and set disabled while count is zero, but it must remove/recompute that state on startup and must never be required for submission.

- [ ] **Step 3: Split bulk GET eligibility from POST execution re-check**

Add a helper that loads per-target authorization/availability decisions without requiring AVAILABLE immediately:

```python
async def _target_context_decisions(...) -> tuple[tuple[ActionContext, ActionAvailabilityDecision], ...]:
    ...
```

It uses the same per-target exact authorization and fresh loaded records.

Bulk GET behavior after selection is known:
- any HIDDEN => return safe 404 (`Resource was not found`) and do not render action label/form;
- else any DISABLED => render `actions/bulk.html` with `availability="disabled"`, first safe disabled reason, no executable final submit control;
- all AVAILABLE => normal bulk form.

Bulk POST continues to call the strict AVAILABLE path (`_target_contexts` or equivalent) immediately before execution and returns conflict if eligibility changed.

- [ ] **Step 4: Add presentation/policy context to bulk form**

`_form_args` adds:

```python
"action_presentation": action_web_presentation(action),
"availability": availability,
"availability_reason": availability_reason,
"execution_policy": action.bulk_policy.execution.value,
"synchronous_maximum": action.bulk_policy.synchronous_maximum,
```

Use the exact existing `BulkPolicy` attribute names from `rakit_core.bulk`; do not rename core fields. Keep `selected_count`, selected identities, concurrency tokens, confirmation token, CSRF, submission token, fields, form action, cancel URL unchanged.

- [ ] **Step 5: Mature action form/confirm templates**

`_form.html`:
- semantic Rakit tokens and mature form rhythm;
- `rakit-alert-danger` summary + field-local `rakit-error`;
- safe availability-disabled panel/reason;
- intent-aware final CTA (danger only for DANGER presentation);
- preserve all hidden tokens exactly.

`_confirm.html`:
- authoritative preview title/description/impact;
- safe submitted confirmation fields as `<dl>`;
- back/cancel affordance;
- intent-aware final CTA;
- remove unconditional danger styling.

- [ ] **Step 6: Mature `actions/bulk.html`**

Render:
- action label;
- selected count prominently;
- execution policy only when useful;
- confirmation/impact warning when required;
- typed fields/validation using semantic tokens;
- disabled availability reason with no execute control;
- otherwise intent-aware final CTA;
- all existing hidden selected/concurrency/confirmation/CSRF/submission values unchanged.

- [ ] **Step 7: Add only reusable CSS and optional non-critical JS**

Add stable action-menu/bulk-bar primitives only when reused. If selected-count JS is added, it may:
- update `[data-rakit-selected-count]`;
- disable/enable bulk submit buttons as enhancement;
- react to checkbox changes.

The HTML must remain functional when that script never runs.

Rebuild:

```powershell
bun run css:build
uv run ruff format --check .
uv run ruff check .
uv run ty check
```

- [ ] **Step 8: Commit bulk + review surfaces**

```powershell
git add packages/rakit-web/src/rakit_web/bulk_admin.py packages/rakit-web/src/rakit_web/bulk_routes.py packages/rakit-web/src/rakit_web/templates/resources/_table.html packages/rakit-web/src/rakit_web/templates/actions packages/rakit-web/src/rakit_web/assets/rakit.css packages/rakit-web/src/rakit_web/static/rakit.css packages/rakit-web/src/rakit_web/static/rakit-ui.js
git commit -m "feat(web): mature action and bulk review surfaces"
```

Only stage `rakit-ui.js` if it actually changed.

---

### Task 5: Exercise UI-06A in `examples/ui_showcase`

**Files:**
- Modify: `examples/ui_showcase/main.py`

**Interfaces:**
- Consumes: new public presentation types and existing action/bulk runtime.
- Produces: deterministic browser states for normal, primary, danger, disabled, hidden, form, preview, confirmation, success, and bulk actions.

- [ ] **Step 1: Import the public presentation types**

Add `ActionIntent`, `ActionPresentation`, and `PageWebPresentation` to the existing public imports.

- [ ] **Step 2: Mark `refund_order` as danger only through Web presentation**

Register `OrdersAdmin` with:

```python
web=ResourceWebPresentation(
    actions={
        "refund_order": ActionPresentation(intent=ActionIntent.DANGER),
    }
)
```

Do not add a danger field to the core action declaration.

- [ ] **Step 3: Add deterministic action states**

Add at least:
- DEFAULT record action;
- PRIMARY resource or page action;
- DISABLED action returning `ActionAvailabilityDecision.disabled("Warehouse sync is currently unavailable.")`;
- HIDDEN action and confirm its entry point is omitted for RESOURCE/RECORD/PAGE contexts;
- typed action form with validation;
- safe BULK action;
- danger BULK action with confirmation.

Use existing in-memory/domain executors; do not add a second action engine for the example.

- [ ] **Step 4: Manually exercise before tests**

```powershell
uv run python -m examples.ui_showcase.main
```

Browser checklist:
- resource/record/page action overflow hierarchy;
- HIDDEN omitted when target context is available;
- DISABLED visible with reason and non-invokable;
- action form validation;
- preview/confirmation review screen;
- bulk action list buttons work with JS disabled after selecting records;
- bulk GET hides HIDDEN selection state with 404 and renders DISABLED selection state without execute control;
- bulk one-selected/many-selected;
- safe vs danger hierarchy.

- [ ] **Step 5: Commit showcase scenarios**

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
- Modify as needed: `packages/rakit-web/tests/test_public_resource_composition.py`, `test_public_page_composition.py`.

**Interfaces:**
- Consumes: completed UI-06A behavior.
- Produces: durable presentation/availability/no-JS contract coverage without changing implementation.

- [ ] **Step 1: Test public presentation validation**

Cover:
- unknown action presentation id fails closed before registration mutation;
- non-`ActionPresentation` value fails;
- two PRIMARY RECORD actions under one resource fail;
- one PRIMARY RECORD + one PRIMARY RESOURCE under the same resource is valid;
- page action validation follows the same scope rule.

- [ ] **Step 2: Test default compatibility**

Assert existing actions with no presentation resolve to `ActionIntent.DEFAULT`, existing `ResourceWebPresentation(filters=...)` remains valid, and old `register_page(..., actions=...)` remains valid without `web=`.

- [ ] **Step 3: Test context-aware entry availability**

For RESOURCE/RECORD/PAGE entry views:
- HIDDEN label/URL absent;
- DISABLED label/reason present but URL is not rendered as an invokable link/control;
- AVAILABLE renders normally;
- unauthorized action absent regardless of presentation intent.

- [ ] **Step 4: Test bulk no-JS and selection-aware availability**

Render the resource list and assert base bulk submit controls are not statically disabled. Submit a GET form with selected identities and no JS:
- AVAILABLE => 200 bulk form;
- HIDDEN => 404 without action form/label;
- DISABLED => 200 disabled review with safe reason and no executable final submit;
- POST re-check still rejects a target that becomes unavailable after GET.

- [ ] **Step 5: Test HTML maturity and token preservation**

Render action form/confirm/bulk pages and assert:
- semantic `text-rakit-*` / `rakit-alert-*` classes;
- unconditional legacy slate/red/amber patterns removed from these templates;
- danger confirm button only when presentation is DANGER;
- disabled reason rendered;
- CSRF/submission/concurrency/confirmation hidden fields remain present with their existing names.

- [ ] **Step 6: Run focused tests**

```powershell
uv run pytest packages/rakit-web/tests/test_advanced_ui_maturity.py packages/rakit-web/tests/test_actions.py packages/rakit-web/tests/test_bulk_actions.py packages/rakit-web/tests/test_bulk_list_ui.py packages/rakit-web/tests/test_public_resource_composition.py packages/rakit-web/tests/test_public_page_composition.py -q
```

Expected: PASS.

- [ ] **Step 7: Run static/full verification**

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

- [ ] **Step 8: Commit tests**

```powershell
git add packages/rakit-web/tests/test_advanced_ui_maturity.py packages/rakit-web/tests/test_actions.py packages/rakit-web/tests/test_bulk_actions.py packages/rakit-web/tests/test_bulk_list_ui.py packages/rakit-web/tests/test_public_resource_composition.py packages/rakit-web/tests/test_public_page_composition.py
git commit -m "test(web): cover mature action presentation"
```

Only stage existing test files that actually changed.

- [ ] **Step 9: Open the UI-06A PR against `ui-06-advanced-operations`**

Require fresh PR CI and maintainer browser acceptance. Do not merge directly to `main`.
