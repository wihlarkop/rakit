# UI-07D Advanced Widget Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a typed, extensible presentation system with advanced field and relationship widgets while preserving Rakit's existing core, authorization, validation, storage, and progressive-enhancement contracts.

**Architecture:** Keep typed presentation values and rendering in `rakit-web`, attach resource-specific field/relationship presentation through the existing `ResourceWebPresentation` sidecar, and reuse the current relationship candidate/query routes. Scalar form controls are rendered through one presentation registry instead of template conditionals. Remote autocomplete remains a read-only projection over the existing permission-aware relationship candidate machinery.

**Tech Stack:** Python 3.12+, frozen dataclasses, Starlette/Jinja2, existing HTMX/progressive-enhancement runtime, vanilla JavaScript, Tailwind build already used by `rakit-web`.

**Spec:** `docs/superpowers/specs/2026-08-19-ui-07d-advanced-widget-foundation-design.md`

## Global Constraints

- UI-07D is a presentation subsystem; it must not change canonical business types or create alternate mutation/query/storage engines.
- `rakit-core` must not import `rakit-web` presentation classes.
- Permission, CSRF, submission-token, relationship authorization, candidate visibility, storage policy, and server validation remain authoritative.
- Large relationship candidate sets must not degrade to unbounded native selects.
- Advanced widget JavaScript must be centralized and progressive-enhancement-only.
- Existing `FieldDefinition.widget` behavior remains compatible.
- UI-07D wave 1 excludes TagInput, Repeater, KeyValueEditor, JsonEditor, rich text, code editor, MultiFileUpload, image editing, and generic cross-field composite infrastructure.
- Project workflow override: implement source/behavior first, perform structural review, then add/update regression tests at the end, followed by full CI.

---

### Task 1: Typed presentation values and resource-sidecar contract

**Files:**
- Create: `packages/rakit-web/src/rakit_web/field_presentation.py`
- Modify: `packages/rakit-web/src/rakit_web/resource_presentation.py`
- Modify: `packages/rakit/src/rakit/__init__.py`

**Interfaces:**
- Produces immutable presentation classes: `Select`, `SearchableSelect`, `Autocomplete`, `MultiAutocomplete`, `DatePicker`, `TimePicker`, `DateTimePicker`, `DateRangePicker`, `NumberInput`, `Currency`, `Percentage`, `Checkbox`, `Switch`, `SegmentedControl`, `FileUpload`, `ImageUpload`.
- Produces `PresentationRegistry`, `FieldRenderer`, and `ResolvedFieldPresentation` web-only contracts.
- Extends `ResourceWebPresentation` with immutable mappings `fields: Mapping[str, FieldPresentation]` and `relationships: Mapping[str, RelationshipPresentation]` (both values use the typed presentation base contract).
- Public package `rakit` re-exports the built-in presentation classes and registry-facing configuration types.

- [ ] **Step 1: Implement immutable presentation value objects**

Create `field_presentation.py` with a small frozen base marker and validated frozen dataclasses. Required validation includes:

```python
@dataclass(frozen=True, slots=True)
class Autocomplete(Presentation):
    search_fields: tuple[str, ...] = ()
    display_fields: tuple[str, ...] = ()
    placeholder: str | None = None
    min_query_length: int = 2
    page_size: int = 20

    def __post_init__(self) -> None:
        if self.min_query_length < 0:
            raise ValueError("min_query_length must be non-negative")
        if self.page_size < 1 or self.page_size > 200:
            raise ValueError("page_size must be between 1 and 200")
```

Use the same style for numeric/date/file/boolean classes. `Percentage` must require an explicit scale mode/value rather than guessing. `SegmentedControl` accepts a tuple of typed choices and rejects fewer than 2 choices.

- [ ] **Step 2: Implement registry contracts**

`PresentationRegistry` must register one renderer per presentation type, reject duplicate registrations unless an explicit replace operation is used, and resolve subclasses deterministically. Renderer output is a mapping/view model consumed by templates; renderers do not access data sources directly.

- [ ] **Step 3: Extend `ResourceWebPresentation`**

Normalize `fields` and `relationships` into `MappingProxyType`, validate non-empty string keys, and validate values as supported presentation objects. Preserve the existing `filters` and `actions` behavior unchanged.

- [ ] **Step 4: Export public API**

Re-export built-in presentations from `rakit` so developer configuration can use:

```python
from rakit import Autocomplete, Currency, DateTimePicker, MultiAutocomplete
```

- [ ] **Step 5: Structural review**

Confirm no import path from `rakit-core` to `rakit-web` was introduced and no presentation object participates in core parsing/mutation logic.

---

### Task 2: Scalar field rendering through the presentation registry

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/form_routes.py`
- Modify: `packages/rakit-web/src/rakit_web/templates/forms/form.html`
- Create: `packages/rakit-web/src/rakit_web/templates/forms/_field_control.html`
- Modify: `packages/rakit-web/src/rakit_web/dashboard_admin.py`

**Interfaces:**
- `WriteResourceBinding` gains an optional web-only field presentation mapping/registry reference without changing `FormSchema`.
- `form_routes._form_response()` resolves a presentation for every visible writable field using: explicit sidecar presentation -> legacy `widget` compatibility -> conservative type default.
- `_field_control.html` renders semantic fallback markup plus deterministic `data-rakit-*` hooks.

- [ ] **Step 1: Bind resource field presentation at registration**

Validate configured field presentation keys against the final resource/form field ids when they are available. Unknown configured ids fail closed with the existing invalid-resource-policy error family.

- [ ] **Step 2: Add deterministic presentation resolution**

Implement a helper equivalent to:

```python
def resolve_field_presentation(field: FieldDefinition, configured: Presentation | None) -> Presentation:
    if configured is not None:
        return configured
    if field.widget != "text":
        return legacy_widget_presentation(field.widget)
    return inferred_presentation(field.python_type, is_file=isinstance(field, FileField))
```

Inference must remain conservative; `Decimal` resolves to `NumberInput`, not `Currency`, and `bool` resolves to `Checkbox`, not `Switch`.

- [ ] **Step 3: Build scalar view models in `form_routes`**

Each field control view includes presentation key/config, canonical current/submitted value, descriptions/errors, and file presentation state. No renderer performs validation or storage access.

- [ ] **Step 4: Split field control markup from the page template**

Move field-control markup into `_field_control.html`. Render native semantic fallbacks:

```text
Select/SearchableSelect -> select
DatePicker -> input[type=date]
TimePicker -> input[type=time]
DateTimePicker -> input[type=datetime-local]
NumberInput/Currency/Percentage -> numeric/text numeric-safe fallback
Checkbox/Switch -> checkbox
SegmentedControl -> radio group
FileUpload/ImageUpload -> input[type=file]
```

Preserve existing error/description linkage and current-file retention text.

- [ ] **Step 5: Structural review**

Verify form names, CSRF/submission/concurrency tokens, multipart behavior, `required` rules, and `FormSchema.parse()` inputs remain unchanged.

---

### Task 3: Relationship choice presentations and bounded candidate transport

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/relationship_routes.py`
- Modify: `packages/rakit-web/src/rakit_web/templates/relationships/panel.html`
- Modify: `packages/rakit-web/src/rakit_web/templates/relationships/options.html`
- Create: `packages/rakit-web/src/rakit_web/templates/relationships/picker.html`
- Modify: `packages/rakit-web/src/rakit_web/admin.py` or the existing relationship-binding construction site only as required to pass configured relationship presentation into `RelationshipEditorBinding`.

**Interfaces:**
- `RelationshipEditorBinding` gains `presentation: Presentation | None`.
- Candidate lookup returns both items and bounded continuation metadata rather than dropping page state.
- Existing relationship mutation field names remain canonical; labels are never submitted as identity.

- [ ] **Step 1: Resolve relationship presentation**

Use explicit `ResourceWebPresentation.relationships[relationship_id]` when configured. Otherwise retain current safe relationship UI. Validate cardinality: `Autocomplete` is to-one only; `MultiAutocomplete` is to-many only; incompatible declarations fail during registration/binding.

- [ ] **Step 2: Refactor candidate lookup to preserve pagination metadata**

Replace `_candidate_options()` return-only-items behavior with a small internal page object containing:

```text
items: tuple[RelationshipCandidate, ...]
page/current continuation
has_more/has_next
```

Keep current permission and resource-query path. Enforce configured presentation `page_size` within the existing 1..200 server bound.

- [ ] **Step 3: Upgrade the `/options` helper route**

The enhanced response must expose canonical encoded identities, labels, optional safe secondary description derived only from configured visible fields, selected state, and continuation metadata. It must remain authorization-protected and cache-disabled.

- [ ] **Step 4: Add no-JS picker fallback**

Add a server-rendered picker page/action under the existing compiled relationship route. It provides a normal search form, bounded candidate page, canonical selection controls, and returns selected identity values to the parent form flow without loading the full candidate table.

- [ ] **Step 5: Render enhanced relationship control shells**

To-one autocomplete renders a semantic combobox shell plus current-value fallback. To-many renders selected chips plus combobox shell. The existing relationship panel/list editor remains available for non-configured or inline/nested relationships.

- [ ] **Step 6: Structural/security review**

Confirm candidate endpoints still require parent access + exact relationship permission, do not mutate state, never submit labels as identity, and do not bypass searchable-field/query restrictions.

---

### Task 4: Shared advanced-widget JavaScript and CSS

**Files:**
- Create: `packages/rakit-web/src/rakit_web/assets/rakit-widgets.js`
- Modify: `packages/rakit-web/src/rakit_web/assets/rakit.css`
- Modify generated asset: `packages/rakit-web/src/rakit_web/static/rakit.css`
- Modify asset registration/build wiring only where the project currently fingerprints JS assets.

**Interfaces:**
- One shared progressive-enhancement initializer scans `data-rakit-widget` hooks.
- Autocomplete follows combobox/listbox semantics and keeps focus on the textbox.
- Remote request sequencing/abort logic prevents stale response overwrite.

- [ ] **Step 1: Implement SearchableSelect enhancement**

Local filtering only; preserve native select value and form submission.

- [ ] **Step 2: Implement Autocomplete and MultiAutocomplete enhancement**

Required behavior:

```text
ArrowUp/ArrowDown -> active option
Enter -> select active option
Escape -> close
clear -> remove nullable to-one selection
multi select -> chip + keep input focused
Backspace on empty multi input -> remove final chip
```

Use `aria-expanded`, `aria-controls`, `aria-activedescendant`, listbox/option roles, and restrained live regions.

- [ ] **Step 3: Implement race-safe remote search**

Debounce in the web runtime and ignore/abort obsolete requests. Query shorter than `min_query_length` does not send a request. Loading, zero-result, and error states are distinct.

- [ ] **Step 4: Implement presentation-only enhancements for date/numeric/boolean/file**

Keep native fallback values authoritative. Currency/percentage formatting must not alter submitted canonical numeric strings incorrectly. File/Image preview reads only the selected local file; it does not transform or upload outside the normal form submission.

- [ ] **Step 5: Add responsive/theme/reduced-motion styles**

Use existing semantic tokens. Popups are viewport-bounded, chips wrap safely, focus rings remain visible in light/dark, and reduced-motion suppresses nonessential transitions.

- [ ] **Step 6: Rebuild committed CSS through the existing Bun/Tailwind command**

Run the repository's canonical `bun run css:build` command from the expected package/root location and commit the generated CSS with the maintainer source.

- [ ] **Step 7: Structural review**

Confirm no inline per-template JavaScript was added and no advanced widget becomes a browser-only authorization or validation boundary.

---

### Task 5: Deterministic showcase and documentation

**Files:**
- Modify: `examples/ui_showcase/main.py`
- Modify: `docs/accessibility.md`
- Create or modify the nearest public UI/form documentation page if one already documents form presentation.

**Interfaces:**
- UI Showcase exposes deterministic examples for every first-wave presentation family.
- At least one to-one relationship uses `Autocomplete`; one to-many relationship uses `MultiAutocomplete`.

- [ ] **Step 1: Add showcase states**

Include representative small select/searchable-select, remote autocomplete, multi autocomplete, date/time, currency/percentage/number, switch/segmented, file upload, and image preview surfaces without creating a separate showcase-only stylesheet.

- [ ] **Step 2: Document public configuration**

Document typed `presentation=` examples, explicit-vs-inferred behavior, relationship candidate privacy/permission behavior, and no-JS fallbacks.

- [ ] **Step 3: Update accessibility guarantees**

Document only guarantees implemented and verified: combobox keyboard model, live state behavior, native fallbacks, focus visibility, and reduced-motion behavior.

- [ ] **Step 4: Structural review**

Ensure docs do not claim Playwright/axe/cross-browser automation or deferred wave features.

---

### Task 6: Tests-last regression suite and full verification

**Files:**
- Create: `packages/rakit-web/tests/test_field_presentation.py`
- Create: `packages/rakit-web/tests/test_advanced_widget_contracts.py`
- Create: `packages/rakit-web/tests/test_relationship_autocomplete.py`
- Modify existing form/relationship/showcase tests only where intentional markup/copy contracts changed.

**Interfaces:**
- Tests lock typed configuration validation, deterministic resolution, form transport invariants, candidate authorization/bounds, keyboard/ARIA hooks, no-JS fallback markup, and showcase coverage.

- [ ] **Step 1: Add presentation value/registry tests**

Cover invalid page sizes/min-query lengths, segmented-choice bounds, percentage scale requirements, duplicate registry registration, field/relationship mapping normalization, legacy widget fallback, and conservative inference.

- [ ] **Step 2: Add scalar rendering tests**

Verify native fallback element types/names, existing validation/error linkage, file retention behavior, canonical values, and no changes to CSRF/submission/concurrency controls.

- [ ] **Step 3: Add relationship autocomplete tests**

Verify authorization, canonical encoded identity transport, bounded candidate page size, query forwarding only through configured searchable fields, stale/selected state rendering, cardinality validation, and no-JS picker availability.

- [ ] **Step 4: Add JS/static semantic contract tests**

Lock required ARIA/data hooks and race-safe request implementation without brittle full-file snapshots.

- [ ] **Step 5: Add showcase acceptance contracts**

Verify deterministic UI Lab/resource examples expose the advanced widget families.

- [ ] **Step 6: Run focused verification**

Run the new presentation/widget/relationship tests and any directly affected form tests.

- [ ] **Step 7: Run formatting, lint, and type checks**

Run repository-standard `ruff format --check`, `ruff check`, and `ty check`.

- [ ] **Step 8: Run full repository tests and release gate**

Run the full pytest suite (including coverage/release gate), dependency matrix where CI provides it, MkDocs strict build, and artifact checks.

- [ ] **Step 9: Open child PR to `ui-07-responsive-a11y-hardening` and require fresh PR CI**

Do not merge to the epic until every required job is green. Do not touch `main`.

- [ ] **Step 10: Merge UI-07D into the epic and repeat combined browser acceptance**

After merge, maintainer browser acceptance covers the combined UI-07A/B/C/D tree before final UI-07 -> `main` PR is opened/merged.
