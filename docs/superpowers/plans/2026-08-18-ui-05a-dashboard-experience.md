# UI-05A Dashboard Experience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mature the default Rakit dashboard into a calm, generic operational home page driven entirely by registered launchers and existing widget definitions.

**Architecture:** Preserve dashboard runtime contracts and HTMX widget endpoints. Change presentation in Jinja/Tailwind first, extend the deterministic showcase for visual QA, then add focused semantic tests after the complete feature surface is visually coherent. Python runtime changes are not expected unless the existing dashboard context demonstrably lacks safe presentation data.

**Tech Stack:** Python 3.12+, Starlette, Jinja2, HTMX, Tailwind CSS v4, server-rendered Lucide icons, pytest, Ruff, ty.

## Global Constraints

- Base branch for implementation: `ui-05-resource-experience`.
- Feature branch: `ui-05a-dashboard-experience`.
- Merge destination: `ui-05-resource-experience`, not `main`.
- Preserve launcher/widget permission and capability filtering.
- Preserve existing widget size values: `small`, `medium`, `large`, `full`.
- Preserve lazy widget and refresh endpoint behavior.
- No application-specific KPI/domain assumptions in framework templates/runtime.
- `examples/ui_showcase` may use commerce-specific examples, but framework code may not.
- Use semantic Rakit tokens instead of direct slate/blue styling in modified built-in dashboard templates where equivalent tokens exist.
- Keep SSR/no-JS rendering authoritative; HTMX is enhancement only.
- Use UI-04 primitives for alerts/loading/icon buttons where practical.
- Do not add private showcase CSS.
- Execution order is feature first -> visual review -> tests at end -> verification.

## File Structure

Primary implementation:

- `packages/rakit-web/src/rakit_web/templates/dashboard/index.html` — dashboard hierarchy, launchers, page empty state.
- `packages/rakit-web/src/rakit_web/templates/dashboard/_widget.html` — widget shell, loading, refresh, error, value/text/table/list presentation.
- `packages/rakit-web/src/rakit_web/templates/components/dashboard_navigation.html` — modify only if dashboard-local navigation presentation needs semantic alignment.
- `packages/rakit-web/src/rakit_web/assets/rakit.css` — reusable dashboard primitives only when repeated styling warrants a class.
- `packages/rakit-web/src/rakit_web/static/rakit.css` — generated output, rebuilt with Bun only.
- `examples/ui_showcase/main.py` and existing showcase widget templates/data — deterministic operational examples.

Test phase:

- Create `packages/rakit-web/tests/test_dashboard_ui_maturity.py`.
- Modify `tests/test_ui_showcase.py` only where showcase contract coverage is needed.
- Preserve `packages/rakit-web/tests/test_dashboard_runtime.py` and accessibility/assets suites.

---

### Task 1: Mature Dashboard Page Hierarchy and Quick Access

**Files:**
- Modify `packages/rakit-web/src/rakit_web/templates/dashboard/index.html`
- Modify `packages/rakit-web/src/rakit_web/assets/rakit.css` only if a reusable launcher primitive is justified

**Interfaces:**
- Consumes existing `dashboard.title`, `launchers`, and `widgets` template context.
- Produces exactly one dashboard `<h1>`, a `Quick access` section when launchers exist, an `Overview`/operational widget section when widgets exist, and a page-level empty state only when both are absent.

- [ ] **Step 1: Replace direct palette utilities in the dashboard header with semantic Rakit roles.**

Keep the existing compact hierarchy: eyebrow `Dashboard`, registered title, and short supporting copy. Do not introduce hero styling or decorative brand blocks.

- [ ] **Step 2: Refine launcher markup into compact operational shortcuts.**

Each launcher remains a normal `<a>` with its existing `launcher.path`, `launcher.label`, and optional `launcher.description`. Use semantic surface/border/text utilities, restrained hover, visible focus, and a small directional affordance. Do not derive new launcher categories or icons from label text.

- [ ] **Step 3: Preserve responsive launcher behavior.**

Use one column on narrow screens and a small multi-column grid on wider screens. Long descriptions wrap; launcher content must not be clipped.

- [ ] **Step 4: Refine page-level empty state.**

When both `launchers` and `widgets` are absent, use a calm dashed/neutral state explaining that registered resources/pages/widgets appear when available. Do not invent a create/setup action.

- [ ] **Step 5: Commit feature-only dashboard hierarchy changes.**

```powershell
git add packages/rakit-web/src/rakit_web/templates/dashboard/index.html packages/rakit-web/src/rakit_web/assets/rakit.css
git commit -m "style(web): mature dashboard hierarchy and launchers"
```

---

### Task 2: Mature Widget Shell and Result States

**Files:**
- Modify `packages/rakit-web/src/rakit_web/templates/dashboard/_widget.html`
- Modify `packages/rakit-web/src/rakit_web/assets/rakit.css` only for reusable widget treatment

**Interfaces:**
- Consumes current widget object fields: `widget.widget_id`, `widget.definition.label`, `widget.definition.layout.size.value`, `widget.is_lazy`, `widget.widget_path`, `widget.result`, and existing result shapes.
- Produces unchanged HTMX targets/URLs with improved semantic presentation.

- [ ] **Step 1: Convert widget container/header/body styling to the shared semantic design system.**

Preserve current responsive `md:col-span-12` / `xl:col-span-*` mapping exactly. Use `rakit-panel` or equivalent semantic border/surface/elevation treatment without nested-card noise.

- [ ] **Step 2: Refine lazy widget state.**

Keep `role="status"`, `aria-live="polite"`, `aria-atomic="true"`, `aria-busy="true"`, `hx-get`, `hx-trigger="load"`, `hx-target`, and `hx-swap`. Decorative skeleton may remain, but retain readable screen-reader text `Loading <label>…`.

- [ ] **Step 3: Refine refresh control.**

Use a restrained secondary or icon-button treatment with the existing endpoint/target/select/swap/disabled/indicator attributes. If icon-only, render Lucide `refresh-cw` through `rakit_icon()` and retain `aria-label="Refresh <result label>"`.

- [ ] **Step 4: Refine error state.**

Use the semantic danger alert language from UI-04. Keep safe `result.message`; do not expose exceptions/stack traces. A failed widget remains local to that widget.

- [ ] **Step 5: Refine scalar, text, table, and item-list result presentation.**

Use semantic Rakit text/border roles. Tables stay compact with intentional horizontal overflow; lists use simple dividers. Preserve result data and conditional branches exactly.

- [ ] **Step 6: Refine widget-level empty messages.**

Use `result.empty_message` where supplied; do not invent business remediation.

- [ ] **Step 7: Commit widget feature work.**

```powershell
git add packages/rakit-web/src/rakit_web/templates/dashboard/_widget.html packages/rakit-web/src/rakit_web/assets/rakit.css
git commit -m "style(web): mature dashboard widget states"
```

---

### Task 3: Expand Deterministic Dashboard Showcase

**Files:**
- Modify `examples/ui_showcase/main.py`
- Modify existing `examples/ui_showcase` data/widget templates only when public APIs already support the scenario

**Interfaces:**
- Consumes the existing public dashboard/widget APIs used by the showcase.
- Produces deterministic examples for visual QA without changing framework assumptions.

- [ ] **Step 1: Inventory existing showcase widgets before adding scenarios.**

Reuse current widget result types instead of introducing a new result API. Confirm which public definitions can express scalar, table/list, lazy, empty, and error states.

- [ ] **Step 2: Ensure showcase dashboard contains realistic operational variety.**

Target examples: recent orders, low inventory, recent activity, a compact summary/value widget, at least one lazy widget, and at least one empty widget. Add a deterministic error/partial-failure example only if the current public API already supports it without framework shortcuts.

- [ ] **Step 3: Keep all showcase data deterministic.**

No randomness, current-time-dependent assertions, or private CSS.

- [ ] **Step 4: Commit showcase changes.**

```powershell
git add examples/ui_showcase
git commit -m "feat(examples): expand dashboard visual QA states"
```

---

### Task 4: Build CSS and Perform Visual Acceptance

**Files:**
- Regenerate `packages/rakit-web/src/rakit_web/static/rakit.css`

- [ ] **Step 1: Build Tailwind output.**

```powershell
bun run css:build
```

- [ ] **Step 2: Run the showcase.**

```powershell
uv run python -m examples.ui_showcase.main
```

- [ ] **Step 3: Inspect light and dark dashboard surfaces.**

Verify: header hierarchy, long launcher description, mixed widget sizes, table/list widget, lazy loading, refresh state, widget error/empty, page-level empty, narrow-width stacking, and no clipped controls.

- [ ] **Step 4: Fix visual defects in source files, rebuild CSS, and repeat until accepted.**

Do not hand-edit generated CSS.

- [ ] **Step 5: Commit generated CSS after visual acceptance.**

```powershell
git add packages/rakit-web/src/rakit_web/static/rakit.css
git commit -m "build(web): regenerate dashboard experience CSS"
```

---

### Task 5: Add Focused Dashboard Tests After Feature Completion

**Files:**
- Create `packages/rakit-web/tests/test_dashboard_ui_maturity.py`
- Modify `tests/test_ui_showcase.py` as needed

**Interfaces:**
- Tests stable semantics/classes/roles and runtime preservation; no full-page HTML snapshots.

- [ ] **Step 1: Add a dashboard semantic contract test using the real Rakit template/runtime test helpers already used in `test_dashboard_runtime.py`.**

Cover one `<h1>`, `Quick access`, launcher links, widget headings, and page-level empty semantics.

- [ ] **Step 2: Add lazy/refresh contracts.**

Assert lazy widget markup retains `aria-busy`, HTMX load attributes, readable loading context, refresh accessible name, disabled-element behavior, and update target.

- [ ] **Step 3: Add widget error/empty contracts.**

Assert local error uses alert semantics and safe rendered message; empty list/table uses supplied empty message.

- [ ] **Step 4: Add a source-level semantic-token guard for modified built-in dashboard templates.**

Assert the modified templates no longer rely on direct `text-slate-*`, `bg-slate-*`, `border-slate-*`, or `text-blue-*` role styling where migrated to semantic Rakit utilities. Avoid asserting generated CSS snapshots.

- [ ] **Step 5: Extend showcase tests for deterministic dashboard examples only where the showcase changed.**

- [ ] **Step 6: Run focused tests.**

```powershell
uv run pytest `
  packages/rakit-web/tests/test_dashboard_ui_maturity.py `
  packages/rakit-web/tests/test_dashboard_runtime.py `
  packages/rakit-web/tests/test_accessibility_contracts.py `
  packages/rakit-web/tests/test_assets.py `
  -q
```

Run root showcase tests separately if fixture/conftest isolation requires it:

```powershell
uv run pytest tests/test_ui_showcase.py -q
```

- [ ] **Step 7: Commit tests.**

```powershell
git add packages/rakit-web/tests/test_dashboard_ui_maturity.py tests/test_ui_showcase.py
git commit -m "test(web): cover dashboard experience contracts"
```

---

### Task 6: Final Verification and Integration PR

- [ ] **Step 1: Run static quality gates.**

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

- [ ] **Step 3: Verify clean tree and inspect commits.**

```powershell
git status --short
git log --oneline ui-05-resource-experience..HEAD
```

- [ ] **Step 4: Open PR from `ui-05a-dashboard-experience` to `ui-05-resource-experience`.**

PR must state no resource-list/form/query changes, local verification results, visual acceptance, and no release side effects.

- [ ] **Step 5: Review the PR diff against the UI-05A spec.**

Check capability filtering, HTMX targets, accessible refresh/loading semantics, scope, and direct-palette cleanup.

- [ ] **Step 6: Merge the reviewed UI-05A PR into `ui-05-resource-experience`.**

This merge is pre-authorized by the maintainer. Do not merge to `main`.