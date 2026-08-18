# UI-06D Custom Pages & Feedback Consistency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give default custom pages a mature, safe Rakit presentation and consistent validation/rejection/success feedback while preserving `PageDefinition`, `PageResult`, POST/Redirect/Get, custom-template escape hatches, and PAGE action execution semantics.

**Architecture:** Keep the core page model unchanged. Add a Web-internal conservative payload classifier that produces a typed `PagePayloadView` for the built-in `pages/page.html`; continue passing the original raw `payload` in template context so existing custom templates remain source-compatible. Reuse UI-06A `PageWebPresentation`/action hierarchy for PAGE actions, and reuse the app shell/system feedback primitives instead of inventing a page-builder DSL.

**Tech Stack:** Python 3.12+, Starlette ASGI, Jinja2, existing Rakit page operation runtime, Tailwind CSS 4.1.18, pytest/pytest-anyio, Ruff, ty.

**Spec:** `docs/superpowers/specs/2026-08-19-ui-06-advanced-operations-auth-system-design.md`

## Global Constraints

- Work from the latest `ui-06-advanced-operations` integration head after UI-06C is merged; implement UI-06D on a child branch.
- Feature/source implementation comes first; regression tests are added at the end of the slice.
- Do not add page-component/page-builder types to `rakit-core` or public `rakit` API.
- `PageDefinition` remains unchanged, including `template="pages/page.html"` as the default and custom `template="..."` as the explicit escape hatch.
- Keep raw `payload` in every page template context for backward compatibility with existing custom templates.
- Only the built-in default template consumes the new safe `payload_view`.
- Never render arbitrary object `repr()` / `str()` as a production fallback.
- Never interpret payload strings/mappings as trusted HTML or implicit component definitions.
- Conservative renderer supports only explicitly safe scalar shapes, flat mappings with string keys, and sequences of flat mappings with consistent keys.
- Unsupported/deep objects render a neutral “requires a custom template” message; do not expose internal object details.
- Mutating pages remain POST/Redirect/Get. Successful mutating handlers must still return `PageRedirect`.
- Preserve page CSRF, submission-token, idempotency, permission, typed input parsing, transaction, deadline, and operation-context semantics.
- PAGE actions use the UI-06A action presentation contract; do not create a second page-action system.
- Custom templates remain free to use Rakit shell/theme primitives but are not forced to adopt the default payload renderer.
- Feedback states must distinguish validation, business rejection, success, forbidden/not-found/system errors; do not collapse them into a generic red box.
- No JavaScript-only page submission path.
- Edit `packages/rakit-web/src/rakit_web/assets/rakit.css`; regenerate `packages/rakit-web/src/rakit_web/static/rakit.css` with `bun run css:build`. Never hand-edit generated CSS.
- No release/tag/PyPI action.

---

## File Map

### Create
- `packages/rakit-web/src/rakit_web/page_payload.py` — Web-internal safe payload classifier/view.
- `packages/rakit-web/tests/test_custom_page_ui_maturity.py` — slice UI contract tests, created after feature work.

### Modify
- `packages/rakit-web/src/rakit_web/page_routes.py` — compute `payload_view`, structured feedback context; preserve raw payload and operation semantics.
- `packages/rakit-web/src/rakit_web/page_admin.py` — ensure PAGE action presentation/link context is available through existing UI-06A helper; no core change.
- `packages/rakit-web/src/rakit_web/templates/pages/page.html` — mature default shell/forms/payload renderer/actions.
- `packages/rakit-web/src/rakit_web/assets/rakit.css`
- `packages/rakit-web/src/rakit_web/static/rakit.css` — generated output.
- `examples/ui_showcase/main.py` — deterministic scalar/mapping/table/empty/unsupported/custom-template/page-action states.
- Existing page regression suites: `packages/rakit-web/tests/test_pages.py`, page input guardrail tests, auth/permission tests as applicable.

---

### Task 1: Add a Conservative Web-Internal Page Payload Classifier

**Files:**
- Create: `packages/rakit-web/src/rakit_web/page_payload.py`

**Interfaces:**
- Consumes: arbitrary `PageResult.payload` from application code.
- Produces: a closed `PagePayloadView` that contains only values safe for the generic built-in template to render.

- [ ] **Step 1: Define the closed view model**

Use a small enum/dataclass model:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import TypeAlias
from uuid import UUID

SafePageScalar: TypeAlias = str | int | float | bool | Decimal | date | datetime | UUID | None


class PagePayloadKind(StrEnum):
    EMPTY = "empty"
    SCALAR = "scalar"
    MAPPING = "mapping"
    TABLE = "table"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class PagePayloadView:
    kind: PagePayloadKind
    scalar: SafePageScalar = None
    items: tuple[tuple[str, SafePageScalar], ...] = ()
    columns: tuple[str, ...] = ()
    rows: tuple[tuple[SafePageScalar, ...], ...] = ()
```

Do not include an arbitrary-object field.

- [ ] **Step 2: Define exactly what counts as a safe scalar**

Use exact/controlled standard types only:

```python
_SAFE_SCALAR_TYPES = (str, int, float, bool, Decimal, date, datetime, UUID)


def _safe_scalar(value: object) -> bool:
    return value is None or isinstance(value, _SAFE_SCALAR_TYPES)
```

Do not call arbitrary formatters, `repr`, `vars`, model dump methods, or object attributes.

- [ ] **Step 3: Classify supported shapes without recursion**

Implement:

```python
def page_payload_view(payload: object) -> PagePayloadView:
    if payload is None:
        return PagePayloadView(PagePayloadKind.EMPTY)
    if _safe_scalar(payload):
        return PagePayloadView(PagePayloadKind.SCALAR, scalar=payload)
    if isinstance(payload, dict):
        return _mapping_view(payload)
    if isinstance(payload, (list, tuple)):
        return _table_view(payload)
    return PagePayloadView(PagePayloadKind.UNSUPPORTED)
```

`_mapping_view` accepts only:
- every key is a non-empty string;
- every value is a safe scalar;
- no nested dict/list/object.

Otherwise return UNSUPPORTED.

`_table_view` accepts only:
- non-empty sequence;
- every row is a `dict`;
- every key is a non-empty string;
- all rows have the same keys in the same canonical column set;
- every cell is a safe scalar.

Derive columns from the first row’s insertion order and materialize row tuples in that order. An empty sequence returns EMPTY. Any mismatch returns UNSUPPORTED.

- [ ] **Step 4: Keep unsupported output opaque**

The UNSUPPORTED view has no representation of the original payload. The default template therefore cannot accidentally leak it.

- [ ] **Step 5: Run static verification**

```powershell
uv run ruff format packages/rakit-web/src/rakit_web/page_payload.py
uv run ruff check packages/rakit-web/src/rakit_web/page_payload.py
uv run ty check
```

- [ ] **Step 6: Commit the classifier**

```powershell
git add packages/rakit-web/src/rakit_web/page_payload.py
git commit -m "feat(web): add safe default page payload views"
```

---

### Task 2: Add Safe Payload and Feedback Context Without Breaking Custom Templates

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/page_routes.py`

**Interfaces:**
- Consumes: existing `PageResult`, schema validation issues, `PageRejected`.
- Produces: template context containing both backward-compatible `payload` and safe `payload_view`.

- [ ] **Step 1: Preserve the existing `payload` key exactly**

In `_template_args`, keep:

```python
"payload": result.payload if result is not None else None,
```

Do not rename/remove it.

- [ ] **Step 2: Add `payload_view` only for result payloads**

Add:

```python
"payload_view": page_payload_view(result.payload if result is not None else None),
```

This is safe even for custom templates; they may ignore it.

- [ ] **Step 3: Add field description/error IDs to page form views**

Bring `_field_views` in line with mature form/action controls:

```python
{
    "id": f"rakit-page-{field.name}",
    "name": field.name,
    "label": ...,
    "description": field.description,
    "description_id": f"rakit-page-{field.name}-description",
    "error_id": f"rakit-page-{field.name}-error",
    "value": submitted.get(field.name, ""),
    "issues": issues.get(field.name, ()),
}
```

This is presentation metadata only.

- [ ] **Step 4: Keep page result/rejection semantics unchanged**

Do not change:
- `PageResult.status_code` handling;
- `PageRedirect` 303 mounting behavior;
- `PageRejected.status_code`;
- mutation idempotency release/fail-final rules;
- successful mutating page requirement to return `PageRedirect`.

`_rejected_response` may be visually replaced later, but do not change its status or replay behavior in this task.

- [ ] **Step 5: Run static verification**

```powershell
uv run ruff format packages/rakit-web/src/rakit_web/page_routes.py
uv run ruff check packages/rakit-web/src/rakit_web/page_routes.py
uv run ty check
```

- [ ] **Step 6: Commit page context additions**

```powershell
git add packages/rakit-web/src/rakit_web/page_routes.py
git commit -m "feat(web): add safe default page presentation context"
```

---

### Task 3: Mature the Built-in Default Page Template

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/templates/pages/page.html`
- Modify: `packages/rakit-web/src/rakit_web/assets/rakit.css`
- Regenerate: `packages/rakit-web/src/rakit_web/static/rakit.css`

**Interfaces:**
- Consumes: `page`, `payload_view`, `fields`, `issues`, `message`, UI-06A `rakit_actions` helper.
- Produces: mature read-only and mutating default page UI.

- [ ] **Step 1: Replace legacy dashboard-navigation fragment and slate palette**

Use the normal app shell already provided by `base.html`; do not include a second `components/dashboard_navigation.html` inside page content unless it provides unique functionality that is not already in the shell.

Add a breadcrumb:

```text
Dashboard > <Page label>
```

using mount-safe root path and semantic Rakit tokens.

Header uses the same rhythm as resource/detail/forms:
- small context label `Page`;
- `h1` page label;
- optional concise default support copy;
- PAGE action group on the right.

- [ ] **Step 2: Add PAGE action hierarchy from UI-06A**

Use:

```jinja
{% set page_actions = rakit_actions(request, page.page_id, 'page') if rakit_actions is defined else () %}
```

Render through `components/actions.html` so PAGE action intent/default/overflow behavior is identical to resource/record actions.

Do not execute actions inline; links go to compiled PAGE action routes.

- [ ] **Step 3: Normalize success and validation feedback**

`message` uses `rakit-alert rakit-alert-success` and `role="status"`.

`issues` uses `rakit-alert rakit-alert-danger`, `role="alert"`, and a concise heading `There are problems with this page input.`. Link to fields when the issue key matches a rendered field ID if straightforward; otherwise keep the summary safe and readable.

- [ ] **Step 4: Mature mutating page forms**

Keep hidden `csrf_token` and `submission_token` names/values unchanged.

For every field:
- semantic label;
- description help text with `aria-describedby`;
- field-local issue with `rakit-error`;
- `aria-invalid` when issues exist;
- normal `rakit-input` control.

Use a sticky or clearly separated footer with Submit and a safe cancel/back affordance only when there is a meaningful mounted destination. Do not add a Cancel button that points to an invented route.

- [ ] **Step 5: Render each `payload_view.kind` explicitly**

Use Jinja branches:

```jinja
{% if payload_view.kind.value == 'empty' %}
  <p>No page content was returned.</p>
{% elif payload_view.kind.value == 'scalar' %}
  <p>{{ payload_view.scalar }}</p>
{% elif payload_view.kind.value == 'mapping' %}
  <dl>...</dl>
{% elif payload_view.kind.value == 'table' %}
  <table>...</table>
{% else %}
  <div class="rakit-alert rakit-alert-neutral">
    This page returned content that requires a custom template.
  </div>
{% endif %}
```

Jinja autoescape remains enabled. Do not use `|safe`.

- [ ] **Step 6: Keep table rendering intentionally modest**

The default table supports only the already-classified scalar cell values. Do not add sorting/filtering/pagination guesses to custom-page payloads. If a page needs richer interactions, its explicit custom template owns them.

- [ ] **Step 7: Add only reusable page primitives if needed and rebuild CSS**

```powershell
bun run css:build
uv run python -c "from rakit_web.resource_routes import build_templates; build_templates(()).env.get_template('pages/page.html')"
uv run ruff format --check .
uv run ruff check .
```

- [ ] **Step 8: Commit default page UI**

```powershell
git add packages/rakit-web/src/rakit_web/templates/pages/page.html packages/rakit-web/src/rakit_web/assets/rakit.css packages/rakit-web/src/rakit_web/static/rakit.css
git commit -m "feat(web): mature default custom page UI"
```

---

### Task 4: Replace Generic Page Rejection HTML With Consistent Safe Feedback

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/page_routes.py`

**Interfaces:**
- Consumes: expected safe page rejection/guardrail messages and existing page template machinery.
- Produces: semantic page feedback without changing status codes or mutation replay rules.

- [ ] **Step 1: Keep validation and `PageRejected` on the normal page template**

These already route through `_render_page`. Preserve that path and ensure the matured template displays their issue/message hierarchy.

- [ ] **Step 2: Replace `_rejected_response` only where there is no page context**

For submission replay/guardrail responses that currently return hand-built HTML, introduce a small internal template response or semantic helper that renders:
- safe fixed message;
- exact supplied status code;
- `Cache-Control: no-store`;
- app shell context if the principal is already authorized to the page;
- no exception internals.

Do not route 403/404/500 framework system errors through this helper; UI-06C owns those.

A dedicated built-in fragment such as `pages/rejected.html` is acceptable if it avoids duplicating raw HTML. If created, add it to the file map/commit for this task.

- [ ] **Step 3: Preserve idempotency state transitions exactly**

No change to:
- completed receipt replay;
- FAILED_FINAL response;
- in-progress 409;
- fingerprint mismatch 409;
- `release()` on `PageRejected`;
- `fail_final()` on unexpected/invalid mutating handler result.

- [ ] **Step 4: Static verification**

```powershell
uv run ruff format packages/rakit-web/src/rakit_web/page_routes.py
uv run ruff check packages/rakit-web/src/rakit_web/page_routes.py
uv run ty check
```

- [ ] **Step 5: Commit feedback consistency**

```powershell
git add packages/rakit-web/src/rakit_web/page_routes.py packages/rakit-web/src/rakit_web/templates/pages
git commit -m "feat(web): unify custom page feedback"
```

Stage a new `pages/rejected.html` only if it was actually created.

---

### Task 5: Exercise Default and Custom Pages in `examples/ui_showcase`

**Files:**
- Modify: `examples/ui_showcase/main.py`
- Modify/add showcase templates only for explicit custom-template scenarios under `examples/ui_showcase/templates/`.

**Interfaces:**
- Consumes: public `PageDefinition`, `PageResult`, `PageWebPresentation`, PAGE actions.
- Produces: deterministic acceptance states for every default renderer branch and the custom-template escape hatch.

- [ ] **Step 1: Add default read-only page scenarios**

Register separate deterministic pages or a single QA page with links for:
- scalar payload;
- flat mapping payload;
- sequence of consistent flat mappings;
- empty payload;
- unsupported/deep payload.

Example unsupported payload must be intentionally opaque, e.g.:

```python
PageResult(payload={"nested": {"secret-ish-internal": "do not render generically"}})
```

The UI must show only the custom-template guidance, not the nested data.

- [ ] **Step 2: Keep one explicit custom-template page**

Existing `/ui-lab` already demonstrates `template="ui_lab.html"`. Verify it continues to receive raw `payload` and render unchanged after `payload_view` is added.

Do not migrate it to the default renderer merely to prove the default.

- [ ] **Step 3: Add a mutating page scenario**

Use an existing supported input schema + `PageRedirect` path with development-only idempotency. Exercise validation and business rejection through the real page runtime.

- [ ] **Step 4: Add PAGE actions and danger presentation**

Register PAGE actions via the existing `actions=(...)` parameter and UI-06A:

```python
web=PageWebPresentation(
    actions={
        "clear_report_cache": ActionPresentation(intent=ActionIntent.DANGER),
    }
)
```

Ensure the action still executes through the compiled PAGE action route.

- [ ] **Step 5: Manual browser review before tests**

```powershell
uv run python -m examples.ui_showcase.main
```

Review:
- page breadcrumb/header rhythm;
- scalar/mapping/table/empty/unsupported states;
- custom UI Lab still unchanged functionally;
- mutating page validation/rejection/success redirect;
- PAGE default + danger action hierarchy;
- no-JS page submission.

- [ ] **Step 6: Commit showcase page states**

```powershell
git add examples/ui_showcase/main.py examples/ui_showcase/templates
git commit -m "feat(examples): cover mature custom page states"
```

Only stage showcase templates that actually changed/appeared.

---

### Task 6: Add Regression Tests Last and Run the UI-06D Gate

**Files:**
- Create: `packages/rakit-web/tests/test_custom_page_ui_maturity.py`
- Modify: `packages/rakit-web/tests/test_pages.py` only where compatibility assertions belong.
- Modify other page guardrail suites only if response presentation assertions require it.

**Interfaces:**
- Consumes: completed UI-06D behavior.
- Produces: safe-renderer, compatibility, PAGE action, and PRG regression coverage.

- [ ] **Step 1: Test every payload classifier branch**

```python
def test_nested_payload_is_not_exposed_by_default_view() -> None:
    payload = {"nested": {"api_key": "secret"}}
    view = page_payload_view(payload)

    assert view.kind is PagePayloadKind.UNSUPPORTED
    assert not view.items
    assert not view.rows
```

Also test scalar, flat mapping, consistent table, empty list, inconsistent table columns, non-string mapping keys, and custom object all produce the expected closed view.

- [ ] **Step 2: Test default template does not leak unsupported payload**

Render a page returning:

```python
{"nested": {"credential": "DO_NOT_RENDER"}}
```

Assert:
- status 200;
- custom-template guidance present;
- `DO_NOT_RENDER` absent;
- no `<pre>` arbitrary payload dump.

- [ ] **Step 3: Test flat mapping/table markup**

Assert mapping renders `<dl>` labels/values and sequence renders a semantic table with only declared scalar columns/cells.

- [ ] **Step 4: Prove custom-template backward compatibility**

Create/use a custom template that accesses `payload` directly:

```jinja
<p>{{ payload["purpose"] }}</p>
```

Assert it still renders after UI-06D. This is the compatibility gate for preserving raw payload in custom-template context.

- [ ] **Step 5: Reassert mutating page semantics**

Use existing `test_pages.py` flows to confirm:
- CSRF/submission verification order unchanged;
- validation returns 422 page form;
- `PageRejected` releases idempotency reservation and returns configured 4xx;
- successful mutation requires/returns 303 `PageRedirect`;
- invalid non-redirect mutating result becomes fail-final 500 as before;
- completed receipt replay remains 303.

Do not alter expected status semantics for visual reasons.

- [ ] **Step 6: Test PAGE action presentation integration**

Render a page with multiple PAGE actions and assert it uses the same action-group semantics from UI-06A; danger intent changes presentation only. Action permission and execution remain covered by action suites.

- [ ] **Step 7: Run focused tests**

```powershell
uv run pytest packages/rakit-web/tests/test_custom_page_ui_maturity.py packages/rakit-web/tests/test_pages.py -q
```

Expected: PASS.

- [ ] **Step 8: Run full verification**

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

- [ ] **Step 9: Commit tests**

```powershell
git add packages/rakit-web/tests/test_custom_page_ui_maturity.py packages/rakit-web/tests/test_pages.py
git commit -m "test(web): cover mature custom page UI"
```

Only stage `test_pages.py` if it actually changed.

- [ ] **Step 10: Open the UI-06D PR against `ui-06-advanced-operations`**

Require fresh PR CI and maintainer browser acceptance. Merge only into the integration branch. After this merge, proceed to the separate UI-06 integration verification plan; do not merge the integration branch to `main` yet.
