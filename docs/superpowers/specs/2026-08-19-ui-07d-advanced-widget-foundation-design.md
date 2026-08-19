# UI-07D Advanced Widget Foundation — Design

## Status

Approved design for the fourth UI-07 slice on top of `ui-07-responsive-a11y-hardening`.

UI-07D is a presentation subsystem. It improves form and relationship interaction without changing business types, authorization, storage policy, mutation semantics, or adapter ownership.

## Goals

1. Introduce a typed public `presentation=` API for fields and relationships.
2. Keep domain/data semantics in `rakit-core` and browser interaction/rendering in `rakit-web`.
3. Ship a curated first wave of advanced widgets with strong keyboard/accessibility and progressive-enhancement behavior.
4. Reuse existing query, relationship, storage, permission, CSRF, validation, and mutation pipelines rather than creating parallel engines.
5. Preserve the existing `widget: str` hint as compatibility input while making typed presentations the preferred API.
6. Keep no-JavaScript critical flows usable, including large relationship candidate sets.

## Non-goals

UI-07D does not add:

- rich-text or code-editor subsystems;
- generic repeater, key/value, or JSON editors;
- tag creation semantics;
- generic composite-field infrastructure;
- multi-file storage semantics;
- image crop/edit/transform pipelines;
- ORM-specific widget behavior;
- authorization or validation bypasses;
- Playwright/axe/cross-browser infrastructure;
- broad UI-08 polish work.

## Architectural boundary

The public API uses immutable typed presentation objects:

```python
customer = RelationshipField(
    target="customers",
    presentation=Autocomplete(
        search_fields=("name", "email"),
        display_fields=("name", "email"),
        placeholder="Search customer...",
    ),
)
```

Core owns semantics; web owns interaction:

```text
public Rakit DSL
Field / RelationshipField
        │
        ├── semantic definition ──> rakit-core
        │
        └── presentation object
                  │
                  └──> rakit-web PresentationRegistry
                            ├── semantic HTML
                            ├── progressive-enhancement hooks
                            └── shared JS/CSS behavior
```

Presentation objects may format, constrain interaction, and choose browser affordances. They must not change the canonical business type or become an alternate mutation/query/storage engine.

Examples:

```python
price = Field(
    Decimal,
    presentation=Currency(currency="IDR", locale="id-ID"),
)

published_at = Field(
    datetime,
    presentation=DateTimePicker(timezone="Asia/Jakarta"),
)

enabled = Field(
    bool,
    presentation=Switch(on_label="Enabled", off_label="Disabled"),
)
```

## Presentation contract

A presentation is an immutable value object with a stable internal key. Built-ins are typed classes rather than stringly-typed option dictionaries.

The first-wave family is:

### Choice and relationships

- `Select`
- `SearchableSelect`
- `Autocomplete`
- `MultiAutocomplete`

### Date and time

- `DatePicker`
- `TimePicker`
- `DateTimePicker`
- `DateRangePicker` (typed range value only in v1)

### Numeric

- `NumberInput`
- `Currency`
- `Percentage`

### Boolean and small choice

- `Checkbox`
- `Switch`
- `SegmentedControl`

### File

- `FileUpload`
- `ImageUpload`

All classes validate their own presentation configuration at construction time.

## Inference and compatibility

Default inference remains conservative:

```text
str       -> TextInput/basic text
bool      -> Checkbox
int       -> NumberInput
float     -> NumberInput
Decimal   -> NumberInput
date      -> DatePicker
datetime  -> DateTimePicker
enum      -> Select
file      -> FileInput/basic file
relation  -> existing safe relationship presentation
```

Rakit must not infer domain intent such as currency, percentage, switch semantics, or remote autocomplete solely from Python type or row counts.

Resolution order:

```text
explicit presentation
    -> typed presentation renderer
else legacy widget string
    -> compatibility mapping
else
    -> safe type-based default
```

`FieldDefinition.widget` remains accepted in UI-07D. It is not the preferred advanced customization API.

## PresentationRegistry

`rakit-web` owns one centralized registry mapping presentation types to renderer contracts.

Conceptually:

```python
registry.register(Autocomplete, renderer=autocomplete_renderer)
```

A renderer may consume:

- field/relationship metadata;
- canonical current value;
- validation issues;
- resolved candidate endpoint metadata;
- presentation configuration.

A renderer may produce:

- semantic HTML;
- deterministic `data-rakit-*` enhancement hooks;
- declarations of shared assets required by the page.

A renderer must not:

- access the database directly;
- authorize requests;
- bypass `FormSchema` parsing;
- mutate relationships or files itself;
- return unescaped arbitrary user HTML.

The registry supports minimal custom server-rendered presentation registration in v1. Full plugin packaging is deferred.

## Choice and relationship behavior

### Select

Use for small bounded options. Native `<select>` remains the implementation and fallback.

### SearchableSelect

Use for small-to-medium option sets that are safe to render in full. Search is local in the browser; no remote request is required.

### Autocomplete

Use for one canonical identity from a potentially large candidate set.

```python
Autocomplete(
    search_fields=("name", "email"),
    display_fields=("name", "email"),
    placeholder="Search customer...",
    min_query_length=2,
    page_size=20,
)
```

The browser submits canonical encoded identity, never display labels as the source of truth.

Candidate responses use a small adapter-neutral contract:

```text
items:
  - identity
  - label
  - optional description
next_cursor
has_more
```

Remote candidate lookup reuses resource visibility, permissions, searchable-field policy, query limits, sorting, and pagination. It does not introduce a bypass endpoint.

`page_size` is bounded by the server. Cursor pagination is preferred for interactive candidate continuation.

### MultiAutocomplete

Uses the same candidate contract while retaining multiple canonical identities. Selected records render as removable chips/tokens. Selected identities are excluded or marked unavailable in subsequent candidate results.

### Interaction contract

Single autocomplete:

```text
focus -> type -> pending -> results -> ArrowUp/ArrowDown -> Enter -> select
Escape -> close
clear -> remove current selection when nullable
```

Multi autocomplete additionally supports:

- keeping the input focused after selection;
- chip remove buttons with accessible names;
- Backspace on an empty input removing the final chip;
- selected-item deduplication.

Remote requests are debounced by the web runtime and are race-safe; an older response must never replace newer query results.

### ARIA contract

Autocomplete implementations use the standard combobox/listbox model:

- input `role="combobox"`;
- `aria-expanded`;
- `aria-controls`;
- `aria-activedescendant`;
- popup `role="listbox"`;
- options `role="option"` with selected state where applicable.

Focus remains on the textbox while active-option state moves through `aria-activedescendant`.

Pending, empty, and error states use restrained live-region announcements.

## No-JavaScript candidate fallback

Large candidate sets must not degrade to thousands of `<option>` nodes.

For remote autocomplete, the no-JS fallback is a server-rendered picker flow:

```text
current selection
+ Change/Add action
      -> searchable candidate page
      -> paginated/cursor-bounded candidates
      -> choose canonical identity/identities
      -> return to original form/relationship operation
```

The picker reuses the same permissions/query restrictions as the enhanced endpoint.

## Date and time presentations

### DatePicker

Canonical type: `date`.

Fallback: `<input type="date">`.

### TimePicker

Canonical type: `time` or an explicitly supported time value.

Fallback: `<input type="time">`.

### DateTimePicker

Canonical type remains `datetime`.

Presentation timezone may be explicit or derive from an application/admin default. Rakit must not silently reinterpret timezone-aware business values without a configured policy.

Fallback: `<input type="datetime-local">` plus server-authoritative normalization.

### DateRangePicker

V1 supports a typed canonical range value only. Generic composition of two unrelated fields (`start_date` + `end_date`) is deferred.

The enhanced UI may render a range picker; the no-JS fallback renders two semantic range inputs belonging to the one typed field contract.

## Numeric presentations

### NumberInput

Canonical type remains `int`, `float`, or `Decimal`.

Supports presentation constraints such as step, min/max, prefix/suffix, and optional grouping.

### Currency

Currency is presentation, not a new business datatype.

```python
Currency(currency="IDR", locale="id-ID")
```

Display may be localized while submitted/normalized value remains canonical numeric data. Documentation should recommend `Decimal` for monetary values.

### Percentage

Scale semantics must be explicit. Rakit must not guess whether `15` or `0.15` represents fifteen percent.

## Boolean and small-choice presentations

### Checkbox

Default boolean presentation and semantic fallback.

### Switch

Boolean presentation for mutable enabled/disabled-style state. Underlying form semantics remain checkbox-like.

### SegmentedControl

For a small mutually-exclusive choice set, typically 2–4 choices. No-JS fallback is a radio group.

Large choice sets should use select/autocomplete families instead.

## File and image presentations

Existing `FileField` remains authoritative for storage id, path prefix, size, extension/MIME restrictions, filename policy, and delete behavior.

### FileUpload

Enhances one canonical file value with:

- native picker;
- drag/drop;
- selected filename and size/type summary;
- replace/clear pending selection;
- existing-file presentation during edit;
- progress when the transport can expose it.

Fallback remains `<input type="file">`.

Existing-file retention semantics remain unchanged.

### ImageUpload

Adds safe image thumbnail preview and optional browser-readable dimensions on top of `FileUpload`.

UI-07D does not add crop, rotate, filters, compression policy, client-side image transformation, or multi-file semantics.

## Custom presentation boundary

Developers may define immutable custom presentation objects and register a web renderer through the admin/web presentation registry.

Conceptually:

```python
@dataclass(frozen=True)
class RatingStars(Presentation):
    max_stars: int = 5

admin.presentations.register(RatingStars, renderer=rating_renderer)
```

The standard pipelines still own validation, authorization, CSRF, candidate visibility, storage restrictions, and mutation execution.

## Asset policy

Advanced widget behavior is centralized in shared Rakit CSS/JS modules. UI-07D must not scatter inline scripts through templates.

The page/runtime may track required presentation families so future asset splitting remains possible. UI-07D does not require micro-bundling every widget separately.

## Error states

Autocomplete distinguishes:

- query below minimum length;
- zero results;
- candidate request failure;
- selected identity no longer available.

Server submission remains authoritative if a stale or unauthorized identity is submitted.

Presentation-side validation may improve feedback but never replaces server validation.

## Security and policy invariants

UI-07D must preserve all existing UI-06/UI-07 guarantees:

- permission/capability fail-closed behavior;
- CSRF and submission-token handling;
- relationship authorization;
- candidate visibility restrictions;
- storage/file policy enforcement;
- canonical identity transport;
- progressive enhancement for critical operations;
- no browser-only authorization assumptions.

## Implementation discipline

The project workflow for this slice is:

```text
source/behavior implementation
-> structural/non-test review
-> regression tests
-> focused verification
-> full repo CI
```

Tests should prefer semantic/behavior contracts over brittle full-HTML snapshots.

## Acceptance criteria

UI-07D is complete when:

1. typed presentations can be attached through the public API without changing canonical field types;
2. built-in presentation resolution is deterministic and legacy widget strings still work;
3. registry rendering is centralized and custom renderer registration has a minimal safe contract;
4. SearchableSelect, Autocomplete, and MultiAutocomplete provide keyboard-accessible interaction;
5. remote candidates use canonical identity, permissions, query restrictions, bounded pagination, and race-safe browser behavior;
6. large relationship selections have a usable no-JS server-rendered picker fallback;
7. Date/Time, Numeric/Currency/Percentage, Checkbox/Switch/Segmented, FileUpload, and ImageUpload honor their canonical data/storage contracts;
8. shared widget assets are semantic, theme-compatible, responsive, and reduced-motion compatible;
9. the deterministic showcase exposes representative states for browser acceptance;
10. focused and full repository verification pass before merge into the UI-07 epic;
11. combined UI-07 browser acceptance is repeated after UI-07D integration before the epic is proposed to `main`.

## Deferred wave

The following remain explicitly deferred after UI-07D:

- `TagInput`;
- `Repeater`;
- `KeyValueEditor`;
- `JsonEditor`;
- rich-text editor;
- code editor;
- `MultiFileUpload`;
- image crop/edit;
- generic cross-field composite engine;
- advanced presentation plugin packaging.
