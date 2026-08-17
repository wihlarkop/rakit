# Rakit UI/UX Maturity Design

Date: 2026-08-17
Status: Approved design direction; ready for maintainer review before implementation planning

## 1. Goal

The UI/UX Maturity program upgrades every user-facing Rakit web surface from a functional admin baseline into a cohesive, production-grade developer-tool experience that is simple, clean, comfortable for long sessions, accessible, responsive, and visually distinctive without becoming decorative or noisy.

The work covers the entire `rakit-web` experience rather than only the dashboard. Existing application behavior, progressive enhancement, SSR + HTMX flow, capability boundaries, and security semantics remain authoritative. UI work must not weaken fail-closed behavior or create JavaScript-only paths.

## 2. Visual Direction

Rakit adopts a **Modern Product UI** direction:

- simple and clean rather than ornamental;
- compact enough for power users but never cramped;
- calm enough to use for many hours;
- clear visual hierarchy over card-heavy layouts;
- restrained brand color rather than a saturated multicolor interface;
- deliberate icons to improve recognition and scanning;
- light, dark, and system theme support as first-class modes;
- strong accessibility and keyboard behavior by default.

The interface should feel like a mature developer/admin product, not a generic Tailwind starter and not a marketing SaaS dashboard.

## 3. Tailwind CSS Architecture

Tailwind CSS v4 remains the primary styling engine.

The styling architecture has three layers:

1. **Rakit design tokens** defined through Tailwind theme variables.
2. **Reusable Rakit framework primitives** for components that occur across many templates.
3. **Direct Tailwind utilities in templates** for local layout and one-off presentation.

### 3.1 Design-token layer

The design system will use semantic tokens rather than scattering concrete palette classes throughout templates. Tokens cover:

- brand scale;
- application background;
- surface and raised surface;
- subtle surface;
- borders and dividers;
- primary and muted text;
- success, warning, danger, and info roles;
- focus ring;
- typography;
- radius;
- shadow/elevation;
- motion durations/easing where reusable.

Color values should use OKLCH where Rakit owns the token. Contrast must be calibrated for both light and dark themes.

The brand direction is a restrained **indigo-violet family** so Rakit is more distinctive than the current generic blue treatment while remaining clearly separate from semantic green, amber, and red states. Neutral colors may be very lightly tinted toward the brand hue, but surfaces remain predominantly neutral.

Target color balance:

- roughly 85-90% neutral surfaces;
- roughly 8-12% brand interaction/highlight usage;
- semantic colors only when they convey status or meaning.

### 3.2 Framework primitives

Reusable framework concepts may retain or gain `.rakit-*` classes implemented with Tailwind composition where that provides a stable visual primitive. Expected families include:

- buttons and button variants;
- inputs/selects/textarea;
- checkbox/radio controls where necessary;
- panels/surfaces;
- chips/status badges;
- alerts/feedback;
- dialogs;
- pagination/navigation primitives;
- icon-button primitive;
- loading/progress feedback.

`@apply` is allowed for these true framework primitives. It should not be used to create a custom CSS class for every local layout fragment.

### 3.3 Template utilities

One-off layout should stay readable as Tailwind utilities in Jinja templates. Rakit should avoid creating classes such as `resource-header-wrapper` or deeply nested page-specific CSS abstractions unless a pattern proves reusable across surfaces.

### 3.4 CSS constraints

- No UI-showcase-only stylesheet that makes the example look better than default Rakit.
- No CDN-hosted Tailwind, icon package, or runtime styling dependency.
- No dynamic construction of Tailwind class names that the compiler cannot statically detect.
- Avoid excessive arbitrary values when a reusable token is appropriate.
- Keep the generated static CSS asset committed according to the existing Rakit asset workflow.
- Preserve reduced-motion support.
- Avoid decorative glassmorphism, gradient text, oversized radii, heavy shadows, decorative grids, and nested-card visual noise.

## 4. Icon System

Icons are part of the product language but must remain restrained.

Rakit will use a curated **Lucide-style outline icon system**, rendered as server-side inline SVG. The implementation must not require a CDN or a browser-side icon runtime.

### 4.1 Icon usage rules

Icons are encouraged for:

- primary navigation/resource recognition;
- common actions where the icon improves scanning;
- search/filter/sort controls;
- status and feedback where the symbol adds meaning;
- relationship affordances;
- pagination and disclosure controls;
- file/upload affordances;
- theme selection;
- empty/error states when a simple icon improves comprehension.

Icons should not be added automatically to every title, field label, table cell, or button.

Text labels remain the default for actions whose meaning could be ambiguous. Icon-only buttons are acceptable only for conventional actions with accessible labeling.

### 4.2 Accessibility

- Decorative SVG icons are hidden from assistive technology.
- Icon-only controls require an accessible name.
- Tooltips may supplement icon-only controls but never replace the accessible name.
- Critical/destructive actions must not rely on color or icon shape alone.
- Icon size/stroke should remain visually consistent across the shell and components.

## 5. Theme Control

The current text `<select>` for `System / Light / Dark` will be replaced by an icon-based theme control.

Required states:

- **System**: monitor/device icon;
- **Light**: sun icon;
- **Dark**: moon icon.

The control must:

- expose the active mode clearly;
- remain fully keyboard accessible;
- have accessible names and state semantics;
- preserve the current no-flash theme initialization behavior;
- work without requiring a large client-side framework;
- retain the user's selected preference using the existing theme preference mechanism;
- support light, dark, and system rather than reducing the control to a two-way light/dark toggle.

A compact segmented/popover interaction may be used, but the final implementation must remain understandable without relying on icon recognition alone for assistive technology.

## 6. Comprehensive Surface Scope

The maturity pass covers all of the following:

1. design system and semantic colors;
2. typography hierarchy;
3. spacing and page rhythm;
4. app shell;
5. desktop navigation;
6. mobile navigation;
7. dashboard home;
8. resource list/table;
9. resource detail;
10. create/edit forms;
11. search/filter/query UI;
12. record actions;
13. page/resource actions;
14. bulk selection and bulk actions;
15. relationships;
16. authentication/session surfaces;
17. custom pages;
18. dialogs and confirmations;
19. notifications and inline feedback;
20. empty states;
21. error states;
22. loading/pending/progress states;
23. chips/badges/statuses;
24. buttons and icon buttons;
25. field/control families;
26. table ergonomics;
27. breadcrumbs/current-location hierarchy;
28. responsive behavior;
29. dark theme quality;
30. accessibility;
31. purposeful motion and micro-interactions;
32. UX copy clarity;
33. visual consistency across feature areas;
34. reusable component architecture;
35. final edge-case polish.

## 7. `examples/ui_showcase`

Create one dedicated official example at:

```text
examples/ui_showcase/
```

It is a hybrid of a realistic operations application and a deterministic UI state gallery. It must use Rakit's real default UI and must not ship a private visual layer that hides weaknesses in the framework UI.

### 7.1 Realistic application model

The example represents a fictional commerce/operations admin with resources such as:

- Customers;
- Products;
- Orders;
- Categories;
- Inventory;
- Teams.

The data should be realistic enough to produce long labels, statuses, relationships, missing values, multiple states, and useful table/form scenarios.

### 7.2 Dashboard scenarios

The dashboard should exercise:

- operational summary without defaulting to a wall of identical metric cards;
- recent orders/activity;
- low-inventory attention state;
- resource shortcuts;
- quick actions;
- partial and empty states;
- responsive hierarchy.

### 7.3 Resource-list scenarios

The showcase should expose:

- sorting;
- search;
- filters;
- status badges;
- row actions;
- pagination;
- bulk selection;
- long values;
- no-results state;
- empty-resource state;
- responsive overflow strategy;
- loading/pending feedback.

### 7.4 Detail and relationship scenarios

Detail pages should exercise:

- grouped information;
- metadata;
- primary/secondary/destructive action hierarchy;
- related records;
- add/remove/connect relationship affordances;
- no-related-record state;
- high-cardinality relationship state;
- readonly relationships.

### 7.5 Form scenarios

The showcase must include representative forms for:

- text;
- textarea;
- select;
- number;
- checkbox;
- radio;
- dates;
- optional/required values;
- help text;
- readonly values;
- file upload;
- multiple validation errors;
- long forms with sections;
- pending submit state;
- successful submit feedback.

### 7.6 Action scenarios

Representative actions include:

- Approve;
- Cancel;
- Archive;
- Refund;
- Publish;
- Duplicate;
- Refresh;
- Export.

The example should cover normal, destructive, confirmation, preview, rejected, validation, and success/result flows already supported by Rakit.

### 7.7 Bulk-action scenarios

Exercise:

- selected-row count;
- bulk toolbar;
- safe and destructive actions;
- confirmation;
- result feedback;
- partial/best-effort style messaging where applicable to existing runtime behavior.

### 7.8 Authentication scenarios

The showcase should make it practical to inspect:

- login;
- invalid credentials;
- logout;
- session-expired presentation;
- forbidden/access-denied state.

## 8. `/ui-lab` Visual QA Surface

The UI showcase includes a dedicated visual QA page at `/ui-lab`.

Its purpose is deterministic design inspection, not a second CSS system.

The page should expose representative states for:

- typography;
- buttons;
- icon buttons;
- icons;
- inputs;
- selects;
- textarea;
- checkbox/radio;
- badges/status;
- alerts;
- toasts/feedback;
- panels/surfaces;
- dialogs;
- tables;
- pagination;
- breadcrumbs;
- navigation states;
- empty states;
- loading states;
- error states;
- theme modes.

Where meaningful, components should demonstrate default, selected, disabled, error, success, warning, and loading states. Hover/focus behavior should remain interactive rather than duplicated as fake static variants unless deterministic inspection requires a dedicated example.

The UI Lab becomes the primary visual regression playground for each UI PR.

## 9. Responsive Strategy

Responsive support is a UX design concern, not a final CSS shrinking pass.

Required targets:

- desktop workstation;
- laptop/smaller desktop;
- tablet;
- mobile.

Specific expectations:

- navigation transforms appropriately rather than merely becoming narrower;
- forms preserve readable labels and controls;
- action groups wrap/restructure with clear priority;
- tables use intentional overflow/column-priority behavior;
- dialogs remain usable on short/narrow viewports;
- icon-only controls maintain adequate touch targets;
- no important action is lost at small widths.

## 10. Accessibility Requirements

At minimum:

- normal text contrast >= 4.5:1;
- large text contrast >= 3:1;
- visible keyboard focus;
- useful focus order;
- semantic labels and descriptions;
- field errors associated with controls;
- status changes announced where Rakit already has announcer infrastructure;
- keyboard-operable menus/dialogs/navigation;
- minimum practical touch targets for compact controls;
- reduced-motion behavior;
- no state communicated only by color;
- icon-only controls have accessible names.

Existing accessibility behavior must be preserved or improved, never regressed for visual polish.

## 11. Motion and Interaction

Motion should be subtle and functional:

- short hover/press transitions;
- dialog/popover transitions where appropriate;
- clear HTMX pending feedback;
- toast/feedback entrance and dismissal where useful;
- no bounce/elastic decorative motion;
- no content hidden behind animation initialization;
- `prefers-reduced-motion` remains respected.

## 12. PR Breakdown

Implementation is intentionally split into reviewable PRs.

### UI-01 — UI Showcase and visual baseline

- create `examples/ui_showcase`;
- create `/ui-lab`;
- cover existing UI states without redesigning the framework yet;
- add focused tests needed to ensure the example remains runnable and deterministic;
- document how maintainers run the showcase.

Purpose: establish a stable visual inspection surface before design-system changes.

### UI-02 — Tailwind design tokens and color foundation

- semantic Tailwind tokens;
- indigo-violet Rakit brand scale;
- neutral surface system;
- semantic status colors;
- typography hierarchy;
- radius/shadow normalization;
- light/dark theme calibration;
- focus styling;
- preserve generated asset workflow.

### UI-03 — App shell, navigation, theme switcher, icons

- desktop shell;
- mobile shell;
- sidebar/navigation hierarchy;
- page-location treatment;
- user/account area where supported;
- icon-based System/Light/Dark theme selector;
- reusable server-rendered icon primitive;
- curated navigation/action icons.

### UI-04 — Core components

- buttons;
- icon buttons;
- inputs/selects/textarea;
- checkbox/radio presentation;
- chips/status badges;
- alerts/feedback;
- dialogs;
- pagination;
- loading primitives.

### UI-05 — Resource experience

- list/table;
- search/filter UI;
- detail view;
- create/edit forms;
- delete flows;
- pagination and empty/no-results states;
- responsive resource ergonomics.

### UI-06 — Advanced operations

- actions;
- bulk actions;
- relationships;
- upload surfaces;
- custom pages;
- operation result feedback.

### UI-07 — Responsive, accessibility, and UX hardening

- viewport audit;
- keyboard audit;
- focus audit;
- contrast audit;
- reduced motion;
- long text/overflow;
- loading/error/empty edge cases;
- UX copy refinement.

### UI-08 — Final Impeccable polish

Run a final structured quality pass across the showcase and framework surfaces using critique/audit/layout/typeset/colorize/adapt/harden/polish workflows as appropriate. Resolve remaining inconsistencies before declaring the maturity program complete.

## 13. Testing and Verification

Each PR must keep the existing repository gate green. UI work adds focused regression tests where behavior or rendered semantics change.

Verification includes:

- existing Python test suite;
- existing type/lint/format gates;
- strict docs build when docs change;
- generated asset consistency;
- UI showcase smoke coverage;
- semantic/accessibility assertions where stable and valuable;
- manual visual inspection of `/ui-lab` and realistic workflows in light, dark, and system modes;
- desktop/tablet/mobile viewport inspection.

Visual changes should be evaluated against the UI showcase before being propagated to or judged through specialized examples.

## 14. Non-Goals

This program does not:

- introduce React/Vue/Svelte or another SPA framework;
- replace SSR + HTMX progressive enhancement;
- redesign core/domain APIs solely for visual convenience;
- make `ui_showcase` a separate product theme;
- introduce decorative animation or icon saturation;
- require external asset CDNs;
- publish a release automatically when UI-08 completes.

## 15. Acceptance Criteria

The UI/UX Maturity program is complete when:

1. all major `rakit-web` surfaces use one coherent visual system;
2. the default interface is comfortable, simple, and clean in both light and dark modes;
3. System/Light/Dark theme selection is icon-based, accessible, and persistent;
4. icons improve scanning without overwhelming the interface;
5. direct concrete color usage has been reduced in favor of semantic Tailwind tokens where appropriate;
6. resource lists, detail pages, forms, actions, bulk actions, relationships, auth, and custom pages share consistent interaction hierarchy;
7. responsive behavior is intentionally designed across desktop, tablet, and mobile;
8. accessibility requirements are met or improved relative to the current baseline;
9. `examples/ui_showcase` exposes realistic end-to-end UI workflows and `/ui-lab` exposes deterministic visual states;
10. the showcase has no private styling layer that hides framework UI deficiencies;
11. all repository verification gates remain green;
12. final Impeccable critique/audit/polish findings have no unresolved release-blocking UI issues.
