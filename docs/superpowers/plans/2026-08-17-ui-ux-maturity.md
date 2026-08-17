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

## PR Sequence

1. `ui-01-showcase-baseline`
2. `ui-02-design-tokens`
3. `ui-03-shell-theme-icons`
4. `ui-04-core-components`
5. `ui-05-resource-experience`
6. `ui-06-advanced-operations`
7. `ui-07-responsive-a11y-hardening`
8. `ui-08-final-polish`

Merge each PR before creating the next branch.

---

## Shared File Map

### Styling / assets

- `packages/rakit-web/src/rakit_web/assets/rakit.css` — Tailwind maintainer source.
- `packages/rakit-web/src/rakit_web/static/rakit.css` — generated committed output.
- `packages/rakit-web/src/rakit_web/static/theme.js` — early theme resolution/persistence.
- `packages/rakit-web/src/rakit_web/static/rakit-ui.js` — lightweight UI interaction helpers.
- `packages/rakit-web/src/rakit_web/assets.py` — static serving.
- `package.json` — `tailwindcss` and `@tailwindcss/cli` pinned at `4.1.18`; `css:build` is the authoritative build command.

### Shared templates

- `packages/rakit-web/src/rakit_web/templates/base.html`
- `packages/rakit-web/src/rakit_web/templates/components/ui.html`
- `packages/rakit-web/src/rakit_web/templates/components/admin_navigation.html`
- `packages/rakit-web/src/rakit_web/templates/components/admin_mobile_navigation.html`
- `packages/rakit-web/src/rakit_web/templates/components/dashboard_navigation.html`

### Resource / form / operation templates

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
- templates under `packages/rakit-web/src/rakit_web/templates/dashboard/`
- templates under `packages/rakit-web/src/rakit_web/templates/pages/`

### Runtime boundary

Pure visual decisions stay out of Python runtime code. The only planned runtime-level UI addition is the icon helper registration in `packages/rakit-web/src/rakit_web/resource_routes.py::build_templates()`. Other runtime files may change only when a failing semantic test demonstrates missing presentation data; that change must remain local to the relevant PR and preserve current HTTP/security behavior.

### New focused UI tests

- `tests/test_ui_showcase.py`
- `packages/rakit-web/tests/test_ui_tokens.py`
- `packages/rakit-web/tests/test_icons.py`
- `packages/rakit-web/tests/test_theme_ui.py`
- `packages/rakit-web/tests/test_ui_primitives.py`
- `packages/rakit-web/tests/test_resource_ui_maturity.py`
- `packages/rakit-web/tests/test_advanced_ui_maturity.py`

Existing behavior suites remain authoritative, especially `test_assets.py`, `test_accessibility_contracts.py`, `test_dashboard_runtime.py`, `test_bulk_list_ui.py`, `test_actions.py`, and `test_bulk_actions.py`.

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

- [ ] **Step 8: Commit**

```powershell
git add examples/ui_showcase tests/test_ui_showcase.py
git commit -m "feat(examples): add UI showcase baseline"
```

- [ ] **Step 9: Run the PR gate**

```powershell
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest -n auto --cov
uv run mkdocs build --strict
uv run python scripts/check_artifacts.py
git status --short
```

---

# UI-02 — Tailwind Design Tokens and Color Foundation

**Goal:** Establish semantic Tailwind v4 tokens and calibrated light/dark color foundations without restructuring interactions.

**Files:**
- Modify `packages/rakit-web/src/rakit_web/assets/rakit.css`
- Regenerate `packages/rakit-web/src/rakit_web/static/rakit.css`
- Modify `packages/rakit-web/src/rakit_web/templates/base.html`
- Modify `packages/rakit-web/src/rakit_web/templates/components/ui.html`
- Create `packages/rakit-web/tests/test_ui_tokens.py`
- Keep `packages/rakit-web/tests/test_assets.py` and `test_accessibility_contracts.py` green

**Produces:** semantic token families for brand, background, surface, border, text, focus, semantic states, radius, and elevation while preserving existing `.rakit-*` primitive class names.

- [ ] **Step 1: Write failing token contract tests**

```python
from pathlib import Path

SOURCE = Path("packages/rakit-web/src/rakit_web/assets/rakit.css")


def test_rakit_theme_defines_semantic_color_roles() -> None:
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
    ):
        assert token in css
```

- [ ] **Step 2: Verify failure**

```powershell
uv run pytest packages/rakit-web/tests/test_ui_tokens.py -q
```

- [ ] **Step 3: Define the token system in `@theme`**

Use OKLCH for Rakit-owned brand 50–950 and semantic roles. Add neutral application roles for background/surface/subtle/raised, border/strong-border, text/muted, focus, compact radius, and restrained elevation.

- [ ] **Step 4: Migrate base primitives to semantic utilities**

Keep `.rakit-button`, secondary/quiet/danger, `.rakit-input`, `.rakit-select`, `.rakit-panel`, header/body, error, chip, dialog public class names. Replace hard-coded generic blue/slate role usage with Rakit semantic utilities.

- [ ] **Step 5: Calibrate dark mode independently**

Ensure separate readable dark surfaces, muted text, focus, border, and semantic status treatments. Do not merely invert the light palette.

- [ ] **Step 6: Build CSS**

```powershell
bun run css:build
```

- [ ] **Step 7: Run focused verification**

```powershell
uv run pytest packages/rakit-web/tests/test_ui_tokens.py packages/rakit-web/tests/test_assets.py packages/rakit-web/tests/test_accessibility_contracts.py tests/test_ui_showcase.py -q
```

- [ ] **Step 8: Inspect showcase light/dark**

Run `uv run python -m examples.ui_showcase.main`; inspect dashboard, list, detail, form, and UI Lab. Reject washed-out muted text, excessive brand surfaces, and indistinguishable dark surfaces.

- [ ] **Step 9: Commit and run full PR gate**

```powershell
git add packages/rakit-web/src/rakit_web/assets/rakit.css packages/rakit-web/src/rakit_web/static/rakit.css packages/rakit-web/src/rakit_web/templates/base.html packages/rakit-web/src/rakit_web/templates/components/ui.html packages/rakit-web/tests/test_ui_tokens.py
git commit -m "style(web): establish Rakit design tokens"
```

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

- [ ] **Step 3: Add Lucide license and provenance**

Provenance records upstream project/version or commit, retrieval date, vendored icon list, and server-side rendering strategy.

- [ ] **Step 4: Register `rakit_icon` in `resource_routes.build_templates()`**

Add exactly one Jinja global beside `static_url`:

```python
cast(dict[str, Any], environment.globals)["rakit_icon"] = render_icon
```

- [ ] **Step 5: Write failing theme UI tests**

Render the shell and assert: no `<select data-rakit-theme-select>`, accessible theme trigger exists, three `data-rakit-theme-option` values exist, option text contains System/Light/Dark, and active state is represented semantically.

- [ ] **Step 6: Replace theme select with one icon-triggered popover**

Use monitor/sun/moon icons. Menu options contain icon + text. Preserve keyboard reachability, Escape close, and focus return.

- [ ] **Step 7: Refactor `theme.js`**

Synchronize `data-rakit-theme-trigger`, `data-rakit-theme-option`, active state, localStorage `rakit.theme`, resolved theme, and OS scheme listener while preserving early no-flash application.

- [ ] **Step 8: Add restrained shell/navigation icons**

Use icons for dashboard/home, mobile menu, conventional actions, and known showcase resources. Custom user resources remain text-first unless they already provide framework-neutral presentation metadata.

- [ ] **Step 9: Refine shell navigation**

Improve active state, group rhythm, hover/focus, touch targets, mobile open/close, long labels, and light/dark shell surfaces without changing navigation-provider contracts.

- [ ] **Step 10: Build and test**

```powershell
bun run css:build
uv run pytest packages/rakit-web/tests/test_icons.py packages/rakit-web/tests/test_theme_ui.py packages/rakit-web/tests/test_accessibility_contracts.py tests/test_ui_showcase.py -q
```

- [ ] **Step 11: Commit and run full PR gate**

```powershell
git add packages/rakit-web/src/rakit_web packages/rakit-web/tests tests/test_ui_showcase.py
git commit -m "feat(web): mature shell theme control and icons"
```

Keyboard-check Tab, Shift+Tab, Enter, Space, Escape for theme and mobile navigation.

---

# UI-04 — Core Components

**Goal:** Normalize buttons, icon buttons, fields, statuses, alerts, dialogs, pagination, and loading primitives.

**Files:**
- Modify `packages/rakit-web/src/rakit_web/assets/rakit.css`
- Regenerate `packages/rakit-web/src/rakit_web/static/rakit.css`
- Modify `packages/rakit-web/src/rakit_web/templates/components/ui.html`
- Modify `packages/rakit-web/src/rakit_web/static/rakit-ui.js`
- Create `packages/rakit-web/tests/test_ui_primitives.py`
- Keep action/bulk/accessibility suites green

- [ ] **Step 1: Write primitive contract tests**

Create tests for primary/secondary/quiet/danger button class selection, icon-button accessible labels, form error association, disabled state, semantic alerts, and dialog semantics. Assert roles/attributes and stable `.rakit-*` contracts, not full HTML snapshots.

- [ ] **Step 2: Verify new tests fail**

```powershell
uv run pytest packages/rakit-web/tests/test_ui_primitives.py -q
```

- [ ] **Step 3: Refine button family**

Primary is strongest; secondary and quiet support hierarchy; danger is destructive only; icon-only keeps visible focus and a practical touch target; loading preserves readable label/state.

- [ ] **Step 4: Refine field family**

Unify text/number/date/select/textarea/checkbox/radio/file input, help text, required marker, read-only, disabled, and error states.

- [ ] **Step 5: Refine statuses and feedback**

Provide neutral/success/warning/danger/info visual roles with text meaning and restrained optional icons.

- [ ] **Step 6: Refine dialogs, pagination, and loading**

Dialogs remain usable on short/narrow viewports; pagination has clear current/disabled states; HTMX pending state is visible without blocking non-JS flow.

- [ ] **Step 7: Expand `/ui-lab`**

Expose all core variants interactively in default/disabled/error/success/warning/loading states.

- [ ] **Step 8: Build and verify**

```powershell
bun run css:build
uv run pytest packages/rakit-web/tests/test_ui_primitives.py packages/rakit-web/tests/test_accessibility_contracts.py packages/rakit-web/tests/test_actions.py packages/rakit-web/tests/test_bulk_list_ui.py tests/test_ui_showcase.py -q
```

- [ ] **Step 9: Commit and run full PR gate**

```powershell
git add packages/rakit-web/src/rakit_web packages/rakit-web/tests tests/test_ui_showcase.py
git commit -m "style(web): mature core UI primitives"
```

---

# UI-05 — Resource Experience

**Goal:** Mature list/table/search/filter/detail/create/edit/delete/pagination/empty-state workflows.

**Files:**
- Modify `packages/rakit-web/src/rakit_web/templates/resources/list.html`
- Modify `packages/rakit-web/src/rakit_web/templates/resources/_table.html`
- Modify `packages/rakit-web/src/rakit_web/templates/resources/_count.html`
- Modify `packages/rakit-web/src/rakit_web/templates/resources/detail.html`
- Modify `packages/rakit-web/src/rakit_web/templates/forms/form.html`
- Modify `packages/rakit-web/src/rakit_web/templates/forms/delete_confirm.html`
- Modify `packages/rakit-web/src/rakit_web/templates/components/ui.html`
- Modify `packages/rakit-web/src/rakit_web/assets/rakit.css`; regenerate static CSS
- Create `packages/rakit-web/tests/test_resource_ui_maturity.py`
- Keep existing resource/form/bulk behavior suites green

- [ ] **Step 1: Write resource UI semantic tests**

Cover one page heading, labeled search/filter controls, table headers, accessible row actions, labeled bulk checkboxes, distinct empty vs filtered-no-results messaging, query-preserving pagination, field-linked validation errors, and explicit delete consequence.

- [ ] **Step 2: Verify failures**

```powershell
uv run pytest packages/rakit-web/tests/test_resource_ui_maturity.py -q
```

- [ ] **Step 3: Redesign list hierarchy**

Use title/context → primary action → search/filter → active filters → count/selection → table → pagination. Avoid one card per block.

- [ ] **Step 4: Redesign table ergonomics**

Readable compact density, aligned statuses/numbers/actions, sort affordance, row hover/selection, horizontal overflow wrapper, and no tiny mobile text.

- [ ] **Step 5: Redesign detail hierarchy**

Prefer grouped information and definition-list structures; keep actions clearly prioritized and relationships visually integrated.

- [ ] **Step 6: Redesign forms**

Use consistent field rhythm, help/required/error treatment, sections for long forms, clear save/cancel hierarchy, and pending feedback compatible with full-page and HTMX requests.

- [ ] **Step 7: Redesign delete confirmation**

State the destructive consequence explicitly and separate danger action from cancel/back.

- [ ] **Step 8: Build and verify**

```powershell
bun run css:build
uv run pytest packages/rakit-web/tests/test_resource_ui_maturity.py packages/rakit-web/tests/test_bulk_list_ui.py packages/rakit-web/tests/test_accessibility_contracts.py tests/test_ui_showcase.py -q
uv run pytest packages/rakit-web/tests -q
```

- [ ] **Step 9: Visual workflow pass**

Inspect many rows, filtered no-results, empty resource, long/missing values, detail, create/edit multi-error validation, delete confirm, desktop and mobile.

- [ ] **Step 10: Commit and run full PR gate**

```powershell
git add packages/rakit-web/src/rakit_web packages/rakit-web/tests tests/test_ui_showcase.py
git commit -m "style(web): mature resource workflows"
```

---

# UI-06 — Advanced Operations

**Goal:** Mature actions, bulk operations, relationships, uploads, custom pages, previews, confirmations, and result feedback.

**Files:**
- Modify action templates listed in Shared File Map
- Modify relationship templates listed in Shared File Map
- Modify existing upload presentation in form/file-upload surfaces
- Modify relevant dashboard/page templates
- Modify `packages/rakit-web/src/rakit_web/assets/rakit.css`; regenerate static CSS
- Modify `packages/rakit-web/src/rakit_web/static/rakit-ui.js` only for progressive-enhancement behavior
- Create `packages/rakit-web/tests/test_advanced_ui_maturity.py`
- Keep action/bulk/relationship/upload/page behavior suites green

- [ ] **Step 1: Write advanced semantic tests**

Cover confirmation hierarchy, preview readability without JS, success/rejected/validation feedback, bulk selected count, relationship accessible labels, empty/high-cardinality relationship states, and upload help/error text.

- [ ] **Step 2: Verify failures**

```powershell
uv run pytest packages/rakit-web/tests/test_advanced_ui_maturity.py -q
```

- [ ] **Step 3: Mature action forms and confirmations**

Use one hierarchy across page/resource/record actions with explanatory copy, fields, confirm/back, danger only for destructive actions, and equivalent full-page/HTMX fragments.

- [ ] **Step 4: Mature bulk UX**

Show selected count, compact bulk toolbar, safe/destructive separation, selection state, and existing runtime result summaries.

- [ ] **Step 5: Mature relationships**

Refine to-one, to-many, inline rows, option selection, preview/confirm, validation, empty, and high-cardinality states. Keep ambiguous operations text-labeled.

- [ ] **Step 6: Mature upload/custom pages**

Reuse established primitives/icons; do not add a second widget or styling framework.

- [ ] **Step 7: Build and verify**

```powershell
bun run css:build
uv run pytest packages/rakit-web/tests/test_advanced_ui_maturity.py packages/rakit-web/tests/test_actions.py packages/rakit-web/tests/test_bulk_actions.py packages/rakit-web/tests/test_bulk_list_ui.py tests/test_ui_showcase.py -q
uv run pytest packages/rakit-web/tests -q
```

- [ ] **Step 8: Visual advanced-flow pass**

Exercise approve, refund/cancel destructive confirmation, validation, preview, bulk selection, relationship add/remove, no-related state, upload, and custom pages.

- [ ] **Step 9: Commit and run full PR gate**

```powershell
git add packages/rakit-web/src/rakit_web packages/rakit-web/tests tests/test_ui_showcase.py
git commit -m "style(web): mature advanced operation UX"
```

---

# UI-07 — Responsive, Accessibility, and UX Hardening

**Goal:** Make desktop/tablet/mobile, keyboard, focus, contrast, reduced motion, long content, loading/error/empty states, and UX copy release-quality.

**Files:**
- Modify affected `rakit-web` templates/CSS/JS only
- Modify `packages/rakit-web/tests/test_accessibility_contracts.py`
- Modify `tests/test_ui_showcase.py`
- Modify `docs/accessibility.md` to reflect guarantees verified in this PR

- [ ] **Step 1: Expand accessibility contracts before fixes**

Add stable assertions for main landmark, skip link, icon-button names, dialog semantics, form-error linking, representative duplicate-ID safety, and text meaning accompanying status color/icon.

- [ ] **Step 2: Run accessibility tests**

```powershell
uv run pytest packages/rakit-web/tests/test_accessibility_contracts.py tests/test_ui_showcase.py -q
```

- [ ] **Step 3: Perform responsive pass**

Inspect approximately 1440, 1024, 768, and 390 CSS-pixel widths for dashboard/list/detail/form/action/relationship/login/UI Lab. Fix hierarchy/structure rather than only shrinking typography.

- [ ] **Step 4: Perform keyboard-only pass**

Verify skip link, desktop/mobile nav, theme chooser, search/filter, row actions, dialogs, forms, relationships, and return focus.

- [ ] **Step 5: Perform contrast pass**

Verify >=4.5:1 normal and >=3:1 large text in both themes, including muted/placeholder/status text.

- [ ] **Step 6: Perform reduced-motion and pending-state pass**

No content becomes visible only after animation; reduced-motion disables nonessential motion; HTMX pending feedback stays understandable.

- [ ] **Step 7: Clarify UX copy**

Use explicit action labels and destructive consequences while retaining domain terminology.

- [ ] **Step 8: Update accessibility documentation**

Document the keyboard/theme/focus/reduced-motion guarantees actually verified by tests/manual matrix.

- [ ] **Step 9: Build and verify**

```powershell
bun run css:build
uv run pytest packages/rakit-web/tests tests/test_ui_showcase.py -q
uv run mkdocs build --strict
```

- [ ] **Step 10: Commit and run full PR gate**

```powershell
git add packages/rakit-web/src/rakit_web packages/rakit-web/tests tests/test_ui_showcase.py docs/accessibility.md
git commit -m "fix(web): harden responsive and accessible UX"
```

---

# UI-08 — Final Impeccable Polish and Planning-Doc Cleanup

**Goal:** Resolve final design-quality findings, verify every major surface across themes/viewports, then delete temporary planning docs after copies are confirmed saved.

**Files:** only UI/test files required by final findings, then delete:
- `docs/superpowers/specs/2026-08-17-ui-ux-maturity-design.md`
- `docs/superpowers/plans/2026-08-17-ui-ux-maturity.md`

- [ ] **Step 1: Run Impeccable context against `packages/rakit-web`** and load the product/admin register before evaluating surfaces.

- [ ] **Step 2: Run structured critique/audit** for shell, dashboard, resource list/detail, forms, actions/bulk, relationships, auth, and `/ui-lab`. Record findings in the PR description rather than another repo planning file.

- [ ] **Step 3: Fix P0/P1 and material P2 findings test-first**

For each semantic/behavior fix: add failing focused test → run it → implement → rerun it → rebuild CSS when source styling changes. Avoid unrelated refactors.

- [ ] **Step 4: Apply layout/typeset/colorize/adapt/harden/polish passes where findings justify them**

The final interface remains simple, clean, restrained, comfortable for long sessions, and icon-supported rather than icon-saturated.

- [ ] **Step 5: Complete final manual matrix**

Verify Shell/navigation, Dashboard, Resource list, Detail, Form, Action/confirm, Bulk, Relationships, Login/auth, and UI Lab in Light/Dark/System at Desktop/Tablet/Mobile.

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

- [ ] **Step 7: Confirm the maintainer has saved both files supplied before implementation**

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
- Light/dark/system themes are polished and accessible.
- Theme switching uses the icon-triggered System/Light/Dark popover.
- Curated Lucide icons are vendored with license/provenance and rendered server-side through `rakit_icon`.
- Resource/form/action/bulk/relationship/auth/custom-page surfaces share one interaction hierarchy.
- Desktop/tablet/mobile behavior is intentional.
- Keyboard/focus/contrast/reduced-motion requirements are satisfied.
- All repository gates are green.
- No release-blocking Impeccable findings remain.
- Maintainer has local copies of spec and plan.
- Repo copies of temporary spec/plan are removed in the UI-08 cleanup commit.
- No tag, GitHub Release, PyPI, or TestPyPI publish has been performed automatically.
