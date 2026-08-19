# Built-in UI accessibility

Rakit's built-in admin UI follows accessibility-oriented defaults for responsive structure,
semantic HTML, keyboard operation, visible and restorable focus, form error linkage, status
announcements, reduced motion, light/dark/system themes, and progressive-enhanced form controls.

The built-in theme implementation is CSP-safe: theme and advanced-widget behavior is shipped as
local JavaScript, styling is compiled into Rakit's bundled Tailwind stylesheet, and no inline script
or `unsafe-inline` CSP relaxation is required.

## Built-in contracts

Repository quality gates cover important framework-owned contracts including:

- a skip link plus main and navigation landmarks;
- one page-level heading on representative built-in screens;
- responsive containment for shell navigation, dialogs, filter drawers, resource tables, action
  groups, long values, relationships, advanced choice controls, and custom-page content;
- explicit form labels, descriptions, errors, and error-summary focus targets;
- semantic sortable table headers with keyboard-native GET controls that preserve active query
  state while resetting pagination;
- contextual record-selection labels, a current-page select-all control, and polite selected-count
  announcements;
- keyboard-native action, filter, theme, dialog, and popover controls with meaningful accessible
  names;
- opener focus restoration for framework dialogs, mobile navigation, relationship previews, and
  dismissible popovers without forcing unrelated scroll movement;
- contextual accessible names for relationship unlink/delete and multi-autocomplete chip-removal
  controls;
- polite live announcements and HTMX focus-management hooks;
- persisted `light`, `dark`, and `system` preferences;
- semantic light/dark color roles calibrated for readable built-in text and focus states;
- `prefers-reduced-motion` handling that reduces nonessential animation and transitions while
  keeping loading/state feedback available;
- visible text accompanying semantic success, warning, danger, and information presentation;
- duplicate DOM-ID checks on representative screens;
- server-rendered critical operation paths that remain available without JavaScript.

## Advanced choice controls

`Autocomplete` and `MultiAutocomplete` use the ARIA combobox/listbox pattern. DOM focus stays on the
search textbox while `aria-activedescendant` identifies the active option. `ArrowUp` and `ArrowDown`
move the active option, `Enter` selects it, and `Escape` closes the result popup. Multi-select chips
have named remove buttons, and Backspace on an empty multi-autocomplete input removes the final
pending chip.

The combobox exposes `aria-expanded` and `aria-controls`; result options use `role="option"`. Loading,
empty-result, request-error, selection, and removal feedback is announced through a restrained polite
live region rather than moving focus into the popup.

`SearchableSelect` enhances a native select. Date, time, number, boolean, segmented, file, and image
presentations retain native semantic controls underneath their visual enhancement. If JavaScript is
unavailable, large relationship candidate sets use a separate server-rendered searchable and bounded
picker instead of an unbounded select.

## Contrast and motion targets

Rakit's built-in design tokens target at least 4.5:1 contrast for normal text and 3:1 for large
text on the framework-owned combinations where those roles are used. Semantic state color is not
the only carrier of meaning; framework feedback includes text and appropriate HTML roles.

When `prefers-reduced-motion: reduce` is active, Rakit reduces nonessential animation and transition
durations and disables smooth scrolling. State visibility, autocomplete results, and HTMX loading
feedback do not depend on animation continuing to run.

## Scope

These contracts are quality gates for Rakit-owned UI, not a formal WCAG certification. A host
application remains responsible for the accessibility of its custom templates, custom presentation
renderers, third-party content, and domain-specific copy.

Browser-level Playwright/axe automation, cross-browser accessibility automation, and visual
regression remain later roadmap items; UI-07 does not claim those tools are already part of the
release gate.
