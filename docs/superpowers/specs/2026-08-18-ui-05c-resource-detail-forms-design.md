# UI-05C Resource Detail, Forms & Delete Design

## Status

Approved design for the third UI-05 slice.

This document supersedes the resource-detail/create/edit/delete portion of the original single-PR `UI-05 — Dashboard and Resource Experience` scope.

Approved sequence:

1. UI-05A Dashboard Experience
2. UI-05B Resource List Experience
3. UI-05C Resource Detail, Forms & Delete

UI-05C starts only after UI-05B has merged.

## Goal

Mature the record-level CRUD workflow into a coherent product experience for:

- resource detail;
- built-in create/edit navigation and hierarchy;
- layout-driven forms;
- field help/required/read-only/disabled/error states;
- validation summaries;
- file-field presentation;
- save/cancel hierarchy and pending feedback;
- explicit delete confirmation and consequences;
- long and missing values;
- basic responsive usability.

The UI must remain driven by existing Rakit resource/form definitions and preserve authorization, CSRF, idempotency, concurrency, delete-token, validation, and progressive-enhancement behavior.

## Workflow Boundary

UI-05C owns built-in CRUD presentation only:

`resource list -> record detail -> create/edit -> delete confirmation`

Built-in CRUD includes Create, Edit, and Delete when those capabilities/routes are already exposed.

Domain actions such as Approve, Refund, Publish, Archive, custom confirmation workflows, and bulk domain operations remain UI-06.

## Security and Runtime Principle

Core/runtime validated state remains authoritative.

Presentation must not:

- expose fields outside existing detail/form policy;
- fabricate CRUD routes or capabilities;
- weaken permission checks;
- drop CSRF tokens;
- drop submission/idempotency tokens;
- drop concurrency tokens;
- drop delete tokens;
- trust raw path/query/form values as a safe record label;
- move server validation into client-only logic.

Any runtime change must be justified by missing safe presentation data, remain narrowly presentation-oriented, and preserve existing HTTP/security semantics.

## Resource Detail Hierarchy

Use a calm entity-focused detail page rather than card-per-field presentation.

Recommended hierarchy:

1. breadcrumb;
2. record title;
3. record context/identity;
4. built-in CRUD actions if available;
5. grouped record information using definition-list semantics.

Conceptual layout:

`Dashboard > Orders > ORD-1080`

`Order #1080                         [Edit] [Delete]`

`Order · ORD-1080`

Then a clear information region:

- Customer — Atlas Research
- Status — Paid
- Total — $1,240
- Reference — —

## Record Title Safety

Keep the UI-03 visible-field-only title heuristic.

Record titles/identities may be derived only from detail fields already visible to the current resource presentation. Hidden or policy-excluded fields must not be consulted merely to create a prettier heading.

Preferred visible-field order remains conceptually:

1. visible `name` / `title` / `label`;
2. visible `id` / identity-like value already exposed;
3. first safe visible detail value;
4. resource singular label fallback.

Do not introduce broad reflection over the domain object in templates.

## Detail Information Layout

The existing `<dl>` foundation is correct and should remain semantic.

Mature it with:

- clearer label/value hierarchy;
- consistent vertical rhythm;
- responsive stacking;
- wrapping for long values;
- restrained dividers;
- no nested card per field;
- semantic Rakit tokens rather than direct old palette utilities.

## Missing Values

Where a safe presentation value is absent, render `—` rather than `None`, `null`, or an ambiguous blank.

This is a view transformation only. It must not change stored values or data-source behavior.

## Built-In CRUD Actions

Built-in Create/Edit/Delete affordances should follow UI-04 hierarchy.

### Detail

Typical action group:

- Edit: primary or strong secondary depending on page context;
- Delete: visually separated danger action.

Do not saturate the header with every possible domain action. Advanced/domain actions remain UI-06.

### Create

A Create action belongs at resource/list level when capability exists and should lead to the existing create route.

### Edit

Edit belongs naturally on the record detail page and preserves the existing update route/concurrency behavior.

### Delete

Delete must lead to the explicit server-rendered delete-confirmation flow. UI-05C must not replace it with JavaScript-only confirmation.

## Form Architecture

The existing form layout definition remains authoritative.

UI-05C must not flatten all forms into a fixed layout or introduce a new Python component API.

Supported existing layout node concepts remain:

- field;
- section;
- row;
- column;
- tabs;
- collapsible;
- relationship placeholder/panel;
- custom block placeholder.

Relationships and custom blocks keep their existing behavior; their advanced presentation is UI-06.

## Form Page Hierarchy

Recommended structure:

1. breadcrumb/context;
2. one page `<h1>`;
3. short resource/record context where available;
4. validation summary if present;
5. definition-driven form layout;
6. save/cancel action footer.

Create and edit must be distinguishable from the heading/context without turning the operation into a large banner.

## Field Presentation

Reuse UI-04 primitives and semantics.

Expected control families include existing supported form field renderers and at minimum:

- text-like input;
- file input;
- select/other existing controls where the runtime already emits them;
- help text;
- required state;
- invalid/error state;
- read-only/disabled state when already represented by the form definition.

Do not infer a new field type from field names.

## Labels and Required State

Field labels remain explicitly associated with controls.

When a field is required, presentation should include a visible indicator plus an accessible equivalent. Do not rely on red color alone.

The actual `required`/validation contract remains owned by the form/runtime schema; presentation does not invent requirements.

## Help and Description Text

Use `.rakit-field-help` or equivalent shared semantic presentation.

If a field has both description/help text and validation issues, `aria-describedby` should continue to reference both safe IDs as appropriate.

Help text remains secondary to the field value/label and should wrap comfortably.

## Field Errors

Field-level issues remain adjacent to their controls and use the shared Rakit error treatment.

Requirements:

- `aria-invalid="true"` where applicable;
- associated error description ID;
- readable text, not color-only styling;
- server-provided validation message remains authoritative.

UI-05C does not create a separate client-side validation engine.

## Validation Summary

The existing server-rendered summary/focus concept is retained and visually matured through the semantic feedback system.

Recommended content:

`There are problems with this form`

Then a list of safe field labels/messages, linking to the field anchor when the runtime already provides a valid anchor.

Requirements:

- remains focusable when the runtime targets it after validation;
- retains `role="alert"` for submission failure requiring attention;
- links do not point to hidden/nonexistent controls;
- field-level messages remain present as well.

## Form Sections

### Section

A layout node explicitly defined as a section may use a semantic panel/section treatment. Avoid wrapping every field in an additional card.

### Rows and Columns

These remain layout helpers. Multi-column arrangements collapse on narrow screens.

### Tabs

Existing server-rendered tab content remains available in document flow/anchors according to current runtime behavior. UI-05C does not introduce an SPA tab controller.

Error counts/active state should remain understandable and keyboard accessible.

### Collapsible

Continue to use native `<details>`/`<summary>` where currently defined.

Do not hide validation errors inside a collapsed region without respecting existing `node.open`/error behavior.

## File Fields

File controls should use the UI-04 file-input primitive rather than generic text-input styling.

Preserve:

- `multipart/form-data` only when required;
- configured `accept` values;
- required semantics;
- help and issue associations;
- server upload/security limits and validation.

Advanced upload workflows/previews/progress remain UI-06 where applicable.

## Save and Cancel Hierarchy

The form action footer remains useful, especially on long forms, but should use a calm solid semantic surface rather than decorative glass treatment.

Desktop target:

- Cancel secondary;
- Create / Save changes primary;
- actions aligned to the end.

Narrow target:

- practical touch targets;
- no overlap with form content;
- stacking/order remains clear.

Cancel URL must continue to use safe existing route context; UI-05C should not invent redirect destinations.

## Pending Submission

Server-side submission, idempotency, and concurrency remain the enforcement mechanisms.

HTMX/browser enhancement may communicate pending state with:

- readable `Saving changes` / `Creating…` label;
- compact spinner;
- busy/disabled affordance to reduce accidental repeat activation.

The flow must still work without JavaScript.

No UI-only disabling behavior may be treated as a security or idempotency guarantee.

## Delete Confirmation

The current minimal delete page must become an explicit destructive decision page.

Recommended hierarchy:

1. breadcrumb/context;
2. `Delete <resource singular>?` heading;
3. explicit consequence text;
4. safe record identity/context if already available from validated route/runtime data;
5. Cancel secondary action;
6. clearly labeled danger submit action such as `Delete order`.

Suggested consequence copy:

`You are about to permanently delete this record. This action cannot be undone.`

If the underlying delete semantics are not actually permanent for a particular adapter, the copy must not lie. In that case use a generic consequence statement supported by the runtime contract. The implementation plan must inspect actual delete semantics/context before finalizing wording.

## Delete Safety Tokens

The delete form must preserve all current hidden security/integrity inputs, including where present:

- CSRF token;
- submission token;
- delete token;
- any existing concurrency/confirmation token required by the route.

Template redesign must not drop or rename these fields.

## Delete Cancel Path

Cancel must be visible and usable without JavaScript.

Prefer returning to the safe record/detail/list route already available from server context. If the current route does not supply a safe detail URL, implementation may add a narrow presentation context helper rather than parsing an untrusted referrer.

## Error Handling

Form/delete errors remain server-rendered and must use existing status/security behavior.

UI-05C may improve presentation of:

- validation failures;
- concurrency conflicts if they already reach the form presentation;
- delete rejection/error messages already exposed safely.

It must not reinterpret domain exceptions or expose internal exception details.

## Responsive Baseline

Full systematic responsive/a11y hardening remains UI-07, but UI-05C must be usable at narrow widths.

Minimum requirements:

- detail definition rows stack cleanly;
- long values wrap;
- multi-column form rows collapse;
- section/tabs/collapsible controls remain reachable;
- sticky action footer does not obscure fields;
- delete actions remain readable and comfortably tappable.

## Accessibility

Preserve/improve:

- one `<h1>` per page;
- logical breadcrumbs;
- semantic `<dl>` for record details;
- label/control association;
- required state conveyed beyond color;
- `aria-describedby` for help/errors;
- `aria-invalid` for invalid controls;
- focused validation summary;
- keyboard-operable tabs/details according to native/existing semantics;
- visible focus;
- explicit destructive action text;
- no icon-only destructive action without accessible name.

## Expected Files

Primary:

- `packages/rakit-web/src/rakit_web/templates/resources/detail.html`
- `packages/rakit-web/src/rakit_web/templates/forms/form.html`
- `packages/rakit-web/src/rakit_web/templates/forms/delete_confirm.html`
- `packages/rakit-web/src/rakit_web/templates/components/ui.html` if shared CRUD/form primitives need refinement
- `packages/rakit-web/src/rakit_web/assets/rakit.css`
- generated static CSS
- `examples/ui_showcase` for deterministic CRUD states

Focused runtime route/form context changes are allowed only when safe presentation data is missing.

## UI Showcase Acceptance

The deterministic showcase should exercise:

- normal record detail;
- record title with visible name + identity;
- record fallback title;
- long values;
- missing optional values;
- create form;
- edit form;
- multi-section/row/column layout where public APIs support it;
- help and required states;
- multiple validation errors and summary links;
- file field;
- long form with sticky footer;
- delete confirmation;
- light and dark themes.

If a scenario cannot be produced using public Rakit APIs, do not add showcase-only framework shortcuts merely for visual QA.

## Testing Strategy

Per the approved workflow, implement the complete UI-05C feature surface first, visually/manual-review it, then add/finalize focused tests.

Stable contracts to test include:

- detail breadcrumb/title/context semantics;
- visible-detail-field-only title behavior;
- missing-value presentation;
- built-in CRUD action visibility only when available;
- create/edit heading hierarchy;
- label/help/error associations;
- required semantics;
- file-input class/encoding preservation;
- validation summary focus/links;
- hidden CSRF/submission/concurrency fields preserved;
- delete CSRF/submission/delete token preservation;
- explicit delete consequence and Cancel path;
- no JavaScript-only critical CRUD behavior.

Existing form, write-pipeline, CSRF, idempotency, concurrency, delete, accessibility, and showcase suites remain authoritative regressions.

## Out of Scope

UI-05C does not redesign:

- dashboard;
- resource search/filter/table/pagination;
- domain actions;
- advanced bulk flows;
- relationship management presentation;
- rich upload workflow/progress;
- auth/session;
- custom pages;
- release/publication behavior.

## Definition of Done

UI-05C is complete when:

- detail/create/edit/delete feel like one coherent CRUD workflow;
- record title derivation remains fail-closed to visible fields;
- form layout remains definition-driven;
- validation/help/required/file states use the shared design system;
- delete confirmation clearly communicates supported consequences and preserves security tokens;
- SSR/no-JS critical flows remain functional;
- basic narrow layouts are usable;
- showcase visual acceptance is approved;
- focused and existing regressions are green;
- Ruff, ty, diff check, full pytest/coverage, strict MkDocs, and artifact checks are green;
- the PR is reviewed and merged before UI-06 begins.
