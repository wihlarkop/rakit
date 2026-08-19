# Rakit UI/UX Maturity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade every `rakit-web` surface into a cohesive, simple, clean, accessible Modern Product UI using Tailwind CSS v4, semantic design tokens, restrained Lucide icons, and a comprehensive `examples/ui_showcase` visual QA application.

**Architecture:** Keep SSR + HTMX and the existing Rakit runtime authoritative. Tailwind v4 remains the styling engine; semantic theme tokens live in the maintainer source CSS, reusable framework primitives remain `.rakit-*` classes, and one-off layout stays as direct Tailwind utilities in Jinja templates. `examples/ui_showcase` plus `/ui-lab` is the visual acceptance surface for every UI PR.

**Tech Stack:** Python 3.12+, Starlette ASGI, Jinja2, HTMX, Tailwind CSS 4.1.18, Bun maintainer asset build, server-rendered inline SVG icons, pytest/pytest-anyio/pytest-cov/pytest-xdist, Ruff, ty, MkDocs.

## Global Constraints

- Preserve SSR + HTMX progressive enhancement; no JavaScript-only critical flow.
- Preserve fail-closed capability, permission, CSRF, authentication, idempotency, transaction, and concurrency semantics.
- Tailwind CSS v4 is the primary styling engine.
- Edit `packages/rakit-web/src/rakit_web/assets/rakit.css`; regenerate and commit `packages/rakit-web/src/rakit_web/static/rakit.css` with `bun run css:build`. Never hand-edit generated CSS.
- Rakit-owned colors use semantic Tailwind theme tokens and OKLCH values.
- Brand direction: restrained indigo-violet; approximately 85–90% neutral surfaces and 8–12% brand interaction/highlight usage.
- Semantic states: success green, warning amber, danger red, info blue/cyan.
- Use `@apply` only for stable reusable `.rakit-*` primitives. Local layout remains direct Tailwind utilities.
- Never dynamically construct Tailwind class names that the scanner cannot statically detect.
- No CDN-hosted Tailwind, icon package, font, or runtime styling dependency.
- Icons use a curated vendored subset of Lucide outline SVG path data rendered server-side. Preserve upstream license/provenance.
- Icons support recognition and scanning; do not add icons automatically to every heading, field label, table cell, or button.
- Icon-only controls require an accessible name; decorative icons use `aria-hidden="true"`.
- Theme control is one icon button opening a compact popover with icon + text options for System, Light, and Dark.
- Keep persistence under `rakit.theme`, preserve early no-flash theme application, and follow OS color-scheme changes when preference is System.
- Light, dark, and system modes are first-class.
- Normal text contrast >= 4.5:1; large text contrast >= 3:1.
- Preserve keyboard operation, visible focus, live announcements, semantic labels, and reduced-motion support.
- No decorative glassmorphism, gradient text, oversized card radii, decorative grid backgrounds, heavy shadow-plus-border ghost cards, or nested-card noise.
- `examples/ui_showcase` uses default Rakit UI and contains no private stylesheet.
- Every UI PR starts from the previous merged UI PR and remains independently reviewable.
- Local fast suite may use `uv run pytest -n auto --cov`; CI serial verification remains authoritative.
- No tag, GitHub Release, PyPI, or TestPyPI action in this program.
- Keep the approved design spec and this implementation plan in the repo during implementation. Delete both only in UI-08 after the maintainer has saved the pre-implementation copies supplied in chat.

## PR Sequence and Ownership

1. `ui-01-showcase-baseline` — realistic showcase + `/ui-lab`, no redesign yet.
2. `ui-02-design-tokens` — semantic colors, typography hierarchy, spacing/page rhythm, radius/elevation, light/dark foundation.
3. `ui-03-shell-theme-icons` — shell, desktop/mobile navigation, Lucide icon primitive, icon theme popover.
4. `ui-04-core-components` — reusable controls, statuses, feedback, dialogs/popovers, pagination/loading.
5. `ui-05-resource-experience` — **dashboard home + resource list/detail + search/filter + forms/delete**.
6. `ui-06-advanced-operations` — **actions/bulk/relationships/uploads + auth/session surfaces + custom pages**.
7. `ui-07-responsive-a11y-hardening` — responsive, keyboard, contrast, motion, overflow, UX copy, accessibility.
8. `ui-08-final-polish` — final Impeccable review, final matrix, planning-doc cleanup.

Merge each PR before creating the next branch. The bold ownership above is deliberate: dashboard is completed in UI-05, and auth/session presentation is completed in UI-06 so neither surface is implicitly left for “final polish.”

---

## Shared File Map

### Styling / assets

- `packages/rakit-web/src/rakit_web/assets/rakit.css` — Tailwind maintainer source.
- `packages/rakit-web/src/rakit_web/static/rakit.css` — generated committed output.
- `packages/rakit-web/src/rakit_web/static/theme.js` — early theme resolution/persistence.
- `packages/rakit-web/src/rakit_web/static/rakit-ui.js` — lightweight UI interaction helpers.
- `packages/rakit-web/src/rakit_web/assets.py` — static serving.
- `package.json` — Tailwind 4.1.18 build/watch scripts.

### Shared templates

- `packages/rakit-web/src/rakit_web/templates/base.html`
- `packages/rakit-web/src/rakit_web/templates/components/ui.html`
- `packages/rakit-web/src/rakit_web/templates/components/admin_navigation.html`
- `packages/rakit-web/src/rakit_web/templates/components/admin_mobile_navigation.html`
- `packages/rakit-web/src/rakit_web/templates/components/dashboard_navigation.html`

### Dashboard / resource / form / operation templates

- `packages/rakit-web/src/rakit_web/templates/dashboard/index.html`
- `packages/rakit-web/src/rakit_web/templates/dashboard/_widget.html`
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
- templates under `packages/rakit-web/src/rakit_web/templates/pages/`

### Runtime boundary

Pure visual choices stay out of Python runtime code. The one pre-planned runtime UI addition is registering the icon helper in `packages/rakit-web/src/rakit_web/resource_routes.py::build_templates()`. Other runtime files change only when a focused failing semantic test proves a template lacks data that cannot be derived safely in Jinja; those changes must preserve HTTP/security behavior.

### New focused UI tests

- `tests/test_ui_showcase.py`
- `packages/rakit-web/tests/test_ui_tokens.py`
- `packages/rakit-web/tests/test_icons.py`
- `packages/rakit-web/tests/test_theme_ui.py`
- `packages/rakit-web/tests/test_ui_primitives.py`
- `packages/rakit-web/tests/test_dashboard_ui_maturity.py`
- `packages/rakit-web/tests/test_resource_ui_maturity.py`
- `packages/rakit-web/tests/test_advanced_ui_maturity.py`
- `packages/rakit-web/tests/test_auth_ui_maturity.py`

Existing behavior suites remain authoritative, especially `test_assets.py`, `test_accessibility_contracts.py`, `test_dashboard_runtime.py`, `test_bulk_list_ui.py`, `test_actions.py`, `test_bulk_actions.py`, and auth enforcement tests.

---

# UI-01 — UI Showcase and Visual Baseline

**Goal:** Add a deterministic realistic application and `/ui-lab` page that expose the current default UI before redesign starts.

**Files:**
- Create `examples/ui_showcase/__init__.py`
- Create `examples/ui_showcase/data.py`
- Create `examples/ui_showcase/main.py`
- Create `examples/ui_showcase/README.md`
- Create `tests/test_ui_showcase.py`

**Boundary:** UI-01 changes no `rakit-web` framework CSS/template/runtime code. All scenarios use capabilities already present on `main`.

**Produces:** `examples.ui_showcase.main.admin`, `examples.ui_showcase.main.app`, dashboard `/`, visual QA page `/ui-lab`, and representative registered resource/action/relationship routes.

- [ ] **Step 1: Write the failing example smoke test**

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

- [ ] **Step 2: Verify the test fails for the missing module**

```powershell
uv run pytest tests/test_ui_showcase.py -q
```

Expected: `ModuleNotFoundError: No module named 'examples.ui_showcase'`.

- [ ] **Step 3: Add deterministic seeded data**

`data.py` contains Customers, Products, Orders, Categories, Inventory, and Teams with fixed IDs/dates/currency values. Include long names, missing optional values, paid/pending/refunded/cancelled orders, low/healthy stock, multiple relationships, and enough records for pagination/filtering. No randomness and no wall-clock-dependent assertions.

- [ ] **Step 4: Compose the showcase through public Rakit APIs**

Follow `examples/internal_tools/main.py`: create `Admin(admin_id="ui_showcase", title="Rakit Commerce", debug=True, ...)`, development-only auth/session/idempotency implementations, six resources, supported actions such as Approve/Cancel/Archive/Refund/Publish/Duplicate/Refresh/Export, relationships, `PageDefinition(page_id="ui_lab", path="/ui-lab", label="UI Lab", ...)`, and `app = admin.asgi()`.

- [ ] **Step 5: Expand the smoke test into deterministic UI coverage**

Assert seeded customer/order/product values, links to major resources, and `/ui-lab` headings: Typography, Buttons, Fields, Status, Feedback, Tables, Empty states, Loading states, Errors, Theme.

```powershell
uv run pytest tests/test_ui_showcase.py -q
```

Expected: PASS.

- [ ] **Step 6: Add maintainer instructions**

`README.md` includes:

```powershell
uv sync --extra examples
uv run python -m examples.ui_showcase.main
```

Document local URL, demo credentials, `/ui-lab`, and explicitly state that the example has no private stylesheet.

- [ ] **Step 7: Verify existing dashboard example plus showcase**

```powershell
uv run pytest tests/test_dashboard_example.py tests/test_ui_showcase.py -q
```

- [ ] **Step 8: Commit and run the PR gate**

```powershell
git add examples/ui_showcase tests/test_ui_showcase.py
git commit -m "feat(examples): add UI showcase baseline"
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest -n auto --cov
uv run mkdocs build --strict
uv run python scripts/check_artifacts.py
git status --short
```

---

# UI-02 — Tailwind Design Tokens, Typography, Spacing, and Color Foundation

**Goal:** Establish semantic Tailwind v4 tokens plus the shared typography/spacing rhythm used by every later UI PR, with calibrated light/dark foundations and no interaction restructuring.

**Files:**
- Modify `packages/rakit-web/src/rakit_web/assets/rakit.css`
- Regenerate `packages/rakit-web/src/rakit_web/static/rakit.css`
- Modify `packages/rakit-web/src/rakit_web/templates/base.html`
- Modify `packages/rakit-web/src/rakit_web/templates/components/ui.html`
- Create `packages/rakit-web/tests/test_ui_tokens.py`
- Keep `packages/rakit-web/tests/test_assets.py` and `test_accessibility_contracts.py` green

**Produces:** semantic token families for brand, background, surface, border, text, focus, status, typography, radius, elevation, and reusable spacing/page rhythm while preserving existing `.rakit-*` primitive names.

- [ ] **Step 1: Write failing token contract tests**

```python
from pathlib import Path

SOURCE = Path("packages/rakit-web/src/rakit_web/assets/rakit.css")


def test_rakit_theme_defines_semantic_design_roles() -> None:
    css = SOURCE.read_text(encoding="utf-8")
    for token in (
        "--color-rakit-brand-600:",
        "--color-rakit-bg:",
        "--color-rakit-surface:",
        "--color-rakit-border:",
        "--color-rakit-text:",
        "--color-rakit-success:",
        "--color-rakit-warning:",
        "--color-rakit-danger:",
        "--color-rakit-info:",
        "--font-sans:",
    ):
        assert token in css
```

- [ ] **Step 2: Verify failure**

```powershell
uv run pytest packages/rakit-web/tests/test_ui_tokens.py -q
```

- [ ] **Step 3: Define semantic color and structural tokens**

Use OKLCH for brand 50–950 and semantic roles. Add background/surface/subtle/raised, border/strong-border, text/muted, focus, compact radius, restrained elevation, and reusable transition values.

- [ ] **Step 4: Define typography hierarchy**

Use one primary sans family stack; establish consistent display/page heading, section heading, body, label, help, metadata, table, and code/identifier treatments. Keep long body copy within roughly 65–75ch where applicable and avoid overly tight display letter spacing.

- [ ] **Step 5: Define spacing/page rhythm**

Normalize page gutters, section gaps, panel padding, form field rhythm, compact table/control density, and mobile spacing. Do not create bespoke CSS classes for every local wrapper; use Tailwind spacing utilities and reusable tokens only where patterns recur.

- [ ] **Step 6: Migrate base primitives to semantic utilities**

Keep `.rakit-button`, secondary/quiet/danger, `.rakit-input`, `.rakit-select`, `.rakit-panel`, header/body, error, chip, dialog names. Replace generic blue/slate role usage with semantic Rakit utilities.

- [ ] **Step 7: Calibrate dark mode independently**

Ensure readable dark surfaces, muted text, focus, borders, status colors, typography, and elevation. Do not simply invert light colors.

- [ ] **Step 8: Build and verify**

```powershell
bun run css:build
uv run pytest packages/rakit-web/tests/test_ui_tokens.py packages/rakit-web/tests/test_assets.py packages/rakit-web/tests/test_accessibility_contracts.py tests/test_ui_showcase.py -q
```

- [ ] **Step 9: Inspect showcase light/dark and commit**

Inspect dashboard, list, detail, form, and UI Lab for hierarchy/rhythm as well as color. Reject washed-out muted text, excessive brand surfaces, indistinguishable dark surfaces, cramped typography, or inconsistent spacing.

```powershell
git add packages/rakit-web/src/rakit_web/assets/rakit.css packages/rakit-web/src/rakit_web/static/rakit.css packages/rakit-web/src/rakit_web/templates/base.html packages/rakit-web/src/rakit_web/templates/components/ui.html packages/rakit-web/tests/test_ui_tokens.py
git commit -m "style(web): establish Rakit design foundation"
```

Run the full PR gate from UI-01.

---

# UI-03 — App Shell, Navigation, Theme Switcher, and Icons

**Goal:** Add a safe server-side Lucide subset, icon-based theme chooser, and mature desktop/mobile navigation.

**Files:**
- Create `packages/rakit-web/src/rakit_web/icons.py`
- Create `packages/rakit-web/src/rakit_web/static/LUCIDE_LICENSE.txt`
- Create `packages/rakit-web/src/rakit_web/static/LUCIDE_PROVENANCE.md`
- Create `packages/rakit-web/tests/test_icons.py`
- Create `packages/rakit-web/tests/test_theme_ui.py`
- Modify `packages/rakit-web/src/rakit_web/resource_routes.py`
- Modify `packages/rakit-web/src/rakit_web/templates/base.html`
- Modify `packages/rakit-web/src/rakit_web/templates/components/ui.html`
- Modify `packages/rakit-web/src/rakit_web/templates/components/admin_navigation.html`
- Modify `packages/rakit-web/src/rakit_web/templates/components/admin_mobile_navigation.html`
- Modify `packages/rakit-web/src/rakit_web/static/theme.js`
- Modify `packages/rakit-web/src/rakit_web/static/rakit-ui.js`
- Modify `packages/rakit-web/src/rakit_web/assets/rakit.css`
- Regenerate `packages/rakit-web/src/rakit_web/static/rakit.css`

**Produces:** `render_icon(name: str, *, size: int = 18, decorative: bool = True, label: str | None = None) -> Markup` and Jinja global `rakit_icon` registered by `resource_routes.build_templates()`.

Initial icon registry: `sun`, `moon`, `monitor`, `search`, `filter`, `chevron-down`, `chevron-left`, `chevron-right`, `menu`, `x`, `plus`, `edit`, `trash`, `more-horizontal`, `check`, `alert-triangle`, `circle-alert`, `info`, `upload`, `download`, `refresh-cw`, `archive`, `external-link`, `users`, `package`, `shopping-cart`, `boxes`, `tag`, `layout-dashboard`.

- [ ] **Step 1: Write failing icon tests**

```python
import pytest
from rakit_web.icons import render_icon


def test_render_icon_rejects_unknown_names() -> None:
    with pytest.raises(KeyError):
        render_icon("<script>alert(1)</script>")


def test_decorative_icon_is_hidden_from_assistive_technology() -> None:
    html = str(render_icon("sun"))
    assert "<svg" in html
    assert 'aria-hidden="true"' in html
```

- [ ] **Step 2: Implement trusted icon registry and safe renderer**

Store only curated Lucide path data in Python constants. Escape accessible labels, validate size against a small positive range, and never accept raw SVG/path markup from callers.

- [ ] **Step 3: Add Lucide license/provenance and register the helper**

Record upstream project/version or commit, retrieval date, vendored icon list, and rendering strategy. Register exactly one Jinja global beside `static_url`:

```python
cast(dict[str, Any], environment.globals)["rakit_icon"] = render_icon
```

- [ ] **Step 4: Write failing theme UI tests**

Render the shell and assert the old `<select data-rakit-theme-select>` is absent, an accessible theme trigger exists, three `data-rakit-theme-option` values exist, System/Light/Dark visible text exists, and active state has semantics.

- [ ] **Step 5: Replace theme select with one icon-triggered popover**

Use monitor/sun/moon icons. Options contain icon + visible text. Preserve keyboard reachability, Escape close, focus return, and clear active state.

- [ ] **Step 6: Refactor `theme.js`**

Synchronize trigger/options/active state, localStorage `rakit.theme`, resolved theme, and OS scheme listener while preserving early no-flash application.

- [ ] **Step 7: Add restrained shell/navigation icons and mature nav hierarchy**

Use icons for dashboard/home, mobile menu, conventional actions, and known showcase resources. Custom user resources remain text-first unless existing framework-neutral metadata supports an icon. Improve active state, group rhythm, focus, touch targets, mobile open/close, long labels, and theme surfaces.

- [ ] **Step 8: Build/test/keyboard-check/commit**

```powershell
bun run css:build
uv run pytest packages/rakit-web/tests/test_icons.py packages/rakit-web/tests/test_theme_ui.py packages/rakit-web/tests/test_accessibility_contracts.py tests/test_ui_showcase.py -q
git add packages/rakit-web/src/rakit_web packages/rakit-web/tests tests/test_ui_showcase.py
git commit -m "feat(web): mature shell theme control and icons"
```

Keyboard-check Tab, Shift+Tab, Enter, Space, Escape; then run the full PR gate.

---

# UI-04 — Core Components

**Goal:** Normalize buttons, icon buttons, fields, statuses, alerts, dialogs, popovers, pagination, and loading primitives.

**Files:**
- Modify `packages/rakit-web/src/rakit_web/assets/rakit.css`
- Regenerate `packages/rakit-web/src/rakit_web/static/rakit.css`
- Modify `packages/rakit-web/src/rakit_web/templates/components/ui.html`
- Modify `packages/rakit-web/src/rakit_web/static/rakit-ui.js`
- Create `packages/rakit-web/tests/test_ui_primitives.py`
- Keep action/bulk/accessibility suites green

- [ ] **Step 1: Write primitive contract tests**

Test primary/secondary/quiet/danger class selection, icon-button accessible names, form error association, disabled state, semantic alerts, dialog title/description semantics, pagination current/disabled state, and loading semantics. Assert stable roles/attributes/classes, not complete HTML snapshots.

- [ ] **Step 2: Verify new tests fail**

```powershell
uv run pytest packages/rakit-web/tests/test_ui_primitives.py -q
```

- [ ] **Step 3: Refine button and icon-button families**

Primary is strongest; secondary/quiet support hierarchy; danger is destructive only; icon-only maintains visible focus and practical touch target; loading preserves readable label/state.

- [ ] **Step 4: Refine field/control families**

Unify text, number, date, select, textarea, checkbox, radio, file input, help, required, read-only, disabled, and error states.

- [ ] **Step 5: Refine status, feedback, dialogs, popovers, pagination, and loading**

Provide neutral/success/warning/danger/info roles with text meaning and optional restrained icons. Keep dialogs usable on short/narrow viewports and HTMX pending feedback understandable without JavaScript-only behavior.

- [ ] **Step 6: Expand `/ui-lab`**

Expose representative default/disabled/error/success/warning/loading variants interactively.

- [ ] **Step 7: Build/test/commit**

```powershell
bun run css:build
uv run pytest packages/rakit-web/tests/test_ui_primitives.py packages/rakit-web/tests/test_accessibility_contracts.py packages/rakit-web/tests/test_actions.py packages/rakit-web/tests/test_bulk_list_ui.py tests/test_ui_showcase.py -q
git add packages/rakit-web/src/rakit_web packages/rakit-web/tests tests/test_ui_showcase.py
git commit -m "style(web): mature core UI primitives"
```

Run the full PR gate.

---

# UI-05 — Dashboard and Resource Experience

**Goal:** Mature the dashboard home and the highest-frequency resource workflows: list/table/search/filter/detail/create/edit/delete/pagination/empty states.

**Files:**
- Modify `packages/rakit-web/src/rakit_web/templates/dashboard/index.html`
- Modify `packages/rakit-web/src/rakit_web/templates/dashboard/_widget.html`
- Modify `packages/rakit-web/src/rakit_web/templates/components/dashboard_navigation.html`
- Modify `packages/rakit-web/src/rakit_web/templates/resources/list.html`
- Modify `packages/rakit-web/src/rakit_web/templates/resources/_table.html`
- Modify `packages/rakit-web/src/rakit_web/templates/resources/_count.html`
- Modify `packages/rakit-web/src/rakit_web/templates/resources/detail.html`
- Modify `packages/rakit-web/src/rakit_web/templates/forms/form.html`
- Modify `packages/rakit-web/src/rakit_web/templates/forms/delete_confirm.html`
- Modify `packages/rakit-web/src/rakit_web/templates/components/ui.html`
- Modify `packages/rakit-web/src/rakit_web/assets/rakit.css`; regenerate static CSS
- Create `packages/rakit-web/tests/test_dashboard_ui_maturity.py`
- Create `packages/rakit-web/tests/test_resource_ui_maturity.py`
- Keep `test_dashboard_runtime.py` and existing resource/form/bulk behavior suites green

- [ ] **Step 1: Write failing dashboard semantic tests**

Assert one clear dashboard page heading, resource navigation, operational sections with meaningful labels, quick-action semantics, and explicit partial/empty presentation. Tests must not require a wall of identical metric cards.

```powershell
uv run pytest packages/rakit-web/tests/test_dashboard_ui_maturity.py -q
```

- [ ] **Step 2: Mature dashboard hierarchy**

Design dashboard as contextual heading → operational summary → attention/recent activity → resource shortcuts/quick actions. In `ui_showcase`, include recent orders, low inventory, recent activity, shortcuts, quick actions, and partial/empty states. Use cards only where they are the best information container.

- [ ] **Step 3: Write failing resource UI semantic tests**

Cover page heading, labeled search/filter controls, table headers, accessible row actions, labeled selection, distinct empty vs filtered-no-results messaging, query-preserving pagination, field-linked validation errors, and explicit delete consequence.

```powershell
uv run pytest packages/rakit-web/tests/test_resource_ui_maturity.py -q
```

- [ ] **Step 4: Redesign list/table/search/filter hierarchy**

Use title/context → primary action → search/filter → active filters → count/selection → table → pagination. Keep compact readable table density, sorting, row hover/selection, aligned numeric/status/action columns, and intentional horizontal overflow.

- [ ] **Step 5: Redesign detail and forms**

Prefer grouped information/definition lists over nested cards. Use coherent field rhythm, help/required/error treatment, long-form sections, clear save/cancel hierarchy, and pending feedback compatible with full-page and HTMX requests.

- [ ] **Step 6: Redesign delete confirmation and empty/no-results states**

State destructive consequences clearly, separate cancel from danger action, and distinguish truly empty resources from a filter returning no matches.

- [ ] **Step 7: Build/test/visual-pass/commit**

```powershell
bun run css:build
uv run pytest packages/rakit-web/tests/test_dashboard_ui_maturity.py packages/rakit-web/tests/test_resource_ui_maturity.py packages/rakit-web/tests/test_dashboard_runtime.py packages/rakit-web/tests/test_bulk_list_ui.py packages/rakit-web/tests/test_accessibility_contracts.py tests/test_ui_showcase.py -q
uv run pytest packages/rakit-web/tests -q
git add packages/rakit-web/src/rakit_web packages/rakit-web/tests tests/test_ui_showcase.py
git commit -m "style(web): mature dashboard and resource workflows"
```

Inspect dashboard, many rows, no-results, empty resource, long/missing values, detail, multi-error form validation, delete confirm, desktop/mobile. Run the full PR gate.

---

# UI-06 — Advanced Operations, Auth/Session, and Custom Pages

**Goal:** Mature actions, bulk operations, relationships, uploads, auth/session surfaces, custom pages, previews, confirmations, and result feedback.

**Files:**
- Modify action templates listed in Shared File Map
- Modify relationship templates listed in Shared File Map
- Modify existing upload presentation in form/file-upload surfaces
- Modify `packages/rakit-web/src/rakit_web/templates/auth/login.html`
- Modify templates under `packages/rakit-web/src/rakit_web/templates/pages/`
- Modify relevant dashboard/page templates only where advanced operation presentation requires it
- Modify `packages/rakit-web/src/rakit_web/assets/rakit.css`; regenerate static CSS
- Modify `packages/rakit-web/src/rakit_web/static/rakit-ui.js` only for progressive-enhancement behavior
- Create `packages/rakit-web/tests/test_advanced_ui_maturity.py`
- Create `packages/rakit-web/tests/test_auth_ui_maturity.py`
- Keep action/bulk/relationship/upload/page/auth enforcement suites green

- [ ] **Step 1: Write failing advanced semantic tests**

Cover confirmation hierarchy, preview readability without JS, success/rejected/validation feedback, bulk selected count, relationship accessible labels, empty/high-cardinality relationship states, upload help/error text, and custom-page hierarchy.

```powershell
uv run pytest packages/rakit-web/tests/test_advanced_ui_maturity.py -q
```

- [ ] **Step 2: Mature actions, bulk UX, relationships, uploads, and custom pages**

Use one hierarchy across page/resource/record actions; show selected count and safe/destructive separation for bulk; refine to-one/to-many/inline/options/preview/error relationships; reuse core upload primitives/icons; give custom pages a consistent page heading/navigation/content rhythm.

- [ ] **Step 3: Write failing auth/session UI tests**

Assert login has one clear heading, labeled identifier/password controls, accessible error presentation for invalid credentials, consistent return/navigation affordance where applicable, and stable semantics for session-expired and forbidden/access-denied presentation without changing auth redirect/status/security behavior.

```powershell
uv run pytest packages/rakit-web/tests/test_auth_ui_maturity.py -q
```

- [ ] **Step 4: Mature auth/session surfaces**

Bring login, invalid credentials, logout/session-expired messaging, and forbidden/access-denied presentation into the same typography/color/feedback system. Do not weaken authentication, CSRF, rate limit, session, or permission boundaries for presentation convenience.

- [ ] **Step 5: Build/test/visual-pass/commit**

```powershell
bun run css:build
uv run pytest packages/rakit-web/tests/test_advanced_ui_maturity.py packages/rakit-web/tests/test_auth_ui_maturity.py packages/rakit-web/tests/test_actions.py packages/rakit-web/tests/test_bulk_actions.py packages/rakit-web/tests/test_bulk_list_ui.py tests/test_ui_showcase.py -q
uv run pytest packages/rakit-web/tests -q
git add packages/rakit-web/src/rakit_web packages/rakit-web/tests tests/test_ui_showcase.py
git commit -m "style(web): mature advanced auth and page UX"
```

Visually exercise approve, refund/cancel, validation, preview, bulk selection, relationship add/remove, empty relationships, upload, custom pages, login invalid credentials, session-expired, and forbidden. Run the full PR gate.

---

# UI-07 — Responsive, Accessibility, Motion, and UX Hardening

**Goal:** Make desktop/tablet/mobile, keyboard, focus, contrast, reduced motion, long content, loading/error/empty states, and UX copy release-quality across every surface completed in UI-01 through UI-06.

**Files:**
- Modify affected `rakit-web` templates/CSS/JS only
- Modify `packages/rakit-web/tests/test_accessibility_contracts.py`
- Modify `tests/test_ui_showcase.py`
- Modify `docs/accessibility.md` to reflect guarantees verified in this PR

- [ ] **Step 1: Expand accessibility contracts before fixes**

Add stable assertions for main landmark, skip link, icon-button names, popover/dialog semantics, form-error linking, representative duplicate-ID safety, and text meaning accompanying status color/icon.

- [ ] **Step 2: Run accessibility tests**

```powershell
uv run pytest packages/rakit-web/tests/test_accessibility_contracts.py tests/test_ui_showcase.py -q
```

- [ ] **Step 3: Perform responsive matrix**

Inspect approximately 1440, 1024, 768, and 390 CSS-pixel widths for shell, dashboard, list, detail, form, action, bulk, relationship, login, custom page, and UI Lab. Fix hierarchy/structure rather than only shrinking typography.

- [ ] **Step 4: Perform keyboard-only matrix**

Verify skip link, desktop/mobile nav, theme chooser, search/filter, row actions, dialogs/popovers, forms, relationships, auth, and return focus.

- [ ] **Step 5: Perform contrast, reduced-motion, and overflow pass**

Verify >=4.5:1 normal and >=3:1 large text in both themes, including placeholder/muted/status text. Ensure content is not gated by animation, reduced-motion removes nonessential animation, HTMX pending feedback remains understandable, and long labels/values do not overflow containers.

- [ ] **Step 6: Clarify UX copy and update accessibility docs**

Use explicit action labels/destructive consequences while preserving domain terminology. Document keyboard/theme/focus/reduced-motion guarantees actually verified.

- [ ] **Step 7: Build/test/commit**

```powershell
bun run css:build
uv run pytest packages/rakit-web/tests tests/test_ui_showcase.py -q
uv run mkdocs build --strict
git add packages/rakit-web/src/rakit_web packages/rakit-web/tests tests/test_ui_showcase.py docs/accessibility.md
git commit -m "fix(web): harden responsive and accessible UX"
```

Run the full PR gate.

---

# UI-08 — Final Impeccable Polish and Planning-Doc Cleanup

> **Completion update (2026-08-19):** The later approved Phase A hardening design supersedes this section where it conflicts with the workflow below. UI-08 found no P0/P1/material-P2 product UI finding after the accepted UI-07 browser matrix and final source audit, so no additional UI source churn was justified. Planning/spec documents are retained when they remain useful architectural history; the unconditional deletion steps below are historical and are not executed.

**Goal:** Resolve final design-quality findings, verify every major surface across themes/viewports, then delete temporary planning docs after copies are confirmed saved.

**Files:** only UI/test files required by final findings, then delete:
- `docs/superpowers/specs/2026-08-17-ui-ux-maturity-design.md`
- `docs/superpowers/plans/2026-08-17-ui-ux-maturity.md`

- [ ] **Step 1: Run Impeccable context against `packages/rakit-web`** and load the product/admin register before evaluating surfaces.

- [ ] **Step 2: Run structured critique/audit** for shell, dashboard, resource list/detail, forms, actions/bulk, relationships, auth/session, custom pages, and `/ui-lab`. Record findings in the PR description rather than another repo planning file.

- [ ] **Step 3: Fix P0/P1 and material P2 findings test-first**

For each semantic/behavior fix: add failing focused test → run it → implement → rerun it → rebuild CSS when source styling changes. Avoid unrelated refactors.

- [ ] **Step 4: Apply layout/typeset/colorize/adapt/harden/polish passes where findings justify them**

The final interface remains simple, clean, restrained, comfortable for long sessions, and icon-supported rather than icon-saturated.

- [ ] **Step 5: Complete final manual matrix**

Verify Shell/navigation, Dashboard, Resource list, Detail, Form, Action/confirm, Bulk, Relationships, Login/auth/session, Custom pages, and UI Lab in Light/Dark/System at Desktop/Tablet/Mobile.

- [ ] **Step 6: Run complete repository gate**

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

Expected: zero failures, coverage >=85%, generated CSS committed, no unintended dirty files.

- [ ] **Step 7: Confirm the maintainer has saved both pre-implementation copies supplied in chat**

Required local copies:
- `2026-08-17-ui-ux-maturity-design.md`
- `2026-08-17-ui-ux-maturity.md`

- [ ] **Step 8: Delete completed planning docs**

```powershell
git rm docs/superpowers/specs/2026-08-17-ui-ux-maturity-design.md
git rm docs/superpowers/plans/2026-08-17-ui-ux-maturity.md
git commit -m "chore: remove completed UI maturity planning docs"
```

- [ ] **Step 9: Re-run docs/artifact-sensitive gates after deletion**

```powershell
uv run mkdocs build --strict
uv run python scripts/check_artifacts.py
git status --short
```

- [ ] **Step 10: Open UI-08 PR without release side effects**

State UI-01 through UI-08 complete, local/CI results, planning-doc cleanup after saved copies, and no tag/release/PyPI action.

---

## Per-PR Review Rules

1. Existing behavior/security semantics remain authoritative.
2. Semantic/behavior markup changes begin with focused failing tests.
3. CSS workflow is source edit → `bun run css:build` → source/generated CSS committed together.
4. Every PR is inspected in `examples/ui_showcase` and `/ui-lab`.
5. If the showcase needs private CSS, fix `rakit-web` instead.
6. Every icon must improve recognition, hierarchy, or conventional control scanning.
7. Tests assert semantics, important text, roles, route behavior, and stable attributes/classes rather than complete HTML snapshots.
8. Runtime Python changes require a concrete semantic presentation need and regression test.
9. Merge UI PRs sequentially.
10. UI maturity completion never triggers release publication automatically.

## Final Definition of Done

- `examples/ui_showcase` is a realistic end-to-end application using default Rakit UI.
- `/ui-lab` exposes deterministic representative components and states.
- Semantic Tailwind tokens replace generic concrete palette usage where appropriate.
- Typography and spacing/rhythm are coherent across all major surfaces.
- Light/dark/system themes are polished and accessible.
- Theme switching uses the icon-triggered System/Light/Dark popover.
- Curated Lucide icons are vendored with license/provenance and rendered server-side through `rakit_icon`.
- Dashboard, resource/form/action/bulk/relationship/auth/session/custom-page surfaces share one interaction hierarchy.
- Desktop/tablet/mobile behavior is intentional.
- Keyboard/focus/contrast/reduced-motion requirements are satisfied.
- All repository gates are green.
- No release-blocking Impeccable findings remain.
- Maintainer has local copies of spec and plan.
- Repo copies of temporary spec/plan are removed in the UI-08 cleanup commit.
- No tag, GitHub Release, PyPI, or TestPyPI publish has been performed automatically.
