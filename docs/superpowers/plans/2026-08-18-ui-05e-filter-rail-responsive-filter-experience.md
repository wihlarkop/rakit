# UI-05E Filter Rail & Responsive Filter Experience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the temporary popover/grid resource filter UI with a scalable desktop right rail and responsive mobile filter experience that renders arbitrary semantic filters consistently while preserving UI-05D query behavior.

**Architecture:** Keep `ResourceFilter` and compiled query semantics untouched in `rakit-core`. Add Web-only immutable presentation policy in `rakit-web`, pass it through `Admin.register(..., web=...)` into `ResourceBinding`, enrich the existing server-built filter presentation model, and render one shared Jinja filter-group macro inside the desktop rail and mobile fallback/drawer containers. Use native HTML disclosures/dialog semantics plus the existing lightweight `rakit-ui.js` enhancement layer; all filtering remains canonical GET navigation without JavaScript requirements.

**Tech Stack:** Python 3.12+, Starlette, Jinja2, HTMX-compatible SSR, Tailwind CSS v4 direct utilities, native `<details>`/`<dialog>`, existing `rakit-ui.js`, pytest, Ruff, ty.

**Spec:** `docs/superpowers/specs/2026-08-18-ui-05e-filter-rail-responsive-filter-experience-design.md`

## Global Constraints

- PR branch: `ui-05e-filter-rail-responsive-filters`; PR target: `ui-05-resource-experience`; never merge this slice directly to `main`.
- Preserve `ResourceFilter` semantic meaning, backend predicates, SQLAlchemy translation, generated REST behavior, and pagination contracts.
- Presentation policy lives in `rakit-web`; do not import Web presentation types into `rakit-core`.
- Zero-configuration resources receive production-quality defaults.
- Filter groups are visually separated by dividers; do not create nested cards per filter.
- Desktop rail is visible by default and manual hide/show never mutates query state.
- Mobile uses the same filter-group renderer as desktop; no-JavaScript filtering remains usable through a server-rendered fallback.
- Choice/boolean selections are canonical GET links; text/number/date/date-range retain explicit Apply forms.
- Keep semantic active-filter chips outside the rail.
- Use existing Tailwind tokens/utilities; do not hand-edit generated `static/rakit.css`.
- Feature/source/template/JS work comes first; focused/regression tests are added after implementation and non-test review per maintainer preference.
- No UI-06 auth/session work, OR/NOT DSL, remote dynamic-choice provider, release, tag, TestPyPI, or PyPI work.

---

### Task 1: Web-only Resource Filter Presentation Policy

**Files:**
- Create: `packages/rakit-web/src/rakit_web/resource_presentation.py`
- Modify: `packages/rakit-web/src/rakit_web/admin.py`
- Modify: `packages/rakit-web/src/rakit_web/resource_routes.py`
- Modify: `packages/rakit/src/rakit/__init__.py`

**Interfaces:**
- Produces `FilterGroupPresentation`, `FilterPanelPresentation`, and `ResourceWebPresentation` immutable Web-only configuration types.
- Extends `Admin.register(admin_cls, *, web: ResourceWebPresentation | None = None)` without changing existing call sites.
- `ResourceBinding.presentation: ResourceWebPresentation` gives route/template presentation code a validated policy.

- [ ] **Step 1: Create immutable presentation policy types.**

Implement `resource_presentation.py` with frozen/slotted dataclasses:

```python
@dataclass(frozen=True, slots=True)
class FilterGroupPresentation:
    expanded_by_default: bool | None = None
    choice_preview_count: int | None = None

@dataclass(frozen=True, slots=True)
class FilterPanelPresentation:
    visible_by_default: bool = True
    collapse_after: int = 4
    choice_collapse_after: int = 8
    choice_preview_count: int = 6
    groups: Mapping[str, FilterGroupPresentation] = field(default_factory=dict)

@dataclass(frozen=True, slots=True)
class ResourceWebPresentation:
    filters: FilterPanelPresentation = field(default_factory=FilterPanelPresentation)
```

Validate positive/non-negative thresholds, require preview counts not to exceed the relevant collapse threshold, copy/freeze `groups`, reject blank group ids, and reject non-`FilterGroupPresentation` values.

- [ ] **Step 2: Extend Web Admin registration without touching `rakit-core`.**

Add `_resource_web_presentations: dict[str, ResourceWebPresentation]` to `Admin`. Change the register signature to:

```python
def register(
    self,
    admin_cls: type[ResourceAdmin],
    *,
    web: ResourceWebPresentation | None = None,
) -> None:
```

Normalize `None` to the default presentation. Reject invalid `web` values with `CONFIG_INVALID_RESOURCE_POLICY`. After effective filter definitions are known, validate every `web.filters.groups` key against semantic/effective `filter_id` values; fail with details reason `unknown_web_filter_presentation` instead of silently ignoring it. Store the validated presentation only after resource registration succeeds.

- [ ] **Step 3: Pass presentation into `ResourceBinding`.**

Add:

```python
presentation: ResourceWebPresentation = field(default_factory=ResourceWebPresentation)
```

and populate it from `Admin.asgi()` when constructing each binding.

- [ ] **Step 4: Export the Web presentation configuration from the public `rakit` facade.**

Import and add to `__all__`:

```python
FilterGroupPresentation
FilterPanelPresentation
ResourceWebPresentation
```

Existing `admin.register(ResourceAdminClass)` remains source-compatible.

- [ ] **Step 5: Perform source review before tests.**

Confirm by inspection that `packages/rakit-core` has no new dependency/import from `rakit-web` and that generated REST binding construction is unchanged.

- [ ] **Step 6: Commit the feature unit.**

Commit message: `feat(web): add resource filter presentation policy`.

### Task 2: Enrich the Server-side Filter Presentation Model

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/resource_query_ui.py`
- Modify: `packages/rakit-web/src/rakit_web/resource_routes.py`

**Interfaces:**
- `filter_groups(..., presentation: FilterPanelPresentation)` returns generic group metadata for both desktop and mobile renderers.
- Each group exposes `active_count`, `expanded_by_default`, `choice_overflow`, `choice_preview_count`, and choice rows without altering semantic selections.

- [ ] **Step 1: Make filter-group building presentation-aware.**

Extend `filter_groups` to accept `FilterPanelPresentation`. For each group index:

```text
active_count = number of active selections for filter_id
override = presentation.groups.get(filter_id)
default expanded = override.expanded_by_default when not None
otherwise active groups expand
otherwise index < presentation.collapse_after
```

- [ ] **Step 2: Add adaptive choice metadata.**

For choice/boolean groups expose:

```text
choice_overflow = len(choices) > choice_collapse_after
choice_preview_count = group override or panel default
choice_hidden_count = max(0, len(choices) - choice_preview_count)
```

Selected choices that would fall outside the preview must be promoted into the visible preview so current state is never hidden by default; keep stable ordering for all other choices.

- [ ] **Step 3: Preserve canonical GET semantics.**

Do not change `serialize_selection`, `canonical_builder_query`, `_replace_filter_id`, generated API query handling, or predicate resolution. Choice rows continue to point to canonical GET URLs generated from the same query objects.

- [ ] **Step 4: Pass the binding presentation policy from `resource_routes.py`.**

Build `filter_groups` with `binding.presentation.filters`. Add lightweight template context values only when they are truly presentation-wide (for example `filter_panel_visible_by_default`).

- [ ] **Step 5: Review query-reset behavior.**

Confirm filter/search/sort/page-size changes still reset to the first page because `validated_query_params` intentionally does not preserve page/offset/cursor navigation state unless pagination controls explicitly add it.

- [ ] **Step 6: Commit the feature unit.**

Commit message: `feat(web): enrich filter presentation metadata`.

### Task 3: Shared Filter Renderer, Desktop Rail, and Mobile Fallback/Drawer

**Files:**
- Create: `packages/rakit-web/src/rakit_web/templates/resources/_filters.html`
- Modify: `packages/rakit-web/src/rakit_web/templates/resources/_table.html`

**Interfaces:**
- `_filters.html` exports one Jinja macro `render_filter_groups(groups, resource, resource_path, filter_hidden_inputs, instance_id)` used by every viewport container.
- Desktop and mobile render identical group ordering/control semantics through that macro.

- [ ] **Step 1: Create the shared filter-group macro.**

Render each filter as a `<details>` section with:

- a `<summary>` heading containing label, active count, and chevron;
- `open` when `group.expanded_by_default` is true;
- semantic `aria`/visible heading treatment;
- `border-t border-rakit-border` between adjacent groups;
- no nested card surface per group.

Use `instance_id` to keep form/input ids unique when the macro is rendered in desktop, mobile fallback, and mobile dialog containers.

- [ ] **Step 2: Render choice/boolean as vertical single-choice options.**

Render `All` plus each choice as full-width text links with an explicit selected indicator and `aria-current="true"` for the active canonical query option. Do not use horizontal chips in the rail.

For overflow groups, render the first preview choices plus a native `<details data-rakit-choice-overflow>` containing the remaining choices in a bounded `max-h-* overflow-y-auto` area. The no-JS summary remains usable; enhancement may switch the label between Show more/Show less.

- [ ] **Step 3: Render text/number/date/date-range/legacy forms vertically.**

Keep canonical hidden inputs and existing builder parameter names. Inputs use existing `rakit-input`/`rakit-select` primitives and direct Tailwind layout utilities. Each form keeps an explicit Apply button.

- [ ] **Step 4: Replace the current filter popover/grid in `_table.html`.**

Keep search and total summary at the top. Keep active-filter chips outside the rail. Wrap the result table and desktop filter rail in a responsive `lg:grid`/flex composition where the table takes remaining width and the rail has a restrained fixed/max width separated by a vertical border.

Desktop rail includes a JS-enhanced `Hide filters` control but remains visible when JavaScript is unavailable.

- [ ] **Step 5: Add mobile no-JS fallback and enhanced drawer.**

Below the mobile toolbar, render:

1. a `<details>` fallback containing the shared filter renderer and visible without JS;
2. a hidden Filters trigger + native `<dialog data-rakit-dialog>` drawer using the same macro, enabled by `rakit-ui.js` when JS loads.

The dialog uses direct Tailwind utilities for fixed right-side placement and existing generic dialog close/backdrop/focus behavior.

- [ ] **Step 6: Keep active chips globally visible.**

The existing `filter_presentations` chips and `Clear all filters` stay above the result grid so they remain visible when the rail is hidden and on mobile.

- [ ] **Step 7: Commit the feature unit.**

Commit message: `feat(web): add responsive resource filter rail`.

### Task 4: Lightweight Progressive Enhancement State

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/static/rakit-ui.js`

**Interfaces:**
- Enhances desktop rail show/hide, mobile fallback-to-dialog upgrade, disclosure persistence, and choice-overflow copy.
- Filtering itself remains normal canonical GET navigation.

- [ ] **Step 1: Add filter UI initialization.**

On DOMContentLoaded and `htmx:afterSwap`, discover `[data-rakit-filter-ui]` roots and initialize them idempotently.

- [ ] **Step 2: Upgrade mobile fallback to dialog only when JS is available.**

Hide `[data-rakit-filter-mobile-fallback]`, reveal `[data-rakit-filter-drawer-trigger]`, and rely on existing generic-dialog functions for opening/closing/focus restoration.

- [ ] **Step 3: Implement desktop rail hide/show as presentation-only state.**

Toggle `hidden` on the desktop rail and switch result-grid layout classes/data state without changing any query input/URL. Persist the preference in `sessionStorage` using a key scoped by resource id; gracefully ignore storage errors.

- [ ] **Step 4: Persist filter-group disclosure state opportunistically.**

Listen for `<details data-rakit-filter-group>` toggle events and persist open/closed state by resource/filter id in `sessionStorage`. Initial server defaults remain authoritative when no stored state exists.

- [ ] **Step 5: Enhance choice overflow copy.**

For `<details data-rakit-choice-overflow>`, update the visible summary text to `Show less` while open and restore the server-provided `Show N more` label when closed. Native details remains fully usable without JS.

- [ ] **Step 6: Ensure initialization remains idempotent after HTMX swaps.**

Use dataset markers/WeakMap patterns consistent with existing dialog enhancement so event listeners are not duplicated.

- [ ] **Step 7: Commit the feature unit.**

Commit message: `feat(web): enhance resource filter interactions`.

### Task 5: Expand the Deterministic UI Showcase

**Files:**
- Modify: `examples/ui_showcase/main.py`
- Modify if necessary: `examples/ui_showcase/data.py`
- Modify: `examples/ui_showcase/README.md`

**Interfaces:**
- Showcase visibly exercises automatic filter-group collapse and long choice overflow using only public Rakit APIs/default UI.

- [ ] **Step 1: Add a many-filter showcase resource configuration.**

Extend one existing resource (prefer Customers/Products rather than inventing a seventh resource) to expose more than four semantic/effective filter groups while preserving deterministic data.

- [ ] **Step 2: Add a long-choice filter scenario.**

Use a deterministic choice filter with more than eight options and labels long enough to exercise wrapping. Do not add showcase-only CSS.

- [ ] **Step 3: Exercise the public Web presentation override once.**

Register one showcase resource using `admin.register(ResourceAdminClass, web=ResourceWebPresentation(...))` with a small behavior override (for example one group explicitly collapsed/expanded or a different preview count) so the public API is executable rather than test-only.

- [ ] **Step 4: Update README visual QA notes.**

Document desktop rail, group dividers, long choices, rail hide/show, active chips, and mobile drawer/fallback as UI-05E inspection targets.

- [ ] **Step 5: Run non-test source/visual consistency review.**

Inspect the changed templates for duplicate ids, unsupported dynamically generated Tailwind classes, raw backend predicate leakage, and any JS-only filtering path.

- [ ] **Step 6: Commit the feature unit.**

Commit message: `feat(examples): exercise scalable filter presentation`.

### Task 6: Focused Regression Coverage (Tests Last)

**Files:**
- Create: `packages/rakit-web/tests/test_resource_filter_presentation.py`
- Modify: `packages/rakit-web/tests/test_resource_query_configuration.py`
- Modify: `packages/rakit-web/tests/test_resource_list_ui_maturity.py`
- Modify: `tests/test_ui_showcase.py`
- Modify: `packages/rakit/tests/test_query_configuration_facade.py`

**Interfaces:**
- Locks down public presentation configuration, registration validation, generic markup, no-JS fallback, long choices, active groups, and public exports without testing pixel styling.

- [ ] **Step 1: Add presentation-policy validation tests.**

Cover defaults, invalid thresholds, blank group ids, invalid group objects, and immutable/copy-safe group mappings.

- [ ] **Step 2: Add registration-boundary tests.**

Assert existing `admin.register(ResourceAdminClass)` remains valid; `web=ResourceWebPresentation(...)` is accepted; unknown presentation `filter_id` fails closed with `CONFIG_INVALID_RESOURCE_POLICY` and reason `unknown_web_filter_presentation`.

- [ ] **Step 3: Add filter presentation model tests.**

Assert:

- ≤4 groups default expanded;
- >4 groups collapse after four;
- active group beyond threshold expands;
- per-group override wins;
- active count reflects semantic selections;
- long choice metadata is bounded;
- selected choice outside the initial preview is promoted into visible choices.

- [ ] **Step 4: Add rendered HTML contract tests.**

Assert desktop rail, dividers, vertical choices, active chips, mobile no-JS `<details>` fallback, hidden JS drawer trigger, dialog drawer, unique ids, and absence of the old `data-rakit-filter-panel` popover/grid contract.

- [ ] **Step 5: Add public facade/showcase tests.**

Assert the three presentation types import from `rakit`, showcase routes render the long-choice/many-filter scenarios, and no private showcase stylesheet is introduced.

- [ ] **Step 6: Run focused tests.**

Run:

```powershell
uv run pytest packages/rakit-web/tests/test_resource_filter_presentation.py packages/rakit-web/tests/test_resource_query_configuration.py packages/rakit-web/tests/test_resource_list_ui_maturity.py packages/rakit/tests/test_query_configuration_facade.py tests/test_ui_showcase.py -q
```

Expected: PASS.

- [ ] **Step 7: Run formatting, lint, typing, and the complete project gate.**

Run:

```powershell
uv sync --all-packages --dev --locked
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
uv run mkdocs build --strict
uv run python scripts/check_artifacts.py
```

Expected: all checks PASS. CI remains authoritative across the supported Python/dependency matrix.

- [ ] **Step 8: Update PR #23 summary with implementation and verification results.**

Keep PR #23 targeting `ui-05-resource-experience`. Do not mark the UI-05 integration PR ready for `main` until maintainer browser acceptance succeeds.

- [ ] **Step 9: Commit the test/verification unit.**

Commit message: `test(web): cover responsive filter presentation`.
