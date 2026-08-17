# Built-in UI accessibility

Rakit's built-in admin UI follows accessibility-oriented defaults for semantic structure, keyboard operation, focus visibility and restoration, form error linkage, status announcements, reduced motion, and light/dark/system themes.

The built-in theme implementation is CSP-safe: theme behavior is shipped as a local content-addressed JavaScript asset, styling is compiled into Rakit's single bundled Tailwind stylesheet, and no inline script or `unsafe-inline` CSP relaxation is required.

## Built-in contracts

The repository tests cover important framework-owned contracts including:

- a skip link and main/navigation landmarks;
- one page-level heading on representative built-in screens;
- explicit form labels, descriptions, errors, and error-summary focus targets;
- semantic sortable table headers with keyboard-native GET controls that preserve active query state while resetting pagination;
- contextual selection labels for record checkboxes;
- polite live announcements and HTMX focus management hooks;
- dialog opener focus restoration while relying on the native modal dialog for trapping focus;
- persisted `light`, `dark`, and `system` preferences;
- `prefers-reduced-motion` handling;
- duplicate DOM-ID checks on representative screens.

These checks are quality gates for Rakit-owned UI, not a formal WCAG certification. Application-owned custom templates and widgets remain the application's responsibility. Browser-level Playwright/axe automation remains a future roadmap item.
