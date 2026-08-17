# UI-04 Core Components Design

**Date:** 2026-08-18

**Status:** Approved for specification; implementation begins only after maintainer review of this written spec.

## 1. Purpose

UI-04 matures the reusable presentation primitives used across `rakit-web` without redesigning dashboard, resource workflows, advanced operations, or authentication surfaces. The goal is a compact, accessible, theme-aware core component layer that later UI-05 and UI-06 work can reuse without introducing a Python component framework or a JavaScript-rendered UI layer.

UI-04 builds on the merged UI-03 semantic design tokens, Lucide icon primitive, app shell, theme popover, breadcrumb hierarchy, and desktop icon rail.

## 2. Architectural Decision

Use a **hybrid primitive model**:

1. Semantic `.rakit-*` CSS classes provide reusable visual/state behavior.
2. Thin Jinja macros provide stable semantic markup for components whose accessibility or interaction contract would otherwise drift across templates.
3. Direct Tailwind utilities remain the default for one-off layout and local composition.
4. `rakit-ui.js` provides only progressive enhancement for behavior that cannot be expressed with native HTML alone.
5. No new Python component API is introduced.
6. SSR + HTMX remain authoritative. Critical flows must continue working without JavaScript.

This avoids both extremes: CSS-only duplication of semantic markup and a macro-heavy mini component framework that would make Rakit templates rigid.

## 3. Scope

### 3.1 CSS primitives

UI-04 will mature or add the following stable classes:

- `.rakit-button`
- `.rakit-button-secondary`
- `.rakit-button-quiet`
- `.rakit-button-danger`
- `.rakit-icon-button`
- `.rakit-input`
- `.rakit-select`
- `.rakit-textarea`
- `.rakit-checkbox`
- `.rakit-radio`
- `.rakit-file-input`
- field help, required, read-only, disabled, and invalid treatments
- `.rakit-chip` for entity/filter-like concepts
- `.rakit-status` with semantic variants
- `.rakit-alert` with semantic variants
- `.rakit-dialog` plus reusable title/body/footer treatment
- `.rakit-popover`
- `.rakit-pagination`
- `.rakit-loading` and reusable pending/loading treatment

All primitives must use existing Rakit semantic design tokens instead of introducing ad-hoc product colors.

### 3.2 Thin Jinja macros

`templates/components/ui.html` will expose focused macros for semantic markup:

- `button(...)`
- `icon_button(...)`
- `status(...)`
- `alert(...)`
- `error(...)`
- `pagination(...)`
- `loading(...)`

The macros are intentionally thin. They do not own application data, routing, permission checks, or domain behavior.

UI-04 will **not** add generic `input()`, `select()`, `checkbox()`, or form-builder macros. Existing form runtime markup remains authoritative; CSS/state contracts are sufficient until UI-05 applies the primitives to CRUD workflows.

## 4. Button and Action Contracts

### 4.1 Hierarchy

- Primary is the strongest positive action on a surface.
- Secondary supports adjacent non-primary actions.
- Quiet is low-emphasis navigation or utility action.
- Danger is reserved for destructive behavior and must not be used as a general accent.

### 4.2 Icon buttons

Icon-only controls:

- use `.rakit-icon-button`;
- target approximately 40px minimum practical interaction size;
- require an accessible name through `aria-label` or equivalent visible labeling;
- render decorative SVGs with `aria-hidden="true"` through the existing icon helper;
- retain visible keyboard focus.

### 4.3 Disabled and loading actions

Disabled controls must be genuinely non-interactive while keeping their label readable. State must not be communicated by opacity or color alone.

Loading actions retain their readable action label and add a compact progress indicator. They must expose appropriate busy/pending semantics, such as `aria-busy="true"`, without becoming spinner-only controls.

## 5. Field and Control Contracts

UI-04 normalizes visual/state behavior for:

- text, number, date, and related text-like inputs;
- select;
- textarea;
- checkbox;
- radio;
- file input;
- help text;
- required state;
- read-only state;
- disabled state;
- invalid/error state.

Field errors remain associated with their controls through existing `aria-describedby`/ID relationships where available. UI-04 must not weaken current server-side validation or error rendering semantics.

UI-04 does not restructure form pages or change form submission/data flow. That presentation work belongs to UI-05.

## 6. Chip and Status Semantics

`rakit-chip` remains appropriate for entity references, filter-like concepts, and compact removable/relationship tokens.

Status is a separate primitive because status has different semantic meaning and visual hierarchy. `.rakit-status` supports:

- `neutral` — default, unknown, inactive, or non-emphasized state;
- `success` — active, published, completed, or healthy state;
- `warning` — pending, review, attention, or caution state;
- `danger` — failed, blocked, destructive, or severe state;
- `info` — informational or in-progress state.

Every status includes readable text. Color and iconography are supportive, never the only signal.

## 7. Alert and Feedback Contracts

`.rakit-alert` supports neutral, success, warning, danger, and info visual variants.

ARIA roles follow urgency instead of visual color:

- informational/non-urgent feedback should normally use `role="status"` or no live role if static;
- urgent failures requiring immediate attention may use `role="alert"`;
- success or warning is not automatically an alert solely because of its color category.

Optional icons are restrained and decorative unless the icon itself carries a necessary accessible label.

## 8. Dialog and Popover Contracts

### 8.1 Dialog

Native `<dialog>` remains the foundation.

Reusable dialog presentation must support:

- clear title;
- optional description;
- body content;
- action footer with visible cancel/secondary path where appropriate;
- accessible labeling/describing relationships;
- narrow and short viewport usability;
- focus return to the invoking control after close;
- existing destructive preview behavior and full-page fallback.

Escape may close ordinary/non-destructive dialogs. Destructive confirmation must never remove the explicit cancel path or rely on JavaScript-only completion.

### 8.2 Popover

Popover styling/behavior is for lightweight contextual choices only. Complex workflows belong in pages or dialogs.

Popover behavior should provide predictable focus, Escape close, and outside-click close where enhancement is used. UI-04 will not introduce a browser framework or JavaScript-rendered content for popovers.

## 9. Pagination Contract

UI-04 provides a reusable visual and semantic pagination primitive only. It supports:

- Previous and Next controls;
- explicit disabled states;
- numbered page controls;
- `aria-current="page"` on the current page;
- non-interactive ellipsis;
- page-size control styling.

Resource-specific pagination behavior remains UI-05. In particular, UI-04 does not implement or change:

- the existing default of 25 rows per page;
- built-in UI choices 25 / 50 / 100;
- query-string preservation;
- reset to page 1 when search/filter/sort/page-size changes;
- resource table pagination layout.

Those decisions remain locked for UI-05.

## 10. Loading and HTMX Pending Contract

Loading is functional feedback, not decoration.

- Keep the original label/context visible where possible.
- Use compact progress indication.
- Preserve existing `htmx-indicator` compatibility.
- Announce meaningful state changes through existing Rakit announcer infrastructure when appropriate.
- The full server-rendered path remains usable without JavaScript.

UI-04 may extend `rakit-ui.js` only when a progressive enhancement behavior is necessary and cannot be achieved cleanly with native HTML/HTMX semantics.

## 11. Motion

Motion is short and functional: hover/focus transitions, compact pending feedback, and restrained dialog/popover transitions if they do not delay interaction.

No bounce, elastic, decorative entrance choreography, or content gated behind animation initialization is allowed. Existing `prefers-reduced-motion` handling remains authoritative and may be extended when new component transitions require it.

## 12. Raw Attribute Safety

The current `button()` macro accepts a raw `attrs` string rendered with `|safe`. UI-04 will reduce reliance on this pattern.

Common semantic states should become explicit macro parameters, including where applicable:

- `disabled`;
- `aria_label`;
- `loading`;
- type/variant parameters;
- other stable attributes that are repeatedly needed by framework-owned templates.

A raw trusted-attribute escape hatch may remain only for internal framework template call sites that require HTMX/data attributes and are not populated from untrusted user input. UI-04 must not broaden the use of `|safe` for user-controlled values.

## 13. UI Lab Acceptance Surface

`examples/ui_showcase` and `/ui-lab` remain the visual acceptance environment and must use default Rakit styling only.

UI-04 expands `/ui-lab` to demonstrate deterministic examples of:

- primary, secondary, quiet, and danger buttons;
- disabled and loading buttons;
- icon-only controls;
- default/read-only/disabled/invalid text controls;
- textarea;
- select;
- checkbox and radio;
- file input;
- neutral/success/warning/danger/info statuses;
- semantic alert variants;
- dialog;
- lightweight popover;
- pagination current/disabled/ellipsis states;
- loading/pending examples.

The showcase must not add private CSS that hides deficiencies in framework defaults.

## 14. Testing Strategy

UI-04 follows TDD and adds focused primitive contract coverage in `packages/rakit-web/tests/test_ui_primitives.py`.

Tests assert stable semantics rather than full HTML snapshots. Coverage includes:

- button variant/class selection;
- icon-button accessible naming;
- disabled semantics;
- loading/busy semantics;
- field invalid/error association;
- status variant text/semantic class behavior;
- alert roles by urgency;
- dialog title/description semantics;
- pagination current and disabled semantics;
- loading semantics;
- progressive-enhancement behavior only where new JS is introduced.

Existing behavior suites remain authoritative, especially accessibility, action, bulk, assets, and showcase tests. No security, CSRF, permission, transaction, idempotency, or concurrency behavior may be loosened to satisfy visual tests.

## 15. Expected Files

Primary implementation files:

- `packages/rakit-web/src/rakit_web/assets/rakit.css`
- `packages/rakit-web/src/rakit_web/static/rakit.css` (generated with `bun run css:build`)
- `packages/rakit-web/src/rakit_web/templates/components/ui.html`
- `packages/rakit-web/src/rakit_web/static/rakit-ui.js` only if required for progressive enhancement
- `packages/rakit-web/tests/test_ui_primitives.py`
- `examples/ui_showcase/templates/ui_lab.html`
- `tests/test_ui_showcase.py` where showcase-level semantic coverage is useful

Other templates may adopt a primitive only when necessary to prove the primitive works against an existing framework-owned pattern. Broad resource/dashboard/action/auth redesign is not part of this PR.

## 16. Explicit Non-Goals

UI-04 does not redesign:

- dashboard layout/content;
- resource list/table/search/filter;
- CRUD form page layout;
- delete workflow presentation;
- resource pagination query behavior;
- bulk action workflows;
- action pages;
- relationship workflows;
- upload surfaces;
- authentication/session pages;
- custom pages as a category.

These remain assigned to UI-05 and UI-06 by the master UI/UX Maturity roadmap.

UI-04 also does not introduce a SPA framework, a client component runtime, a new Python UI component abstraction, or an external icon/style dependency.

## 17. Acceptance Criteria

UI-04 is complete when:

1. core component states use one coherent semantic Rakit design language in light and dark modes;
2. button hierarchy, icon-button accessibility, field states, status, alerts, dialog/popover, pagination, and loading primitives have stable reusable contracts;
3. status and feedback are not communicated by color alone;
4. icon-only controls have accessible names and practical targets;
5. loading retains readable context and correct busy semantics;
6. dialog/popover interaction remains keyboard-usable and compatible with SSR/HTMX progressive enhancement;
7. raw `attrs|safe` usage is reduced rather than expanded, with common semantic states modeled explicitly;
8. `/ui-lab` exposes deterministic representative states using only default Rakit UI;
9. focused primitive tests and existing authoritative behavior/accessibility suites pass;
10. generated Tailwind CSS is rebuilt from the maintainer source and committed;
11. no UI-05/UI-06 workflow redesign is pulled into UI-04;
12. the repository verification gate remains green before merge.
