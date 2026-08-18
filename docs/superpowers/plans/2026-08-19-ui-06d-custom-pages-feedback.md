# UI-06D Custom Pages & Feedback Consistency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give default custom pages a mature, safe Rakit presentation and consistent validation/rejection/success feedback while preserving `PageDefinition`, `PageResult`, POST/Redirect/Get, custom-template escape hatches, and PAGE action execution semantics.

**Architecture:** Keep the core page model unchanged. Add a Web-internal conservative payload classifier that produces a closed `PagePayloadView` for the built-in `pages/page.html`; continue passing the original raw `payload` in template context so existing custom templates remain source-compatible. Consume the permission/availability-aware `page_actions` context already produced by UI-06A rather than resolving actions again in Jinja. Reuse app-shell and feedback primitives instead of inventing a page-builder DSL.

**Tech Stack:** Python 3.12+, Starlette ASGI, Jinja2, existing Rakit page operation runtime, Tailwind CSS 4.1.18, pytest/pytest-anyio, Ruff, ty.

**Spec:** `docs/superpowers/specs/2026-08-19-ui-06-advanced-operations-auth-system-design.md`

## Global Constraints

- Work from the latest `ui-06-advanced-operations` integration head after UI-06C is merged; implement UI-06D on a child branch.
- Feature/source implementation comes first; regression tests are added at the end of the slice.
- Do not add page-component/page-builder types to `rakit-core` or public `rakit` API.
- `PageDefinition` remains unchanged, including `template="pages/page.html"` as default and custom `template="..."` as explicit escape hatch.
- Keep raw `payload` in every page template context for backward compatibility with existing custom templates.
- Only the built-in default template consumes the new safe `payload_view`.
- Never render arbitrary object `repr()` / `str()` as a production fallback.
- Never interpret payload strings/mappings as trusted HTML or implicit component definitions.
- Conservative renderer supports only exact safe standard scalar types, flat string-keyed mappings, and sequences of consistent flat string-keyed mappings.
- Unsupported/deep objects render a neutral “requires a custom template” message; original object data is not carried in the fallback view.
- Mutating pages remain POST/Redirect/Get. Successful mutating handlers must still return `PageRedirect`.
- Preserve page CSRF, submission-token, idempotency, permission, typed input parsing, transaction, deadline, and operation-context semantics.
- PAGE actions consume the UI-06A `page_actions` route context and shared action macro. Do not resolve permissions/availability a second time in the template.
- Custom templates remain free to use raw `payload` and Rakit shell/theme primitives; they are not forced onto the default renderer.
- Feedback distinguishes validation, business rejection, success, forbidden/not-found/system errors; do not collapse all states into a generic red box.
- No JavaScript-only page submission path.
- Edit `packages/rakit-web/src/rakit_web/assets/rakit.css`; regenerate `packages/rakit-web/src/rakit_web/static/rakit.css` with `bun run css:build`. Never hand-edit generated CSS.
- No release/tag/PyPI action.

---

## File Map

### Create
- `packages/rakit-web/src/rakit_web/page_payload.py` — Web-internal safe payload classifier/view.
- `packages/rakit-web/tests/test_custom_page_ui_maturity.py` — slice UI contract tests, created after feature work.

### Modify
- `packages/rakit-web/src/rakit_web/page_routes.py` — compute safe `payload_view`, mounted dashboard URL, mature field metadata; preserve raw payload/execution semantics.
- `packages/rakit-web/src/rakit_web/templates/pages/page.html` — mature default shell/forms/payload renderer/PAGE actions.
- Add `packages/rakit-web/src/rakit_web/templates/pages/rejected.html` only if needed to eliminate hand-built rejection HTML without changing status/idempotency behavior.
- `packages/rakit-web/src/rakit_web/assets/rakit.css`
- `packages/rakit-web/src/rakit_web/static/rakit.css` — generated output.
- `examples/ui_showcase/main.py` and explicit showcase templates only where deterministic page states require them.
- Existing page suites: `test_pages.py`, `test_page_admin_runtime.py`, `test_page_input_guardrails.py`, `test_page_runtime_validation.py`, `test_public_page_composition.py`.

---

### Task 1: Add a Conservative Web-Internal Page Payload Classifier

**Files:**
- Create: `packages/rakit-web/src/rakit_web/page_payload.py`

**Interfaces:**
- Consumes: arbitrary `PageResult.payload` from application code.
- Produces: a closed `PagePayloadView` containing only values safe for the generic built-in template.

- [ ] **Step 1: Define the closed view model**

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

No arbitrary-object field is allowed.

- [ ] **Step 2: Define exact safe scalar types**

```python
_SAFE_SCALAR_TYPES = (str, int, float, bool, Decimal, date, datetime, UUID)


def _safe_scalar(value: object) -> bool:
    return value is None or type(value) in _SAFE_SCALAR_TYPES
```

Use exact `type(...)` membership deliberately. Do not accept arbitrary subclasses whose string/render behavior application code can override. Do not call formatters, `repr`, `vars`, `.dict()`, `.model_dump()`, or inspect object attributes.

- [ ] **Step 3: Classify supported shapes without recursion**

```python
def page_payload_view(payload: object) -> PagePayloadView:
    if payload is None:
        return PagePayloadView(PagePayloadKind.EMPTY)
    if _safe_scalar(payload):
        return PagePayloadView(PagePayloadKind.SCALAR, scalar=payload)
    if type(payload) is dict:
        return _mapping_view(payload)
    if type(payload) in {list, tuple}:
        return _table_view(payload)
    return PagePayloadView(PagePayloadKind.UNSUPPORTED)
```

`_mapping_view` accepts only non-empty string keys + safe scalar values, no recursion.

`_table_view` accepts only:
- empty sequence -> EMPTY;
- every row exact `dict`;
- all keys non-empty strings;
- same canonical key set/order derived from first row;
- every cell safe scalar.

Any mismatch/deep value -> UNSUPPORTED.

- [ ] **Step 4: Keep unsupported output opaque**

UNSUPPORTED carries no original value. This makes accidental leakage impossible from the default template.

- [ ] **Step 5: Verify and commit**

```powershell
uv run ruff format packages/rakit-web/src/rakit_web/page_payload.py
uv run ruff check packages/rakit-web/src/rakit_web/page_payload.py
uv run ty check
git add packages/rakit-web/src/rakit_web/page_payload.py
git commit -m "feat(web): add safe default page payload views"
```

---

### Task 2: Add Safe Payload/Navigation/Field Context Without Breaking Custom Templates

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/page_routes.py`

**Interfaces:**
- Consumes: existing `PageResult`, page route/request, schema validation issues, UI-06A `page_actions` context.
- Produces: template context with backward-compatible raw `payload`, safe `payload_view`, mounted `dashboard_url`, and mature field metadata.

- [ ] **Step 1: Preserve raw `payload` exactly**

Keep:

```python
"payload": result.payload if result is not None else None,
```

Do not rename/remove it for custom templates.

- [ ] **Step 2: Add safe `payload_view`**

```python
"payload_view": page_payload_view(result.payload if result is not None else None),
```

Do not condition this on template name; custom templates may ignore the extra safe view while retaining raw payload.

- [ ] **Step 3: Add exact mounted dashboard URL**

Add:

```python
"dashboard_url": mounted_path(request, "/"),
```

The default template uses this for breadcrumb/back affordance instead of assuming `/`.

- [ ] **Step 4: Preserve the UI-06A `page_actions` context**

UI-06A page route composition has already resolved PAGE actions using permission + availability. Ensure `_template_args` receives/preserves that `page_actions` value; do not re-run the resolver here merely for styling.

- [ ] **Step 5: Add description/error ids to page form views**

For each schema field add deterministic `description_id` and `error_id` while keeping field name/value/issues unchanged. This is presentation metadata only.

- [ ] **Step 6: Do not alter page result/rejection semantics**

Preserve `PageResult.status_code`, `PageRedirect` 303 mounting, `PageRejected.status_code`, mutation idempotency transitions, and the requirement that successful mutating pages return a redirect.

- [ ] **Step 7: Verify and commit**

```powershell
uv run ruff format packages/rakit-web/src/rakit_web/page_routes.py
uv run ruff check packages/rakit-web/src/rakit_web/page_routes.py
uv run ty check
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
- Consumes: `page`, `dashboard_url`, already-resolved `page_actions`, `payload_view`, `fields`, `issues`, `message`.
- Produces: mature default read-only/mutating custom-page UI.

- [ ] **Step 1: Remove the redundant inner dashboard navigation and legacy palette**

Use the app shell from `base.html`; do not include a second `components/dashboard_navigation.html` inside page content. Replace touched slate/red/emerald direct palette utilities with semantic Rakit tokens/primitives.

- [ ] **Step 2: Add mounted-safe breadcrumb/header**

Render `Dashboard > <Page label>` using `dashboard_url`. Header uses the same resource/form rhythm and includes PAGE actions on the right.

- [ ] **Step 3: Render the UI-06A PAGE action context directly**

Import the shared macro:

```jinja
{% from "components/actions.html" import action_group %}
```

Then render:

```jinja
{{ action_group(page_actions | default(())) }}
```

Do **not** call a permission/availability resolver from Jinja and do not rebuild action URLs in the template.

- [ ] **Step 4: Normalize success/validation feedback**

`message` -> semantic success alert/status. `issues` -> semantic danger alert with concise `There are problems with this page input.` summary and field-local errors.

- [ ] **Step 5: Mature mutating page form**

Keep hidden `csrf_token` and `submission_token` names/values exactly. Use labels/help/error ids, `aria-describedby`, `aria-invalid`, `rakit-input`, and a clearly separated action footer. Add Cancel/Back only to an actual safe `dashboard_url`/page destination already provided; do not invent route semantics.

- [ ] **Step 6: Render each safe payload kind explicitly**

```jinja
{% if payload_view.kind.value == 'empty' %}
  ...
{% elif payload_view.kind.value == 'scalar' %}
  {{ payload_view.scalar }}
{% elif payload_view.kind.value == 'mapping' %}
  <dl>...</dl>
{% elif payload_view.kind.value == 'table' %}
  <table>...</table>
{% else %}
  <div class="rakit-alert ...">
    This page returned content that requires a custom template.
  </div>
{% endif %}
```

Jinja autoescape remains on. Do not use `|safe`.

- [ ] **Step 7: Keep default table intentionally modest**

No inferred sorting/filtering/pagination/action DSL. Rich pages use explicit templates.

- [ ] **Step 8: Rebuild/verify/commit**

```powershell
bun run css:build
uv run python -c "from rakit_web.resource_routes import build_templates; build_templates(()).env.get_template('pages/page.html')"
uv run ruff format --check .
uv run ruff check .
git add packages/rakit-web/src/rakit_web/templates/pages/page.html packages/rakit-web/src/rakit_web/assets/rakit.css packages/rakit-web/src/rakit_web/static/rakit.css
git commit -m "feat(web): mature default custom page UI"
```

---

### Task 4: Replace Generic Page Rejection HTML With Consistent Safe Feedback

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/page_routes.py`
- Create only if useful: `packages/rakit-web/src/rakit_web/templates/pages/rejected.html`

**Interfaces:**
- Consumes: fixed/safe page replay/guardrail messages and existing page template machinery.
- Produces: semantic page feedback without changing HTTP/idempotency semantics.

- [ ] **Step 1: Keep validation and `PageRejected` on normal page rendering**

These already use page context. Preserve that route and let the matured template present their issues/message correctly.

- [ ] **Step 2: Replace hand-built rejection HTML only for context-less page guardrails**

For replay/submission guardrail responses currently constructed as raw HTML, use a small built-in template/helper that preserves:
- exact supplied status code;
- safe fixed message;
- `Cache-Control: no-store`;
- app shell context only when already authorized;
- no exception internals.

UI-06C still owns 403/404/500 framework system errors.

- [ ] **Step 3: Preserve idempotency transitions byte-for-byte in behavior**

No semantic changes to completed receipt replay, FAILED_FINAL, in-progress 409, fingerprint mismatch, release on `PageRejected`, or fail-final on unexpected/invalid mutation results.

- [ ] **Step 4: Verify and commit**

```powershell
uv run ruff format packages/rakit-web/src/rakit_web/page_routes.py
uv run ruff check packages/rakit-web/src/rakit_web/page_routes.py
uv run ty check
git add packages/rakit-web/src/rakit_web/page_routes.py packages/rakit-web/src/rakit_web/templates/pages
git commit -m "feat(web): unify custom page feedback"
```

Stage `rejected.html` only if created.

---

### Task 5: Exercise Default and Custom Pages in `examples/ui_showcase`

**Files:**
- Modify: `examples/ui_showcase/main.py`
- Modify/add explicit templates under `examples/ui_showcase/templates/` only as needed.

**Interfaces:**
- Consumes: public `PageDefinition`, `PageResult`, `PageWebPresentation`, PAGE actions.
- Produces: deterministic acceptance states for every default payload branch and custom-template compatibility.

- [ ] **Step 1: Add default read-only payload scenarios**

Exercise scalar, flat mapping, consistent sequence-of-flat-mappings, empty, and unsupported/deep payloads. Unsupported payload must contain seeded nested text and the browser must not reveal it.

- [ ] **Step 2: Preserve one explicit custom-template page**

Existing `/ui-lab` with `template="ui_lab.html"` remains an explicit custom-template scenario. Verify it still receives/uses raw `payload`; do not migrate it merely to prove the default renderer.

- [ ] **Step 3: Add a real mutating page scenario**

Use supported input schema + `PageRedirect`, exercise real validation/business rejection/idempotency through existing runtime.

- [ ] **Step 4: Add PAGE action intent through UI-06A public contract**

Use `PageWebPresentation(actions=...)` with a danger PAGE action where semantically appropriate. Execution still goes through compiled PAGE action route.

- [ ] **Step 5: Manual browser review before tests**

```powershell
uv run python -m examples.ui_showcase.main
```

Review breadcrumb/header, all payload states, UI Lab compatibility, mutating validation/rejection/redirect, PAGE action hierarchy, and no-JS submission.

- [ ] **Step 6: Commit**

```powershell
git add examples/ui_showcase/main.py examples/ui_showcase/templates
git commit -m "feat(examples): cover mature custom page states"
```

Only stage templates that actually changed.

---

### Task 6: Add Regression Tests Last and Run the UI-06D Gate

**Files:**
- Create: `packages/rakit-web/tests/test_custom_page_ui_maturity.py`
- Modify existing page suites only where new compatibility/presentation assertions belong.

**Interfaces:**
- Consumes: completed UI-06D behavior.
- Produces: safe-renderer, custom-template, PAGE-action, PRG, guardrail, and compatibility coverage.

- [ ] **Step 1: Test every payload classifier branch**

Cover exact scalar types, flat mapping, consistent table, empty list, nested mapping, inconsistent table keys/order, non-string keys, subclasses/custom objects. Unsupported view must carry none of the original payload data.

- [ ] **Step 2: Test default template does not leak unsupported payload**

Return nested payload containing `DO_NOT_RENDER`; assert 200 + custom-template guidance, `DO_NOT_RENDER` absent, and no arbitrary `<pre>` dump.

- [ ] **Step 3: Test mapping/table markup and autoescape**

Mapping renders definition list, table sequence renders semantic table. A scalar string containing HTML remains escaped.

- [ ] **Step 4: Prove custom-template backward compatibility**

An explicit template accessing `payload["purpose"]` directly still renders unchanged after `payload_view` is added.

- [ ] **Step 5: Reassert mutating page semantics**

Keep existing expectations for CSRF/submission order, 422 validation, `PageRejected` configured 4xx + reservation release, 303 PageRedirect success, fail-final invalid mutation result, and completed receipt replay.

- [ ] **Step 6: Test PAGE action presentation integration**

Default page renders already-resolved `page_actions`; danger presentation changes hierarchy/style only. HIDDEN/DISABLED behavior remains inherited from UI-06A action-view tests.

- [ ] **Step 7: Run the exact focused suite**

```powershell
uv run pytest packages/rakit-web/tests/test_custom_page_ui_maturity.py packages/rakit-web/tests/test_pages.py packages/rakit-web/tests/test_page_admin_runtime.py packages/rakit-web/tests/test_page_input_guardrails.py packages/rakit-web/tests/test_page_runtime_validation.py packages/rakit-web/tests/test_public_page_composition.py -q
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
git add packages/rakit-web/tests/test_custom_page_ui_maturity.py packages/rakit-web/tests/test_pages.py packages/rakit-web/tests/test_page_admin_runtime.py packages/rakit-web/tests/test_page_input_guardrails.py packages/rakit-web/tests/test_page_runtime_validation.py packages/rakit-web/tests/test_public_page_composition.py
git commit -m "test(web): cover mature custom page UI"
```

Only stage existing files that actually changed.

- [ ] **Step 10: Open UI-06D PR against `ui-06-advanced-operations`**

Require fresh PR CI and maintainer browser acceptance. Merge only into integration, then execute the separate UI-06 integration plan; do not merge integration to `main` yet.
