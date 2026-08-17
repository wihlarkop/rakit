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

The design system uses semantic tokens rather than scattering concrete palette classes throughout templates. Tokens cover brand, background, surfaces, borders, text, semantic states, focus, typography, radius, shadow/elevation, and reusable motion values.

Rakit-owned color values use OKLCH. Contrast is calibrated independently for light and dark themes.

The brand direction is a restrained **indigo-violet family** so Rakit is more distinctive than the current generic blue treatment while remaining clearly separate from semantic green, amber, and red states. Neutral colors may be very lightly tinted toward the brand hue, but surfaces remain predominantly neutral.

Target color balance:

- roughly 85-90% neutral surfaces;
- roughly 8-12% brand interaction/highlight usage;
- semantic colors only when they convey status or meaning.

### 3.2 Framework primitives

Reusable framework concepts may retain or gain `.rakit-*` classes implemented with Tailwind composition where that provides a stable visual primitive. Expected families include buttons, icon buttons, fields, panels/surfaces, chips/status badges, alerts/feedback, dialogs/popovers, pagination/navigation, and loading/progress feedback.

`@apply` is allowed for these true framework primitives. It should not be used to create a custom CSS class for every local layout fragment.

### 3.3 Template utilities

One-off layout stays readable as Tailwind utilities in Jinja templates. Rakit avoids page-specific wrapper classes unless a pattern proves reusable across surfaces.

### 3.4 CSS constraints

- No UI-showcase-only stylesheet that makes the example look better than default Rakit.
- No CDN-hosted Tailwind, icon package, or runtime styling dependency.
- No dynamic construction of Tailwind class names that the compiler cannot statically detect.
- Avoid excessive arbitrary values when a reusable token is appropriate.
- Keep the generated static CSS asset committed according to the existing Rakit asset workflow.
- Preserve reduced-motion support.
- Avoid decorative glassmorphism, gradient text, oversized radii, heavy shadows, decorative grids, and nested-card visual noise.

## 4. Icon System

Icons are part of the product language but remain restrained.

Rakit uses a curated subset of **Lucide** outline icons. Required icon SVG source/path data is checked into the repository and rendered server-side as inline SVG through a reusable Rakit icon primitive. Rakit does not load Lucide from a CDN and does not require a browser-side icon runtime. The upstream license notice must be preserved wherever required by the vendored source.

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

Icons are not added automatically to every title, field label, table cell, or button.

Text labels remain the default for actions whose meaning could be ambiguous. Icon-only buttons are reserved for conventional actions where compact presentation materially improves the interface.

### 4.2 Accessibility

- Decorative SVG icons are hidden from assistive technology.
- Icon-only controls require an accessible name.
- Tooltips may supplement icon-only controls but never replace the accessible name.
- Critical/destructive actions do not rely on color or icon shape alone.
- Icon size and stroke remain visually consistent across shell and components.

## 5. Theme Control

The current text `<select>` for `System / Light / Dark` is replaced by an icon-based theme control.

The interaction is fixed as follows:

- the shell shows one compact icon button representing the stored preference;
- **System** uses a monitor/device icon;
- **Light** uses a sun icon;
- **Dark** uses a moon icon;
- activating the button opens a small accessible popover/menu containing all three choices;
- each menu item shows both its icon and visible text label;
- the active preference is clearly indicated;
- selecting an option applies the theme and closes the popover.

The control must remain fully keyboard accessible, expose accessible names/state, preserve no-flash theme initialization, retain the user's preference using the existing mechanism, work without a large client-side framework, and keep all three System/Light/Dark modes.

## 6. Comprehensive Surface Scope

The maturity pass covers:

1. design system and semantic colors;
2. typography hierarchy;
3. spacing and page rhythm;
4. app shell;
5. desktop and mobile navigation;
6. dashboard home;
7. resource list/table;
8. resource detail;
9. create/edit forms;
10. search/filter/query UI;
11. record/page/resource actions;
12. bulk selection and bulk actions;
13. relationships;
14. authentication/session surfaces;
15. custom pages;
16. dialogs, popovers, and confirmations;
17. notifications and inline feedback;
18. empty, error, loading, pending, and progress states;
19. chips/badges/statuses;
20. buttons and icon buttons;
21. field/control families;
22. table ergonomics;
23. breadcrumbs/current-location hierarchy;
24. responsive behavior;
25. dark-theme quality;
26. accessibility;
27. purposeful motion and micro-interactions;
28. UX copy clarity;
29. visual consistency across feature areas;
30. reusable component architecture;
31. final edge-case polish.

## 7. `examples/ui_showcase`

Create one dedicated official example at:

```text
examples/ui_showcase/
```

It is a hybrid of a realistic operations application and a deterministic UI state gallery. It must use Rakit's real default UI and must not ship a private visual layer that hides weaknesses in the framework UI.

### 7.1 Realistic application model

The example represents a fictional commerce/operations admin with resources such as Customers, Products, Orders, Categories, Inventory, and Teams.

The data is realistic enough to produce long labels, statuses, relationships, missing values, multiple states, and useful table/form scenarios.

### 7.2 Dashboard scenarios

The dashboard exercises operational summary, recent orders/activity, low-inventory attention state, resource shortcuts, quick actions, partial/empty states, and responsive hierarchy without defaulting to a wall of identical metric cards.

### 7.3 Resource-list scenarios

The showcase exercises sorting, search, filters, status badges, row actions, pagination, bulk selection, long values, no-results state, empty-resource state, responsive overflow strategy, and loading/pending feedback.

### 7.4 Detail and relationship scenarios

Detail pages exercise grouped information, metadata, action hierarchy, related records, add/remove/connect relationship affordances, no-related-record state, high-cardinality relationships, and readonly relationships.

### 7.5 Form scenarios

The showcase includes representative text, textarea, select, number, checkbox, radio, date, optional/required, help-text, readonly, file-upload, validation-error, long-form, pending-submit, and successful-submit states.

### 7.6 Action scenarios

Representative actions include Approve, Cancel, Archive, Refund, Publish, Duplicate, Refresh, and Export. The example covers normal, destructive, confirmation, preview, rejected, validation, and success/result flows already supported by Rakit.

### 7.7 Bulk-action scenarios

Exercise selected-row count, bulk toolbar, safe/destructive actions, confirmation, result feedback, and partial/best-effort messaging where applicable to existing runtime behavior.

### 7.8 Authentication scenarios

The showcase makes login, invalid credentials, logout, session-expired presentation, and forbidden/access-denied states practical to inspect.

## 8. `/ui-lab` Visual QA Surface

The UI showcase includes a dedicated visual QA page at `/ui-lab`.

Its purpose is deterministic design inspection, not a second CSS system.

The page exposes representative states for typography, buttons, icon buttons, icons, inputs, selects, textarea, checkbox/radio, badges/status, alerts, toasts/feedback, panels/surfaces, dialogs/popovers, tables, pagination, breadcrumbs, navigation, empty states, loading states, error states, and theme modes.

Where meaningful, components demonstrate default, selected, disabled, error, success, warning, and loading states. Hover/focus behavior remains interactive rather than duplicated as fake static variants unless deterministic inspection requires a dedicated example.

The UI Lab becomes the primary visual regression playground for each UI PR.

## 9. Responsive Strategy

Responsive support is a UX design concern, not a final CSS shrinking pass.

Required targets are desktop workstation, laptop/smaller desktop, tablet, and mobile.

Navigation transforms appropriately; forms preserve readable labels/controls; action groups restructure with clear priority; tables use intentional overflow/column-priority behavior; dialogs remain usable on short/narrow viewports; icon-only controls retain adequate touch targets; and no important action disappears at small widths.

## 10. Accessibility Requirements

At minimum:

- normal text contrast >= 4.5:1;
- large text contrast >= 3:1;
- visible keyboard focus and useful focus order;
- semantic labels/descriptions;
- field errors associated with controls;
- status changes announced where Rakit already has announcer infrastructure;
- keyboard-operable menus, popovers, dialogs, and navigation;
- practical touch targets for compact controls;
- reduced-motion behavior;
- no state communicated only by color;
- icon-only controls have accessible names.

Existing accessibility behavior must be preserved or improved, never regressed for visual polish.

## 11. Motion and Interaction

Motion is subtle and functional: short hover/press transitions, dialog/popover transitions where appropriate, clear HTMX pending feedback, and useful feedback entrance/dismissal. No bounce/elastic decorative motion or content gated behind animation initialization. `prefers-reduced-motion` remains respected.

## 12. PR Breakdown

Implementation is intentionally split into reviewable PRs.

### UI-01 — UI Showcase and visual baseline

- create `examples/ui_showcase`;
- create `/ui-lab`;
- cover existing UI states without redesigning the framework yet;
- add focused tests needed to keep the example runnable/deterministic;
- document how maintainers run the showcase.

Purpose: establish a stable visual inspection surface before design-system changes.

### UI-02 — Tailwind design tokens and color foundation

- semantic Tailwind tokens;
- indigo-violet Rakit brand scale;
- neutral surface system;
- semantic status colors;
- typography hierarchy;
- radius/shadow normalization;
- light/dark calibration;
- focus styling;
- preserve generated asset workflow.

### UI-03 — App shell, navigation, theme switcher, icons

- desktop/mobile shell;
- sidebar/navigation hierarchy;
- page-location treatment;
- user/account area where supported;
- icon-button + three-option theme popover;
- reusable server-rendered Lucide icon primitive;
- curated navigation/action icons.

### UI-04 — Core components

- buttons/icon buttons;
- inputs/selects/textarea;
- checkbox/radio presentation;
- chips/status badges;
- alerts/feedback;
- dialogs/popovers;
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

- viewport, keyboard, focus, and contrast audit;
- reduced motion;
- long text/overflow;
- loading/error/empty edge cases;
- UX copy refinement.

### UI-08 — Final Impeccable polish

Run a final structured quality pass across the showcase and framework surfaces using critique/audit/layout/typeset/colorize/adapt/harden/polish workflows as appropriate. Resolve remaining inconsistencies before declaring the maturity program complete.

## 13. Testing and Verification

Each PR keeps the existing repository gate green and adds focused regression tests where behavior or rendered semantics change.

Verification includes the existing Python/type/lint/format gates, strict docs build when docs change, generated asset consistency, UI-showcase smoke coverage, stable semantic/accessibility assertions, manual `/ui-lab` and realistic-workflow inspection in light/dark/system modes, and desktop/tablet/mobile viewport inspection.

## 14. Non-Goals

This program does not introduce a SPA framework, replace SSR + HTMX progressive enhancement, redesign core/domain APIs solely for visual convenience, make `ui_showcase` a separate product theme, introduce decorative animation/icon saturation, require external asset CDNs, or publish a release automatically when UI-08 completes.

## 15. Acceptance Criteria

The UI/UX Maturity program is complete when:

1. all major `rakit-web` surfaces use one coherent visual system;
2. the default interface is comfortable, simple, and clean in both light and dark modes;
3. System/Light/Dark selection uses the specified icon-button + accessible three-option popover and persists preference;
4. icons improve scanning without overwhelming the interface;
5. direct concrete color usage is reduced in favor of semantic Tailwind tokens where appropriate;
6. resource lists, detail pages, forms, actions, bulk actions, relationships, auth, and custom pages share consistent interaction hierarchy;
7. responsive behavior is intentionally designed across desktop, tablet, and mobile;
8. accessibility requirements are met or improved relative to the current baseline;
9. `examples/ui_showcase` exposes realistic end-to-end workflows and `/ui-lab` exposes deterministic visual states;
10. the showcase has no private styling layer that hides framework UI deficiencies;
11. all repository verification gates remain green;
12. final Impeccable critique/audit/polish findings have no unresolved release-blocking UI issues.
