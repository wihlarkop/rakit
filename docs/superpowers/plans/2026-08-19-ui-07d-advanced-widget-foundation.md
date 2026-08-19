# UI-07D Advanced Widget Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a typed, extensible presentation system with advanced field and relationship widgets while preserving Rakit's existing core, authorization, validation, storage, and progressive-enhancement contracts.

**Architecture:** Direct `FieldDefinition` and `RelationshipDefinition` declarations carry an opaque `presentation` object through `rakit-core` without importing web types. Adapter-generated fields/relationships can be overridden through `ResourceWebPresentation`. `rakit-web` resolves sidecar override -> inline presentation -> legacy widget -> safe default, renders through one centralized presentation registry, and reuses the existing permission-aware relationship candidate/query routes.

**Tech Stack:** Python 3.12+, frozen dataclasses/Pydantic models, Starlette/Jinja2, vanilla JavaScript, existing HTMX/progressive-enhancement runtime, and the repository's existing Tailwind/Bun CSS build.

**Spec:** `docs/superpowers/specs/2026-08-19-ui-07d-advanced-widget-foundation-design.md`

## Global Constraints

- UI-07D is presentation-only; canonical business types and mutation/query/storage engines remain unchanged.
- `rakit-core` may store an opaque presentation object but must not import or branch on `rakit-web` presentation classes.
- Permission, CSRF, submission-token, relationship authorization, candidate visibility, storage policy, and server validation remain authoritative.
- Large relationship candidate sets must not degrade to unbounded native selects.
- Widget JavaScript must be centralized and progressive-enhancement-only.
- Existing `FieldDefinition.widget` behavior remains compatible.
- Wave 1 excludes TagInput, Repeater, KeyValueEditor, JsonEditor, rich text, code editor, MultiFileUpload, image editing, and generic cross-field composite infrastructure.
- Project workflow override: source/behavior first -> structural review -> regression tests last -> full CI.

---

### Task 1: Opaque inline presentation metadata + typed web presentation objects

**Files:**
- Modify: `packages/rakit-core/src/rakit_core/fields.py`
- Modify: `packages/rakit-core/src/rakit_core/relationships.py`
- Create: `packages/rakit-web/src/rakit_web/field_presentation.py`
- Modify: `packages/rakit-web/src/rakit_web/resource_presentation.py`
- Modify: `packages/rakit/src/rakit/__init__.py`

**Interfaces:**
- `FieldDefinition.presentation: object | None = None`.
- `RelationshipDefinition.presentation: object | None = None`.
- Immutable web classes: `Select`, `SearchableSelect`, `Autocomplete`, `MultiAutocomplete`, `DatePicker`, `TimePicker`, `DateTimePicker`, `DateRangePicker`, `NumberInput`, `Currency`, `Percentage`, `Checkbox`, `Switch`, `SegmentedControl`, `FileUpload`, `ImageUpload`.
- `ResourceWebPresentation.fields` and `.relationships` are immutable web-only override mappings.
- `PresentationRegistry` centralizes renderer registration/resolution.

- [ ] **Step 1: Add opaque metadata to core declarations**

Add optional `presentation` members only. Do not import `rakit_web`, validate browser-specific options, or reference presentation types from core parsing/compiler/mutation code.

- [ ] **Step 2: Implement immutable typed presentation values**

Create `field_presentation.py`. Validate configuration at construction time. Required examples:

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
        if not 1 <= self.page_size <= 200:
            raise ValueError("page_size must be between 1 and 200")
```

`Percentage` requires explicit scale semantics. `SegmentedControl` rejects fewer than two choices. Numeric min/max/step values are presentation constraints only.

- [ ] **Step 3: Implement registry contracts**

`PresentationRegistry.register(type, renderer, replace=False)` rejects duplicate registrations unless `replace=True`; `resolve()` is deterministic. Renderer output is a view-model mapping and renderer functions never access data sources.

- [ ] **Step 4: Extend `ResourceWebPresentation`**

Normalize `fields`/`relationships` through `MappingProxyType`, validate non-empty ids and typed presentation values, and preserve filters/actions unchanged.

- [ ] **Step 5: Export public presentation classes**

`from rakit import Autocomplete, Currency, DateTimePicker, MultiAutocomplete, ...` must work.

- [ ] **Step 6: Structural review**

Confirm `rakit-core` contains no `rakit_web` import and no core behavior branches on presentation classes.

---

### Task 2: Deterministic scalar presentation resolution + semantic fallback rendering

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/form_routes.py`
- Modify: `packages/rakit-web/src/rakit_web/templates/forms/form.html`
- Create: `packages/rakit-web/src/rakit_web/templates/forms/_field_control.html`
- Modify the existing write-binding construction site to pass resource web presentation where required.

**Interfaces:**
- `WriteResourceBinding` receives optional web presentation overrides without changing `FormSchema`.
- Resolution order: resource sidecar override -> `FieldDefinition.presentation` -> legacy `widget` -> conservative type inference.

- [ ] **Step 1: Implement field resolver**

Equivalent contract:

```python
def resolve_field_presentation(
    field: FieldDefinition,
    override: Presentation | None,
) -> Presentation:
    if override is not None:
        return override
    if isinstance(field.presentation, Presentation):
        return field.presentation
    if field.presentation is not None:
        raise TypeError("Unsupported field presentation")
    if field.widget != "text":
        return legacy_widget_presentation(field.widget)
    return inferred_presentation(field)
```

Inference: bool -> Checkbox; numeric -> NumberInput; date -> DatePicker; datetime -> DateTimePicker; enum -> Select; FileField -> basic/FileUpload-safe fallback; string -> basic text. Never infer currency/switch/autocomplete.

- [ ] **Step 2: Build presentation-aware control view models**

`_form_response()` carries presentation key/config, canonical value, issue/description ids, required state, and current file state. The normal `FormSchema.parse()` input names stay unchanged.

- [ ] **Step 3: Split field control rendering**

Move scalar/file control markup into `_field_control.html`. Required no-JS semantic fallbacks:

```text
Select/SearchableSelect -> select when choices exist, otherwise safe text/basic fallback
DatePicker -> input[type=date]
TimePicker -> input[type=time]
DateTimePicker -> input[type=datetime-local]
NumberInput/Currency/Percentage -> numeric-safe input
Checkbox/Switch -> checkbox
SegmentedControl -> radio group
FileUpload/ImageUpload -> input[type=file]
```

Preserve existing `aria-describedby`, error ids, required indicators, current-file retention, multipart behavior, and token markup.

- [ ] **Step 4: Validate configured field override ids**

Unknown sidecar field ids fail closed through the existing invalid-resource-web-presentation error path once final form fields are known.

- [ ] **Step 5: Structural review**

Confirm no form transport/security semantics changed.

---

### Task 3: Relationship presentation resolution + bounded candidate transport

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/relationship_routes.py`
- Modify relationship-binding construction in `packages/rakit-web/src/rakit_web/admin.py` or its current helper.
- Modify: `packages/rakit-web/src/rakit_web/templates/relationships/panel.html`
- Modify: `packages/rakit-web/src/rakit_web/templates/relationships/options.html`
- Create: `packages/rakit-web/src/rakit_web/templates/relationships/picker.html`

**Interfaces:**
- `RelationshipEditorBinding.presentation: Presentation | None`.
- Resolution order: sidecar relationship override -> `RelationshipDefinition.presentation` -> existing safe presentation.
- `Autocomplete` requires to-one cardinality; `MultiAutocomplete` requires to-many. Incompatible declarations fail closed before serving UI.

- [ ] **Step 1: Bind/validate relationship presentation**

Reject unsupported opaque inline objects and unknown sidecar relationship ids. Preserve current presentation for relationships with no advanced configuration.

- [ ] **Step 2: Preserve candidate page metadata**

Refactor `_candidate_options()` into a bounded internal candidate page carrying `items`, current continuation/page, and `has_next/has_more`. Continue calling `ResourceService.list(ResourceQuery...)` and preserve exact identity generation and record-label resolution.

- [ ] **Step 3: Apply presentation search/page policy**

For Autocomplete/MultiAutocomplete, use configured `search_fields` only when they are within the editor's already-authorized/searchable target fields. Bound `page_size` by 1..200. Never broaden datasource search capability.

- [ ] **Step 4: Upgrade `/options`**

Render canonical encoded identity, label, optional safe secondary description, selected state, and continuation metadata. Route remains read-only, exact-relationship-authorized, parent-existence checked, `Cache-Control: no-store`.

- [ ] **Step 5: Add server-rendered no-JS picker**

Create a normal search + bounded candidate page under the compiled relationship route. Selection submits canonical identity values into the existing relationship form namespace and returns to the normal form/panel path. Never render all candidates at once.

- [ ] **Step 6: Render advanced relationship shells**

To-one: current value + combobox shell + fallback picker action. To-many: selected chips + combobox shell + fallback picker action. Inline/nested/non-configured relationships continue using existing panel behavior.

- [ ] **Step 7: Structural/security review**

Confirm labels are never mutation identity, candidate lookup does not mutate, and authorization/search restrictions remain unchanged.

---

### Task 4: Shared widget JS/CSS behavior

**Files:**
- Create: `packages/rakit-web/src/rakit_web/assets/rakit-widgets.js`
- Modify: `packages/rakit-web/src/rakit_web/assets/rakit.css`
- Modify generated: `packages/rakit-web/src/rakit_web/static/rakit.css`
- Modify existing asset fingerprint/registration wiring only as required to load the shared widget module.

**Interfaces:**
- Shared initializer scans `data-rakit-widget`.
- Combobox/listbox keeps DOM focus on the textbox and uses `aria-activedescendant`.
- Remote lookup is debounced and stale-response safe.

- [ ] **Step 1: SearchableSelect local enhancement**

Filter the already-rendered bounded choices without changing native submitted value.

- [ ] **Step 2: Autocomplete/MultiAutocomplete interaction**

Implement ArrowUp/Down, Enter, Escape, nullable clear, multi chips, remove buttons, and Backspace-last-chip behavior. Selected identity is stored in normal hidden/relationship form controls.

- [ ] **Step 3: Race-safe remote lookup**

Use AbortController and/or monotonically increasing request sequence. Below-minimum queries do not request. Distinguish loading, zero-result, and request-error state.

- [ ] **Step 4: Date/numeric/boolean/file enhancements**

Enhance native fallback only. Currency/percentage display must preserve canonical submission. Image preview reads local selected file only and performs no transform/upload outside normal form submit.

- [ ] **Step 5: Theme/responsive/reduced-motion CSS**

Use semantic tokens; viewport-bound popups; wrapping chips; visible focus in light/dark; nonessential transitions disabled under reduced motion.

- [ ] **Step 6: Rebuild committed CSS**

Run the canonical Bun/Tailwind CSS build and commit generated output with maintainer CSS.

- [ ] **Step 7: Structural review**

No inline widget scripts and no browser-only validation/authorization assumptions.

---

### Task 5: Showcase + docs

**Files:**
- Modify: `examples/ui_showcase/main.py`
- Modify: `docs/accessibility.md`
- Modify nearest existing public form/UI documentation page if present.

- [ ] **Step 1: Add deterministic first-wave states**

Show representative SearchableSelect, to-one Autocomplete, to-many MultiAutocomplete, date/time, number/currency/percentage, checkbox/switch/segmented, FileUpload, and ImageUpload states using production styles only.

- [ ] **Step 2: Document configuration**

Document both direct inline usage:

```python
RelationshipDefinition(..., presentation=Autocomplete(...))
```

and adapter-generated override usage:

```python
ResourceWebPresentation(relationships={"customer": Autocomplete(...)})
```

Explain inference, canonical identity transport, query privacy, and no-JS picker behavior.

- [ ] **Step 3: Update verified accessibility guarantees**

Document combobox keyboard semantics, native fallbacks, live state, focus, theme, and reduced-motion guarantees only.

- [ ] **Step 4: Structural review**

No claims for deferred widgets or browser-automation infrastructure.

---

### Task 6: Tests-last regression suite + full verification

**Files:**
- Create: `packages/rakit-web/tests/test_field_presentation.py`
- Create: `packages/rakit-web/tests/test_advanced_widget_contracts.py`
- Create: `packages/rakit-web/tests/test_relationship_autocomplete.py`
- Modify existing core form/relationship/showcase tests only for intentional contracts.

- [ ] **Step 1: Presentation/core-boundary tests**

Cover inline opaque metadata preservation, no core web import, invalid configuration, registry duplicate behavior, sidecar mapping normalization, unsupported opaque presentation rejection in web, legacy widget mapping, and conservative inference.

- [ ] **Step 2: Scalar fallback/form transport tests**

Verify element types/names, canonical values, validation/error linkage, current-file retention, and unchanged CSRF/submission/concurrency fields.

- [ ] **Step 3: Relationship autocomplete tests**

Verify exact authorization, canonical encoded identities, cardinality failures, bounded candidate size, query policy, selected state, and no-JS picker availability.

- [ ] **Step 4: JS/static contract tests**

Lock ARIA/data hooks, AbortController/sequence race-safety mechanism, chip accessible names, and reduced-motion/static classes without full snapshots.

- [ ] **Step 5: Showcase acceptance tests**

Verify deterministic first-wave widget examples are present.

- [ ] **Step 6: Focused verification**

Run new tests plus directly affected form/relationship/UI showcase tests.

- [ ] **Step 7: Repository quality gates**

Run `ruff format --check`, `ruff check`, `ty check`, full pytest, coverage/release gate, MkDocs strict, artifact checks, and dependency suites as CI defines them.

- [ ] **Step 8: Child PR**

Open `ui-07d-advanced-widget-foundation -> ui-07-responsive-a11y-hardening`. Require fresh PR CI green. Do not touch `main`.

- [ ] **Step 9: Epic integration and browser gate**

Merge UI-07D only to the UI-07 epic after CI. Repeat combined UI-07A/B/C/D browser acceptance before opening/merging the final UI-07 -> `main` PR.
