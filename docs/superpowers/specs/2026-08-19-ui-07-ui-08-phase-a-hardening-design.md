# UI-07 / UI-08 Phase A Hardening Design

## Status

Approved design for completing Rakit Phase A UI maturity after UI-06.

- Base branch at design start: `main`
- Base commit: `58b690266d37ea64eafd97f863baa01a0cc6e2fa`
- UI-07 epic branch: `ui-07-responsive-a11y-hardening`
- UI-07 final target: `main`
- UI-08 starts only after UI-07 is merged to `main`

This design supersedes the broad UI-07/UI-08 execution notes in the original UI maturity plan where they conflict with the workflow below. It preserves the visual language and behavior established by UI-01 through UI-06.

## Completion Update — 2026-08-19

- UI-07 merged to `main` at `0ce275b475c94da0152e94bfed343d1decabcf06` after maintainer combined browser acceptance and final PR CI #871.
- UI-08 final product/source audit found no P0, P1, or material-P2 product UI findings requiring another visual/runtime change.
- The accepted UI-07 browser result therefore remains the Phase A product baseline; UI-08 intentionally does not invent cosmetic churn.
- Planning artifacts were classified conservatively and retained because they still provide useful architectural/design history. The older unconditional deletion instruction remains superseded by this design.
- Phase A UI maturity is complete. The next default roadmap phase is Phase B alpha hardening.

## Goal

Finish Phase A by making every framework-owned Rakit Web surface release-quality across responsive layouts, keyboard/focus interaction, semantic accessibility, contrast, reduced motion, overflow, and UX copy, then perform one bounded final-polish pass.

Phase A completion means:

```text
UI-01  Showcase baseline                    complete
UI-02  Design tokens                        complete
UI-03  Shell / theme / icons                complete
UI-04  Core components                      complete
UI-05  Resource experience                  complete
UI-06  Advanced operations                  complete
UI-07  Responsive + accessibility hardening current
UI-08  Final polish                         next
```

After UI-08, work moves to Phase B alpha hardening rather than new UI capability work.

## Global Principles

1. Preserve SSR + HTMX progressive enhancement and no-JS critical-operation fallbacks.
2. Preserve authentication, authorization, CSRF, idempotency, concurrency, confirmation, transaction, and API/browser error semantics.
3. Existing framework behavior remains authoritative. UI-07 hardens presentation and interaction; it does not add business capabilities.
4. Keep visual changes inside `rakit-web` unless a concrete semantic requirement forces a small runtime change.
5. Keep `examples/ui_showcase` on default Rakit UI with no private stylesheet.
6. Keep the Tailwind workflow intact: edit maintainer CSS, rebuild, commit generated CSS.
7. Defer Playwright, axe-core, cross-browser automation, and visual-regression infrastructure to the later UI/accessibility v1 roadmap.
8. Use the maintainer development order for each slice: source implementation first, structural/non-test review second, regression tests last, then focused/full verification and CI.
9. Child slices merge only to the UI-07 epic branch. `main` remains unchanged until combined acceptance is complete.
10. No tag, GitHub Release, TestPyPI, or PyPI action is part of UI-07 or UI-08.

## Existing Accessibility Baseline

Rakit already documents and tests important framework-owned contracts including:

- skip link and main/navigation landmarks;
- representative one-page-heading structure;
- explicit form labels, descriptions, errors, and error-summary focus targets;
- semantic sortable table headers;
- contextual record-selection labels;
- polite live announcements and HTMX focus-management hooks;
- dialog opener focus restoration with native modal focus trapping;
- persisted light/dark/system theme preference;
- `prefers-reduced-motion` handling;
- representative duplicate DOM-ID checks.

UI-07 therefore validates and hardens existing guarantees rather than introducing accessibility from zero. `docs/accessibility.md` must describe only behavior actually verified after UI-07.

# UI-07 Architecture

UI-07 uses one epic integration branch with three serial child slices.

```text
main
  └── ui-07-responsive-a11y-hardening
        ├── ui-07a-responsive-overflow
        ├── ui-07b-keyboard-focus-semantics
        └── ui-07c-contrast-motion-copy
```

The slices are serial:

```text
07A -> epic
latest epic -> 07B -> epic
latest epic -> 07C -> epic
```

Every child branch starts from the current epic head when that slice begins. A stale sibling or pre-existing branch must never be used as the base for later work.

## UI-07A — Responsive and Overflow

Purpose: make every completed Rakit surface intentionally usable across desktop, tablet, and mobile widths without mixing in semantic accessibility redesign.

Primary scope:

- application shell, desktop sidebar, mobile navigation, page gutters;
- dashboard and widgets;
- resource list, table, filter rail, pagination, selection, action clusters;
- resource detail;
- create/update forms and delete confirmation;
- record actions and bulk actions;
- relationship editors and upload presentation;
- login, session/system surfaces, custom pages, UI Lab;
- long labels, identifiers, values, dense rows, and wide tables;
- contained horizontal scrolling only where semantically appropriate, especially data tables;
- comfortable touch-layout spacing where existing controls already support the operation.

Required viewport matrix:

- approximately 1440 CSS px;
- approximately 1024 CSS px;
- approximately 768 CSS px;
- approximately 390 CSS px.

Success criteria:

- no accidental page-level horizontal scrolling;
- no clipped critical controls;
- no overlapping action clusters;
- no unusable filter, form, relationship, dialog, or navigation layout;
- wide tables remain contained rather than forcing full-page width;
- responsive adaptations preserve operation semantics and no-JS fallback.

## UI-07B — Keyboard, Focus, and Semantics

Purpose: harden interaction accessibility and semantic contracts after responsive structure is stable.

Primary scope:

- skip-link behavior and landmarks;
- keyboard traversal through shell/navigation, search/filter, tables, actions, forms, relationships, auth, and custom pages;
- visible and logical focus order;
- dialog/popover opener and return-focus behavior;
- Escape/click-away behavior where the component contract supports it;
- accessible names for icon-only and contextual controls;
- form-error summary and field linkage;
- duplicate DOM-ID safety on representative pages;
- selection and select-all semantics;
- status meaning conveyed by text, not color/icon alone;
- critical no-JS operations remain usable.

Representative keyboard journey:

```text
load page
-> skip to main
-> navigation
-> search/filter
-> row selection/action
-> dialog/popover
-> submit/cancel
-> sensible focus return
```

Success criteria:

- framework-owned interactive controls remain reachable and understandable without a pointer;
- focus is always visible and does not disappear behind overlays or offscreen regions;
- modal/popover lifecycle restores focus consistently;
- semantic markup matches the actual interaction model;
- no-JS critical actions retain a complete path.

## UI-07C — Contrast, Motion, Copy, and Accessibility Documentation

Purpose: finish the perceptual and communication layer after layout and interaction semantics are stable.

Primary scope:

- light/dark contrast;
- muted, placeholder, metadata, status, and focus colors;
- `prefers-reduced-motion` behavior;
- HTMX loading/pending feedback that remains understandable without animation;
- destructive and consequential action wording;
- empty/error/session/system copy;
- `docs/accessibility.md` aligned with verified guarantees.

Contrast targets:

- normal text: at least 4.5:1;
- large text: at least 3:1;
- focus indicators visibly distinguishable in light and dark themes;
- status meaning never depends on color alone.

Reduced-motion target: nonessential transitions/animations are removed or substantially reduced without hiding state changes or loading meaning.

## Allowed Files and Boundaries

UI-07 may modify:

- framework-owned `rakit-web` templates;
- `packages/rakit-web/src/rakit_web/assets/rakit.css` and regenerated static CSS;
- lightweight progressive-enhancement JavaScript;
- accessibility/semantic regression tests;
- `examples/ui_showcase` only when a deterministic acceptance state is missing;
- `docs/accessibility.md`.

UI-07 must not:

- add business/product capabilities;
- change core/domain APIs for visual convenience;
- introduce Playwright/axe infrastructure;
- weaken or redesign auth/security semantics;
- add private showcase CSS;
- implement `examples/reference_app`;
- start adapter, CLI, generated API, or other Phase B/C work.

A runtime Python change is allowed only when a concrete presentation/semantic requirement cannot be fulfilled safely in templates/CSS/JS, and that change must have regression coverage.

# Acceptance Matrix

Every major framework-owned surface must be exercised:

```text
Shell / navigation
Dashboard
Resource list
Resource detail
Create / update form
Delete confirmation
Record actions
Bulk actions
Relationships
Uploads
Login / session / system errors
Custom pages
UI Lab
```

For responsive review, every surface is checked at the four target widths. Layouts may adapt, but they may not become unusable. Horizontal scrolling is acceptable only inside deliberately scrollable regions such as wide data tables; it must not leak to the full document.

For keyboard/focus review, test full journeys rather than isolated controls. Include skip link, navigation, theme chooser, search/filter, row selection, select-all, row/record actions, dialogs/popovers, relationship controls, form submission, cancellation, and focus return.

For contrast/motion/copy review, verify both light and dark themes, status meaning, pending/loading states, reduced-motion behavior, and explicit destructive consequences.

# Child PR Quality Gates

Each 07A/07B/07C slice follows this order:

1. source implementation;
2. structural/manual non-test review;
3. regression tests added or updated last;
4. focused verification;
5. CSS rebuild if source CSS changed;
6. Ruff format/check;
7. `ty check`;
8. full pytest;
9. supported dependency matrix;
10. coverage;
11. MkDocs strict;
12. artifact checks/dry run as provided by CI;
13. fresh GitHub PR CI on the exact child head;
14. merge only to the epic branch.

Focused tests are not sufficient evidence for merge when full CI has not passed.

# Combined UI-07 Acceptance

After 07C is merged into the epic:

```text
07A + 07B + 07C
        |
        v
fresh combined full CI
        |
        v
maintainer browser matrix
        |
        +-- findings -> dedicated ui-07-polish-* child PR(s) -> epic
        |
        +-- no findings
        v
final ui-07-responsive-a11y-hardening -> main PR
        |
        v
fresh final PR CI
        |
        v
explicit maintainer merge instruction
```

There is no mandatory browser sign-off per child slice. Technical review and full CI gate each child; the human browser acceptance is performed against the combined epic tree.

The final UI-07 PR must never be merged automatically after CI. Explicit maintainer approval remains required.

# UI-07 Definition of Done

UI-07 is complete only when:

- every major built-in surface has intentional desktop/tablet/mobile behavior;
- no blocker-level overflow, clipping, or control collision remains;
- critical framework UI is usable keyboard-only;
- focus visibility, order, and restoration are consistent;
- accessible names, landmarks, error linkage, and representative duplicate-ID checks are valid;
- dialog/popover interaction contracts are consistent;
- status meaning is not color-only;
- light/dark contrast meets the documented targets;
- reduced-motion is honored without hiding state changes;
- critical no-JS flows remain operable;
- accessibility documentation reflects verified guarantees rather than aspirations;
- full repository and final PR CI are green;
- combined browser acceptance is explicitly given by the maintainer.

# UI-08 — Final Polish Boundary

UI-08 begins only after UI-07 is merged to `main`.

Default branch:

```text
ui-08-final-polish
```

UI-08 is deliberately small. It is not a new feature phase and does not own missing architecture. If final audit exposes a large architectural problem, stop and classify that work explicitly rather than turning UI-08 into a catch-all.

UI-08 flow:

```text
main after UI-07
   |
   v
final product/design critique
   |
   v
classify P0 / P1 / material P2 / cosmetic
   |
   v
fix only meaningful findings
   |
   v
full light/dark/system x desktop/tablet/mobile matrix
   |
   v
full repository gate
   |
   v
planning-doc classification/cleanup
   |
   v
maintainer final browser acceptance
   |
   v
ui-08-final-polish -> main
```

Severity policy:

- P0: broken, unusable, security/accessibility blocker -> must fix;
- P1: major UX/accessibility inconsistency -> must fix;
- material P2: clearly harms product quality -> fix;
- cosmetic/minor preference -> defer unless trivial and low-risk.

UI-08 must not add new business capability, adapter work, lifecycle APIs, CLI/scaffolding, generated APIs, or the reference app.

# Planning-Document Cleanup

The old plan's unconditional deletion rule is replaced with conservative classification.

For each candidate planning document:

```text
temporary execution artifact, fully superseded -> delete
useful architectural/design history            -> keep
still referenced by architecture/docs          -> keep
```

Before deletion:

- inspect references;
- determine whether the document still explains a meaningful architectural decision;
- ensure docs build remains valid;
- perform cleanup in a separate commit so the change is auditable.

No document is deleted merely because its feature is complete.

# Phase A Definition of Done

After UI-08 is merged:

```text
PHASE A — UI MATURITY
UI-01 complete
UI-02 complete
UI-03 complete
UI-04 complete
UI-05 complete
UI-06 complete
UI-07 complete
UI-08 complete
```

The next default roadmap step is Phase B alpha hardening. Adapter expansion, friendly CRUD lifecycle APIs, CLI wizard work, generated APIs, and the postponed `examples/reference_app` remain outside Phase A unless the maintainer explicitly changes the roadmap.

# Non-Goals

- formal WCAG certification;
- Playwright/axe or visual-regression infrastructure in UI-07;
- cross-browser automation in Phase A;
- new Rakit data/backend capabilities;
- framework/ORM/validation adapter expansion;
- release publication or tagging;
- reference application implementation.
