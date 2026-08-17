# Rakit UI/UX Maturity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade every `rakit-web` surface into a cohesive, simple, clean, accessible Modern Product UI using Tailwind CSS v4, semantic design tokens, restrained Lucide icons, and a comprehensive `examples/ui_showcase` visual QA application.

**Architecture:** Keep SSR + HTMX and the existing Rakit runtime authoritative. Tailwind v4 remains the styling engine; semantic theme tokens live in the maintainer source CSS, reusable framework primitives remain `.rakit-*` classes, and one-off layout stays as direct Tailwind utilities in Jinja templates. A dedicated `examples/ui_showcase` application plus `/ui-lab` becomes the visual acceptance surface for every UI PR.

**Tech Stack:** Python 3.12+, Starlette ASGI, Jinja2, HTMX, Tailwind CSS 4.1.18, Bun maintainer asset build, inline server-rendered SVG icons, pytest/pytest-anyio/pytest-cov/pytest-xdist, Ruff, ty, MkDocs.

## Global Constraints

- Preserve SSR + HTMX progressive enhancement; do not create JavaScript-only critical flows.
- Preserve fail-closed capability, permission, CSRF, authentication, idempotency, transaction, and concurrency semantics.
- Tailwind CSS v4 remains the primary styling engine.
- Edit `packages/rakit-web/src/rakit_web/assets/rakit.css`; regenerate and commit `packages/rakit-web/src/rakit_web/static/rakit.css` with `bun run css:build`. Never hand-edit the generated CSS.
- Use semantic Tailwind theme tokens for Rakit-owned colors; use OKLCH for owned color values.
- Brand direction: restrained indigo-violet; approximately 85–90% neutral surfaces and 8–12% brand interaction/highlight usage.
- Status colors are semantic: success green, warning amber, danger red, info blue/cyan family.
- `@apply` is allowed only for stable reusable Rakit primitives; local layout stays as direct Tailwind utilities.
- Do not dynamically construct Tailwind class names that cannot be statically detected.
- No CDN-hosted Tailwind, icons, fonts, or runtime styling dependency.
- Icons use a curated vendored subset of Lucide outline SVG data rendered server-side; preserve upstream license/provenance.
- Icons improve navigation/action scanning but must not be added automatically to every title, field label, cell, or button.
- Icon-only controls require an accessible name; decorative icons are hidden from assistive technology.
- Theme control is one icon button opening a compact popover with icon + text options for System, Light, and Dark.
- Preserve no-flash theme initialization, local persistence under the existing `rakit.theme` preference, and system color-scheme updates.
- Light, dark, and system themes are first-class.
- Normal text contrast target is at least 4.5:1; large text at least 3:1.
- Preserve visible focus, keyboard operation, semantic labels, live announcements, and reduced-motion support.
- No decorative glassmorphism, gradient text, oversized card radii, decorative grid backgrounds, heavy shadow-plus-border “ghost cards”, or nested-card noise.
- `examples/ui_showcase` must use the real default Rakit UI and must not ship private CSS that masks framework weaknesses.
- Each implementation PR is based on the previous merged UI PR, is independently reviewable, and must keep the repository gate green.
- Local fast test command may use `uv run pytest -n auto --cov`; CI remains authoritative for the serial gate.
- Do not tag, create a GitHub Release, or publish to PyPI/TestPyPI as part of this program.
- Keep the design spec and this plan in the repo during implementation. After UI-08 is complete and the maintainer has saved the provided copies, delete both planning files in the final cleanup commit.

## Branch / PR Sequence

Implement sequentially:

1. `ui-01-showcase-baseline`
2. `ui-02-design-tokens`
3. `ui-03-shell-theme-icons`
4. `ui-04-core-components`
5. `ui-05-resource-experience`
6. `ui-06-advanced-operations`
7. `ui-07-responsive-a11y-hardening`
8. `ui-08-final-polish`

Do not stack unrelated work on these branches. Merge each PR before starting the next so the visual baseline evolves monotonically.

---

## File Map

### Existing styling and asset pipeline

- `packages/rakit-web/src/rakit_web/assets/rakit.css` — Tailwind maintainer source, design tokens, reusable `.rakit-*` primitives.
- `packages/rakit-web/src/rakit_web/static/rakit.css` — generated committed CSS output.
- `packages/rakit-web/src/rakit_web/static/theme.js` — early theme preference resolution and persistence.
- `packages/rakit-web/src/rakit_web/static/rakit-ui.js` — lightweight interaction helpers for existing dialogs/navigation/HTMX UI.
- `packages/rakit-web/src/rakit_web/assets.py` — static asset serving contract.
- `package.json` — pinned Tailwind 4.1.18 build/watch scripts.

### Existing shared templates

- `packages/rakit-web/src/rakit_web/templates/base.html` — document shell, header, theme control, main layout.
- `packages/rakit-web/src/rakit_web/templates/components/ui.html` — reusable Jinja UI macros.
- `packages/rakit-web/src/rakit_web/templates/components/admin_navigation.html` — desktop navigation.
- `packages/rakit-web/src/rakit_web/templates/components/admin_mobile_navigation.html` — mobile navigation.
- `packages/rakit-web/src/rakit_web/templates/components/dashboard_navigation.html` — dashboard-local navigation helper.

### Existing feature templates

- `packages/rakit-web/src/rakit_web/templates/resources/list.html`
- `packages/rakit-web/src/rakit_web/templates/resources/_table.html`
- `packages/rakit-web/src/rakit_web/templates/resources/_count.html`
- `packages/rakit-web/src/rakit_web/templates/resources/detail.html`
- `packages/rakit-web/src/rakit_web/templates/forms/form.html`
- `packages/rakit-web/src/rakit_web/templates/forms/delete_confirm.html`
- `packages/rakit-web/src/rakit_web/templates/actions/_form.html`
- `packages/rakit-web/src/rakit_web/templates/actions/_confirm.html`
- `packages/rakit-web/src/rakit_web/templates/actions/form.html`
- `packages/rakit-web/src/rakit_web/templates/actions/confirm.html`
- `packages/rakit-web/src/rakit_web/templates/actions/bulk.html`
- `packages/rakit-web/src/rakit_web/templates/relationships/panel.html`
- `packages/rakit-web/src/rakit_web/templates/relationships/to_one.html`
- `packages/rakit-web/src/rakit_web/templates/relationships/to_many.html`
- `packages/rakit-web/src/rakit_web/templates/relationships/inline_rows.html`
- `packages/rakit-web/src/rakit_web/templates/relationships/options.html`
- `packages/rakit-web/src/rakit_web/templates/relationships/error_summary.html`
- `packages/rakit-web/src/rakit_web/templates/relationships/preview_confirm.html`
- `packages/rakit-web/src/rakit_web/templates/relationships/preview_dialog.html`
- `packages/rakit-web/src/rakit_web/templates/auth/login.html`
- feature templates under `templates/dashboard/` and `templates/pages/`.

### Existing behavior/runtime files that may need narrowly scoped presentation data

- `packages/rakit-web/src/rakit_web/navigation.py`
- `packages/rakit-web/src/rakit_web/dashboard_admin.py`
- `packages/rakit-web/src/rakit_web/dashboard_routes.py`
- `packages/rakit-web/src/rakit_web/resource_routes.py`
- `packages/rakit-web/src/rakit_web/form_routes.py`
- `packages/rakit-web/src/rakit_web/action_routes.py`
- `packages/rakit-web/src/rakit_web/bulk_routes.py`
- `packages/rakit-web/src/rakit_web/relationship_routes.py`
- `packages/rakit-web/src/rakit_web/auth_routes.py`
- `packages/rakit-web/src/rakit_web/page_routes.py`

Rule: change runtime Python only when the template needs semantically meaningful presentation data that cannot be derived safely in Jinja. Do not move pure visual choices into runtime/domain code.

### Existing tests to extend

- `packages/rakit-web/tests/test_assets.py`
- `packages/rakit-web/tests/test_accessibility_contracts.py`
- `packages/rakit-web/tests/test_dashboard_runtime.py`
- `packages/rakit-web/tests/test_bulk_list_ui.py`
- `packages/rakit-web/tests/test_actions.py`
- `packages/rakit-web/tests/test_bulk_actions.py`
- existing form/resource/relationship/auth/page tests in `packages/rakit-web/tests/`.
- root example tests such as `tests/test_dashboard_example.py`.

### New shared files expected during the program

- `packages/rakit-web/src/rakit_web/icons.py` — curated icon registry + safe SVG rendering API.
- `packages/rakit-web/src/rakit_web/templates/components/icon.html` only if a Jinja macro is cleaner than calling the Python helper directly; otherwise keep icon rendering centralized in `icons.py` and expose one template global.
- `packages/rakit-web/src/rakit_web/static/LUCIDE_LICENSE.txt`
- `packages/rakit-web/src/rakit_web/static/LUCIDE_PROVENANCE.md`
- `packages/rakit-web/tests/test_icons.py`
- `packages/rakit-web/tests/test_theme_ui.py`

### New showcase files

- `examples/ui_showcase/__init__.py`
- `examples/ui_showcase/main.py`
- `examples/ui_showcase/data.py`
- `examples/ui_showcase/README.md`
- `tests/test_ui_showcase.py`

Keep the example compact: `main.py` owns Rakit composition and demo-only service/auth glue; `data.py` owns deterministic seeded data. Do not create a second application framework inside the example.

---

# UI-01 — UI Showcase and Visual Baseline

**PR goal:** Add a deterministic realistic application and `/ui-lab` visual QA page that exercise the current UI before redesign work begins.

**Files:**
- Create: `examples/ui_showcase/__init__.py`
- Create: `examples/ui_showcase/data.py`
- Create: `examples/ui_showcase/main.py`
- Create: `examples/ui_showcase/README.md`
- Create: `tests/test_ui_showcase.py`
- Modify only if required for a missing existing public capability: narrowly scoped existing Rakit files; do not redesign framework CSS/templates in this PR.

**Interfaces:**
- Consumes: public Rakit APIs already exercised by `examples/dashboard`, `examples/internal_tools`, relationships, auth, and storage examples.
- Produces: importable `examples.ui_showcase.main.admin` and `examples.ui_showcase.main.app`.
- Produces routes: `/`, `/ui-lab`, and representative resource/action/page routes derived from registered Rakit definitions.

- [ ] **Step 1: Add failing import/smoke test for the new example**

Create `tests/test_ui_showcase.py` with an async test that imports `admin`, builds `app = admin.asgi()`, GETs `/`, `/ui-lab`, and at least one representative resource list path, and asserts `200`.

```python
import httpx
import pytest


@pytest.mark.anyio
async def test_ui_showcase_exposes_dashboard_ui_lab_and_resources() -> None:
    from examples.ui_showcase.main import admin

    app = admin.asgi()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://localhost",
    ) as client:
        dashboard = await client.get("/")
        ui_lab = await client.get("/ui-lab")
        orders = await client.get("/orders")

    assert dashboard.status_code == 200
    assert ui_lab.status_code == 200
    assert orders.status_code == 200
    assert "Rakit Commerce" in dashboard.text
    assert "UI Lab" in ui_lab.text
```

- [ ] **Step 2: Run the new test and verify it fails because the module does not exist**

```powershell
uv run pytest tests/test_ui_showcase.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'examples.ui_showcase'`.

- [ ] **Step 3: Add deterministic seeded demo data**

Create `examples/ui_showcase/data.py` with deterministic records for Customers, Products, Orders, Categories, Inventory, and Teams. Include at least one long customer/company name, paid/pending/refunded/cancelled order statuses, low-stock and healthy-stock products, optional/missing values, multiple relationships, and enough rows to exercise pagination/filtering. Use fixed IDs/dates/currency values; do not use random values or current wall-clock time in rendered assertions.

- [ ] **Step 4: Compose the showcase with real Rakit public APIs**

Create `examples/ui_showcase/main.py` following the composition style of `examples/internal_tools/main.py`: `Admin(admin_id="ui_showcase", title="Rakit Commerce", debug=True, ...)`, development-only auth/session/idempotency adapters where needed, resource registrations for Customers/Products/Orders/Categories/Inventory/Teams, representative supported actions, relationships, a custom `/ui-lab` `PageDefinition`, and `app = admin.asgi()`.

Keep example-specific HTML payloads minimal. `/ui-lab` must render through Rakit’s normal page/template machinery rather than shipping its own CSS.

- [ ] **Step 5: Make the smoke test pass and add deterministic content assertions**

Extend `tests/test_ui_showcase.py` to assert known seeded values, `/ui-lab` headings for Typography/Buttons/Fields/Status/Feedback/Tables/Empty states/Loading states/Errors/Theme, navigation links, and configured auth behavior.

```powershell
uv run pytest tests/test_ui_showcase.py -q
```

Expected: PASS.

- [ ] **Step 6: Document maintainer run instructions**

Create `examples/ui_showcase/README.md` with:

```powershell
uv sync --extra examples
uv run python -m examples.ui_showcase.main
```

Document the development URL, demo credentials if authentication is enabled, `/ui-lab`, and that the example intentionally has no private CSS.

- [ ] **Step 7: Run existing example tests to prove no example regression**

```powershell
uv run pytest tests/test_dashboard_example.py tests/test_ui_showcase.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit UI-01**

```powershell
git add examples/ui_showcase tests/test_ui_showcase.py
git commit -m "feat(examples): add UI showcase baseline"
```

- [ ] **Step 9: Run PR gate before opening UI-01**

```powershell
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest -n auto --cov
uv run mkdocs build --strict
uv run python scripts/check_artifacts.py
git status --short
```

Expected: zero failures, coverage >= 85%, clean status except intentional committed files.

---

# UI-02 — Tailwind Design Tokens and Color Foundation

**PR goal:** Replace generic concrete blue/slate styling with a coherent semantic Tailwind v4 token system and calibrated light/dark foundations without changing interaction structure.

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/assets/rakit.css`
- Regenerate: `packages/rakit-web/src/rakit_web/static/rakit.css`
- Modify: `packages/rakit-web/src/rakit_web/templates/base.html`
- Modify: `packages/rakit-web/src/rakit_web/templates/components/ui.html`
- Modify tests: `packages/rakit-web/tests/test_assets.py`
- Modify tests: `packages/rakit-web/tests/test_accessibility_contracts.py`
- Modify: `tests/test_ui_showcase.py` only for stable semantic assertions.

**Interfaces:** Preserve existing public `.rakit-button`, `.rakit-button-secondary`, `.rakit-button-quiet`, `.rakit-button-danger`, `.rakit-input`, `.rakit-select`, `.rakit-panel`, `.rakit-panel-header`, `.rakit-panel-body`, `.rakit-error`, `.rakit-chip`, `.rakit-dialog` names.

- [ ] **Step 1: Add asset regression assertions for semantic token presence**

Extend `test_assets.py` to assert maintainer CSS contains `--color-rakit-brand-600`, `--color-rakit-bg`, `--color-rakit-surface`, `--color-rakit-text`, `--color-rakit-border`, and `--color-rakit-danger`, and keep the static asset route assertion.

- [ ] **Step 2: Run focused asset tests and verify the new assertions fail**

```powershell
uv run pytest packages/rakit-web/tests/test_assets.py -q
```

- [ ] **Step 3: Define semantic tokens in `@theme`**

Add Rakit-owned OKLCH values for brand 50–950, background/surface/subtle/raised, border, text/muted, success/warning/danger/info roles, focus, radius, and shadow values. Keep values statically declared.

- [ ] **Step 4: Convert base and framework primitives to semantic tokens**

Replace direct `slate-*`, `blue-*`, and semantic red values where they represent design roles. Keep class APIs stable and use real generated Tailwind utilities corresponding to the declared tokens.

- [ ] **Step 5: Calibrate dark theme independently**

Ensure surface levels, muted text, brand active/focus states, semantic statuses, and borders remain legible without making every region outlined.

- [ ] **Step 6: Build Tailwind**

```powershell
bun run css:build
```

- [ ] **Step 7: Run asset/accessibility/showcase tests**

```powershell
uv run pytest packages/rakit-web/tests/test_assets.py packages/rakit-web/tests/test_accessibility_contracts.py tests/test_ui_showcase.py -q
```

- [ ] **Step 8: Manually inspect light and dark**

Run `uv run python -m examples.ui_showcase.main` and inspect `/`, `/orders`, detail/form routes, and `/ui-lab`. Reject washed-out muted text, generic-blue remnants, excessive color, or indistinguishable dark surfaces.

- [ ] **Step 9: Commit UI-02**

```powershell
git add packages/rakit-web/src/rakit_web/assets/rakit.css packages/rakit-web/src/rakit_web/static/rakit.css packages/rakit-web/src/rakit_web/templates/base.html packages/rakit-web/src/rakit_web/templates/components/ui.html packages/rakit-web/tests/test_assets.py packages/rakit-web/tests/test_accessibility_contracts.py tests/test_ui_showcase.py
git commit -m "style(web): establish Rakit design tokens"
```

- [ ] **Step 10: Run the full PR gate**

Use the standard gate from UI-01.

---

# UI-03 — App Shell, Navigation, Theme Switcher, and Icons

**PR goal:** Introduce restrained first-class iconography, replace the text theme select with an accessible icon-triggered System/Light/Dark popover, and mature desktop/mobile shell navigation.

**Files:**
- Create: `packages/rakit-web/src/rakit_web/icons.py`
- Create: `packages/rakit-web/src/rakit_web/static/LUCIDE_LICENSE.txt`
- Create: `packages/rakit-web/src/rakit_web/static/LUCIDE_PROVENANCE.md`
- Create: `packages/rakit-web/tests/test_icons.py`
- Create/Modify: `packages/rakit-web/tests/test_theme_ui.py`
- Modify: `packages/rakit-web/src/rakit_web/templates/base.html`
- Modify: `packages/rakit-web/src/rakit_web/templates/components/ui.html`
- Modify: `packages/rakit-web/src/rakit_web/templates/components/admin_navigation.html`
- Modify: `packages/rakit-web/src/rakit_web/templates/components/admin_mobile_navigation.html`
- Modify: `packages/rakit-web/src/rakit_web/static/theme.js`
- Modify: `packages/rakit-web/src/rakit_web/static/rakit-ui.js` only where native popover/focus behavior needs help.
- Modify: `packages/rakit-web/src/rakit_web/assets/rakit.css`
- Regenerate: `packages/rakit-web/src/rakit_web/static/rakit.css`
- Modify only the existing template-environment setup needed to expose `rakit_icon(...)`.

**Interfaces:** `rakit_web.icons.render_icon(name: str, *, size: int = 18, decorative: bool = True, label: str | None = None)` returns safe markup. Initial supported names: `sun`, `moon`, `monitor`, `search`, `filter`, `chevron-down`, `chevron-left`, `chevron-right`, `menu`, `x`, `plus`, `edit`, `trash`, `more-horizontal`, `check`, `alert-triangle`, `circle-alert`, `info`, `upload`, `download`, `refresh-cw`, `archive`, `external-link`, `users`, `package`, `shopping-cart`, `boxes`, `tag`, `layout-dashboard`. Unknown names fail closed. Theme key remains `rakit.theme`.

- [ ] **Step 1: Write failing icon renderer tests**

Test known icon SVG size, decorative `aria-hidden`, labeled accessible markup, unknown icon failure, and inability to inject arbitrary SVG through `name`.

- [ ] **Step 2: Run icon tests and verify failure**

```powershell
uv run pytest packages/rakit-web/tests/test_icons.py -q
```

- [ ] **Step 3: Implement curated icon registry**

Check in only approved Lucide path data; build SVG from trusted constants and validated parameters, never raw user SVG.

- [ ] **Step 4: Add Lucide license/provenance**

Record project, source version/commit, retrieval date, subset strategy, and server-side rendering approach.

- [ ] **Step 5: Add failing theme UI tests**

Assert old `data-rakit-theme-select` select is absent; accessible theme trigger exists; popover exposes System/Light/Dark with `data-rakit-theme-option`; active state has valid semantics.

- [ ] **Step 6: Replace theme select with icon-triggered popover**

Use one compact button, current monitor/sun/moon icon, icon+text options, keyboard focus, Escape dismissal, and native Popover API where practical.

- [ ] **Step 7: Refactor `theme.js` around generic controls**

Support `data-rakit-theme-trigger`, `data-rakit-theme-option`, active-state synchronization, localStorage persistence, and system media updates while preserving early no-flash application.

- [ ] **Step 8: Add purposeful shell/navigation icons**

Use icons for dashboard/home, recognized showcase resources, menu toggle, and conventional actions. Keep custom user-defined resources text-first unless an optional framework-neutral icon metadata path is clearly justified.

- [ ] **Step 9: Mature desktop/mobile navigation hierarchy**

Refine active state, group spacing, hover/focus, touch targets, long labels, mobile open/close, and shell surface hierarchy without breaking navigation-provider contracts.

- [ ] **Step 10: Build CSS and run focused tests**

```powershell
bun run css:build
uv run pytest packages/rakit-web/tests/test_icons.py packages/rakit-web/tests/test_theme_ui.py packages/rakit-web/tests/test_accessibility_contracts.py tests/test_ui_showcase.py -q
```

- [ ] **Step 11: Commit UI-03**

```powershell
git add packages/rakit-web/src/rakit_web packages/rakit-web/tests tests/test_ui_showcase.py
git commit -m "feat(web): mature shell theme control and icons"
```

- [ ] **Step 12: Run full PR gate and keyboard-test theme/mobile navigation**

Use Tab/Shift+Tab/Enter/Space/Escape before opening the PR.

---

# UI-04 — Core Components

**PR goal:** Make buttons, fields, status, feedback, dialogs, pagination, and loading primitives consistent and reusable.

**Files:** Modify `assets/rakit.css`, generated `static/rakit.css`, `templates/components/ui.html`, `static/rakit-ui.js` only for behavior, `test_accessibility_contracts.py`, relevant existing component/action tests, and `tests/test_ui_showcase.py`.

**Interfaces:** Preserve existing macro call sites. Extend `button(...)` only with backward-compatible keyword parameters such as optional icon. Add icon-button, alert/status, empty-state header, and loading primitives only when reused by at least two framework surfaces.

- [ ] **Step 1: Add failing rendered-markup assertions** for minimum control height, semantic error association, disabled state, icon-only accessible name, and dialog title/description semantics.
- [ ] **Step 2: Run focused tests** with accessibility/actions/bulk/showcase.
- [ ] **Step 3: Refine button hierarchy** for primary/secondary/quiet/danger/icon-only/loading/disabled.
- [ ] **Step 4: Refine fields** for text/number/date/select/textarea/checkbox/radio/help/required/read-only/disabled/error/file input.
- [ ] **Step 5: Refine status and feedback** for success/warning/error/info/neutral, never color-only.
- [ ] **Step 6: Refine dialog/popover/pagination/loading primitives** while preserving HTMX/full-page behavior.
- [ ] **Step 7: Expand `/ui-lab`** with interactive component variants.
- [ ] **Step 8: Build CSS and run focused tests**.

```powershell
bun run css:build
uv run pytest packages/rakit-web/tests/test_accessibility_contracts.py packages/rakit-web/tests/test_actions.py packages/rakit-web/tests/test_bulk_list_ui.py tests/test_ui_showcase.py -q
```

- [ ] **Step 9: Commit UI-04**

```powershell
git add packages/rakit-web/src/rakit_web packages/rakit-web/tests tests/test_ui_showcase.py
git commit -m "style(web): mature core UI primitives"
```

- [ ] **Step 10: Run full PR gate**.

---

# UI-05 — Resource Experience

**PR goal:** Redesign the highest-frequency admin workflow: list/table, search/filter, detail, create/edit, delete, pagination, empty/no-results, and responsive resource behavior.

**Files:** Modify `templates/resources/list.html`, `_table.html`, `_count.html`, `detail.html`, `templates/forms/form.html`, `delete_confirm.html`, shared UI macros, `assets/rakit.css`, generated CSS, and narrowly `resource_routes.py`/`form_routes.py` only when needed for semantic presentation data. Extend resource/form tests and `tests/test_ui_showcase.py`.

**Interfaces:** Preserve query parameters/routes, full-page/HTMX partial behavior, validation status codes, CSRF, delete/concurrency semantics.

- [ ] **Step 1: Add resource UI semantic tests** for page heading, labeled search/filter, table headers, named row actions, labeled selection controls, distinct empty/no-results, query-preserving pagination, and field-linked errors.
- [ ] **Step 2: Run focused resource/form tests** and verify new assertions fail.
- [ ] **Step 3: Redesign list hierarchy** as title/context → primary action → search/filter → active filter summary → count/selection → data → pagination; avoid card-per-block layout.
- [ ] **Step 4: Redesign table ergonomics** with readable compact density, alignment, hover/selection, sorting, horizontal overflow, and no tiny mobile typography.
- [ ] **Step 5: Redesign detail hierarchy** using grouped information/definition lists before adding cards.
- [ ] **Step 6: Redesign create/edit forms** with coherent spacing, sections, help/required/error, responsive save/cancel, pending feedback.
- [ ] **Step 7: Redesign delete confirmation** with explicit consequence and action hierarchy.
- [ ] **Step 8: Build CSS and run package/showcase tests**.

```powershell
bun run css:build
uv run pytest packages/rakit-web/tests tests/test_ui_showcase.py -q
```

- [ ] **Step 9: Visual workflow pass** for many rows, no-results, empty data, long values, missing values, detail, form validation, delete, desktop/mobile.
- [ ] **Step 10: Commit UI-05**

```powershell
git add packages/rakit-web/src/rakit_web packages/rakit-web/tests tests/test_ui_showcase.py
git commit -m "style(web): mature resource workflows"
```

- [ ] **Step 11: Run full PR gate**.

---

# UI-06 — Advanced Operations

**PR goal:** Bring actions, bulk operations, relationships, uploads, custom pages, previews, confirmations, and operation-result feedback into the same visual/interaction language.

**Files:** Modify action and relationship templates listed above, upload-related presentation in existing form/file upload surfaces, relevant dashboard/page templates, CSS/generated CSS, `rakit-ui.js` only for progressive enhancement, and existing action/bulk/relationship/upload/page tests plus `tests/test_ui_showcase.py`.

**Interfaces:** Preserve ActionResult-to-HTTP mapping, preview/confirmation tokens, idempotency/concurrency, bulk policy/selection, relationship mutation/preview, and upload validation/security.

- [ ] **Step 1: Add semantic tests** for confirmation hierarchy, preview readability without JS, result roles/text, selected count, relationship labels, and upload state text.
- [ ] **Step 2: Run focused advanced-operation tests** and verify new assertions fail.
- [ ] **Step 3: Mature action forms/confirmations** across page/resource/record scopes with consistent heading, copy, fields, confirm/back, danger use, and HTMX/full-page parity.
- [ ] **Step 4: Mature bulk UX** with selected-count toolbar, clear primary action, destructive separation, selection visibility, and result summary.
- [ ] **Step 5: Mature relationship UX** for to-one/to-many/inline/options/preview/errors/empty/high-cardinality states; avoid ambiguous icon-only controls.
- [ ] **Step 6: Mature upload and custom-page surfaces** using existing core components/icons rather than a new widget framework.
- [ ] **Step 7: Build CSS and run focused tests**.

```powershell
bun run css:build
uv run pytest packages/rakit-web/tests/test_actions.py packages/rakit-web/tests/test_bulk_actions.py packages/rakit-web/tests/test_bulk_list_ui.py tests/test_ui_showcase.py -q
```

Also run the exact relationship/upload/page test modules affected by the changes.

- [ ] **Step 8: Visual advanced-flow pass** for approve/refund/cancel, validation, preview, bulk selection, relationship add/remove, empty relationship, upload, custom pages.
- [ ] **Step 9: Commit UI-06**

```powershell
git add packages/rakit-web/src/rakit_web packages/rakit-web/tests tests/test_ui_showcase.py
git commit -m "style(web): mature advanced operation UX"
```

- [ ] **Step 10: Run full PR gate**.

---

# UI-07 — Responsive, Accessibility, and UX Hardening

**PR goal:** Treat mobile/tablet, keyboard, focus, contrast, reduced motion, long content, loading/error/empty states, and UX copy as release-quality concerns.

**Files:** Modify only UI files identified by the audit, `test_accessibility_contracts.py`, targeted semantic tests, `docs/accessibility.md` when guarantees change, and `tests/test_ui_showcase.py`.

- [ ] **Step 1: Put a hardening checklist in the PR description** covering keyboard, focus, theme popover, mobile nav, dialogs, table overflow, form errors, touch targets, light/dark contrast, reduced motion, long content, and empty/no-results/error/loading.
- [ ] **Step 2: Expand automated accessibility contracts** for main landmark, skip link, icon-button names, dialog semantics, form-error linking, duplicate IDs where practical, and text accompanying status meaning.
- [ ] **Step 3: Run accessibility tests and fix failures one by one**.

```powershell
uv run pytest packages/rakit-web/tests/test_accessibility_contracts.py tests/test_ui_showcase.py -q
```

- [ ] **Step 4: Perform responsive pass** at approximately 1440, 1024, 768, and 390 CSS pixels for dashboard/list/detail/form/action/relationship/login/UI Lab; fix structure rather than merely shrinking type.
- [ ] **Step 5: Perform keyboard-only pass** for skip link, nav, theme, search/filter, row actions, dialogs, forms, relationships; fix traps/unreachable/invisible focus and return-focus bugs.
- [ ] **Step 6: Perform contrast pass** for >=4.5:1 normal and >=3:1 large text in light/dark, including placeholders/muted/status text.
- [ ] **Step 7: Perform reduced-motion and pending-state pass**; no content may depend on animation to become visible.
- [ ] **Step 8: Clarify UX copy** with explicit action labels and destructive consequences while preserving domain terminology.
- [ ] **Step 9: Build CSS, run package suite, and strict docs if changed**.

```powershell
bun run css:build
uv run pytest packages/rakit-web/tests tests/test_ui_showcase.py -q
uv run mkdocs build --strict
```

- [ ] **Step 10: Commit UI-07**

```powershell
git add packages/rakit-web/src/rakit_web packages/rakit-web/tests tests/test_ui_showcase.py
git add docs/accessibility.md 2>$null
git commit -m "fix(web): harden responsive and accessible UX"
```

If `docs/accessibility.md` did not change, leave it unstaged.

- [ ] **Step 11: Run full PR gate**.

---

# UI-08 — Final Impeccable Polish and Planning-Doc Cleanup

**PR goal:** Run final structured design review, resolve all release-blocking visual/UX findings, verify the showcase across themes/viewports, then remove temporary design/implementation planning docs after the maintainer already has local copies.

**Files:** Modify only UI files/tests required by final findings. Delete after implementation and saved-copy confirmation:
- `docs/superpowers/specs/2026-08-17-ui-ux-maturity-design.md`
- `docs/superpowers/plans/2026-08-17-ui-ux-maturity.md`

- [ ] **Step 1: Run Impeccable context against `rakit-web`** and inspect product/register context plus existing design system before changes.
- [ ] **Step 2: Run structured critique/audit** on shell, dashboard, list/detail, forms, actions/bulk, relationships, auth, and `/ui-lab`. Record findings in PR description/issues, not a new permanent planning file.
- [ ] **Step 3: Fix P0/P1 and material P2 findings test-first**: failing focused test → implementation → focused pass → CSS build if styling changed.
- [ ] **Step 4: Run layout/typeset/colorize/adapt/harden/polish passes as warranted**, keeping the result simple, clean, restrained, and comfortable rather than marketing-like.
- [ ] **Step 5: Complete final manual matrix** for Shell, Dashboard, Resource list, Detail, Form, Action/confirm, Bulk, Relationships, Login/auth, UI Lab across Light/Dark/System and Desktop/Tablet/Mobile.
- [ ] **Step 6: Run complete repository gate**.

```powershell
bun run css:build
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest -n auto --cov
uv run mkdocs build --strict
uv run python scripts/check_artifacts.py
git diff --check
git status --short
```

Expected: zero failures, coverage >= 85%, generated CSS committed, no unintended dirty files.

- [ ] **Step 7: Confirm maintainer has saved the pre-implementation copies** of `2026-08-17-ui-ux-maturity-design.md` and `2026-08-17-ui-ux-maturity.md`.
- [ ] **Step 8: Delete the temporary planning docs**.

```powershell
git rm docs/superpowers/specs/2026-08-17-ui-ux-maturity-design.md
git rm docs/superpowers/plans/2026-08-17-ui-ux-maturity.md
git commit -m "chore: remove completed UI maturity planning docs"
```

- [ ] **Step 9: Re-run docs/artifact-sensitive gates after deletion**.

```powershell
uv run mkdocs build --strict
uv run python scripts/check_artifacts.py
git status --short
```

- [ ] **Step 10: Open UI-08 PR without release side effects**. State UI-01…UI-08 complete, final local/CI verification, planning docs removed after saved copies, and no tag/release/PyPI action.

---

## Per-PR Review Rules

1. Behavior first: server/runtime semantics stay correct.
2. Focused test first for behavior/semantic markup changes.
3. Generated CSS discipline: edit source → `bun run css:build` → commit source/generated CSS together.
4. Inspect affected states in `examples/ui_showcase` and `/ui-lab`.
5. If the showcase needs special CSS to look correct, fix `rakit-web` instead.
6. Every icon must improve recognition, hierarchy, or conventional control scanning.
7. Avoid brittle full-document HTML snapshots; assert semantics, important text, roles, route behavior, and stable attributes/classes.
8. Runtime Python changes require a concrete presentation need and targeted tests.
9. One merged PR at a time: UI-02 starts from merged UI-01, and so on.
10. UI maturity completion does not imply tag/release/PyPI publish.

## Final Definition of Done

The program is done only when:

- `examples/ui_showcase` is a realistic end-to-end application using default Rakit UI;
- `/ui-lab` deterministically exposes representative components and states;
- semantic Tailwind tokens replace generic concrete palette usage where appropriate;
- light/dark/system themes are polished and accessible;
- theme switching uses the icon-triggered System/Light/Dark popover;
- curated Lucide icons are vendored with provenance/license and rendered server-side;
- all major resource/form/action/bulk/relationship/auth/custom-page surfaces share one interaction hierarchy;
- responsive desktop/tablet/mobile behavior is intentional;
- keyboard/focus/contrast/reduced-motion requirements are satisfied;
- all repository gates are green;
- no release-blocking Impeccable findings remain;
- the maintainer has local copies of the spec and implementation plan;
- repo copies of the temporary spec and implementation plan are removed in the final cleanup commit;
- no tag, GitHub Release, or PyPI/TestPyPI publish has been performed automatically.
