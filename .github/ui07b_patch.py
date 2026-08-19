from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected exactly one match in {path}, got {count}: {old!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


# Mobile navigation focus lifecycle.
replace_once(
    "packages/rakit-web/src/rakit_web/static/rakit-shell.js",
    'navigation.querySelector("[data-rakit-mobile-navigation-close]")?.focus();',
    'navigation.querySelector("[data-rakit-mobile-navigation-close]")?.focus({ preventScroll: true });',
)
replace_once(
    "packages/rakit-web/src/rakit_web/static/rakit-shell.js",
    "    returnFocus.focus();",
    "    returnFocus.focus({ preventScroll: true });",
)

# Shared dialog/popover/filter focus lifecycle and disclosure state.
replace_once(
    "packages/rakit-web/src/rakit_web/static/rakit-ui.js",
    "  if (target instanceof HTMLElement && document.contains(target)) target.focus();",
    "  if (target instanceof HTMLElement && document.contains(target)) target.focus({ preventScroll: true });",
)
replace_once(
    "packages/rakit-web/src/rakit_web/static/rakit-ui.js",
    "    if (returnFocus instanceof HTMLElement && document.contains(returnFocus)) returnFocus.focus();",
    "    if (returnFocus instanceof HTMLElement && document.contains(returnFocus)) returnFocus.focus({ preventScroll: true });",
)
replace_once(
    "packages/rakit-web/src/rakit_web/static/rakit-ui.js",
    "  if (initialFocus instanceof HTMLElement) initialFocus.focus();",
    "  if (initialFocus instanceof HTMLElement) initialFocus.focus({ preventScroll: true });",
)
replace_once(
    "packages/rakit-web/src/rakit_web/static/rakit-ui.js",
    "  if (summary instanceof HTMLElement) summary.focus();",
    "  if (summary instanceof HTMLElement) summary.focus({ preventScroll: true });",
)
replace_once(
    "packages/rakit-web/src/rakit_web/static/rakit-ui.js",
    '  dialog.querySelector("[data-rakit-confirm-preview]")?.focus();',
    '  dialog.querySelector("[data-rakit-confirm-preview]")?.focus({ preventScroll: true });',
)
replace_once(
    "packages/rakit-web/src/rakit_web/static/rakit-ui.js",
    "  if (rail instanceof HTMLElement) rail.hidden = !visible;\n  if (show instanceof HTMLElement) show.hidden = visible;\n  if (hide instanceof HTMLElement) hide.hidden = !visible;",
    "  if (rail instanceof HTMLElement) rail.hidden = !visible;\n  if (show instanceof HTMLElement) {\n    show.hidden = visible;\n    show.setAttribute(\"aria-expanded\", visible ? \"true\" : \"false\");\n  }\n  if (hide instanceof HTMLElement) {\n    hide.hidden = !visible;\n    hide.setAttribute(\"aria-expanded\", visible ? \"true\" : \"false\");\n  }",
)
replace_once(
    "packages/rakit-web/src/rakit_web/static/rakit-ui.js",
    '      root.querySelector("[data-rakit-filter-rail-show]")?.focus();',
    '      root.querySelector("[data-rakit-filter-rail-show]")?.focus({ preventScroll: true });',
)
replace_once(
    "packages/rakit-web/src/rakit_web/static/rakit-ui.js",
    '      root.querySelector("[data-rakit-filter-rail-hide]")?.focus();',
    '      root.querySelector("[data-rakit-filter-rail-hide]")?.focus({ preventScroll: true });',
)

# Resource disclosure/selection semantics.
replace_once(
    "packages/rakit-web/src/rakit_web/templates/resources/_table.html",
    '        aria-controls="rakit-filter-drawer-{{ resource.resource_id }}"\n      >',
    '        aria-controls="rakit-filter-drawer-{{ resource.resource_id }}"\n        aria-haspopup="dialog"\n      >',
)
replace_once(
    "packages/rakit-web/src/rakit_web/templates/resources/_table.html",
    '        aria-controls="rakit-filter-rail-{{ resource.resource_id }}"\n      >',
    '        aria-controls="rakit-filter-rail-{{ resource.resource_id }}"\n        aria-expanded="false"\n      >',
)
replace_once(
    "packages/rakit-web/src/rakit_web/templates/resources/_table.html",
    '          <span class="mr-1 text-sm text-rakit-text-muted" data-rakit-selected-count>0 selected</span>',
    '          <span class="mr-1 text-sm text-rakit-text-muted" data-rakit-selected-count role="status" aria-live="polite" aria-atomic="true">0 selected</span>',
)
replace_once(
    "packages/rakit-web/src/rakit_web/templates/resources/_table.html",
    '<summary class="rakit-button rakit-button-secondary cursor-pointer list-none">More</summary>',
    '<summary class="rakit-button rakit-button-secondary cursor-pointer list-none" aria-label="More bulk actions">More</summary>',
)
replace_once(
    "packages/rakit-web/src/rakit_web/templates/resources/_table.html",
    '<button class="rakit-button rakit-button-quiet" type="button" hidden data-rakit-filter-rail-hide>Hide</button>',
    '<button class="rakit-button rakit-button-quiet" type="button" hidden data-rakit-filter-rail-hide aria-controls="rakit-filter-rail-{{ resource.resource_id }}" aria-expanded="true">Hide</button>',
)

# Action overflow groups expose a meaningful group and trigger name.
replace_once(
    "packages/rakit-web/src/rakit_web/templates/components/actions.html",
    '<div class="flex max-w-full flex-wrap items-start gap-2" data-rakit-action-group>',
    '<div class="flex max-w-full flex-wrap items-start gap-2" data-rakit-action-group role="group" aria-label="{{ label }}">',
)
replace_once(
    "packages/rakit-web/src/rakit_web/templates/components/actions.html",
    '<summary class="rakit-button rakit-button-secondary cursor-pointer list-none">More</summary>',
    '<summary class="rakit-button rakit-button-secondary cursor-pointer list-none" aria-label="More {{ label | lower }}">More</summary>',
)

# Contextual relationship row names: paginated reusable row-actions partial.
row_actions = "packages/rakit-web/src/rakit_web/templates/relationships/_row_actions.html"
replace_once(
    row_actions,
    'data-rakit-unlink-input type="checkbox" name="{{ panel.prefix }}unlink__{{ encoded }}" value="{{ encoded }}" checked />Undo removal',
    'data-rakit-unlink-input type="checkbox" name="{{ panel.prefix }}unlink__{{ encoded }}" value="{{ encoded }}" checked aria-label="Undo removal of {{ row.candidate.label }} from {{ panel.relationship.label }}" />Undo removal',
)
replace_once(
    row_actions,
    'data-rakit-unlink-destructive aria-pressed="true" tabindex="-1">Undo removal</button>',
    'data-rakit-unlink-destructive aria-pressed="true" aria-label="Undo removal of {{ row.candidate.label }} from {{ panel.relationship.label }}" tabindex="-1">Undo removal</button>',
)
replace_once(
    row_actions,
    'data-rakit-unlink-destructive data-rakit-preview-unlink aria-pressed="false" hx-post=',
    'data-rakit-unlink-destructive data-rakit-preview-unlink aria-pressed="false" aria-label="Remove {{ row.candidate.label }} from {{ panel.relationship.label }}" hx-post=',
)
replace_once(
    row_actions,
    'data-rakit-unlink-input type="checkbox" name="{{ panel.prefix }}unlink__{{ encoded }}" value="{{ encoded }}"{% if encoded in panel.pending_unlinks %} checked{% endif %} />{{ \'Undo removal\' if encoded in panel.pending_unlinks else \'Remove from relationship\' }}',
    'data-rakit-unlink-input type="checkbox" name="{{ panel.prefix }}unlink__{{ encoded }}" value="{{ encoded }}"{% if encoded in panel.pending_unlinks %} checked{% endif %} aria-label="{{ \'Undo removal of \' if encoded in panel.pending_unlinks else \'Remove \' }}{{ row.candidate.label }} from {{ panel.relationship.label }}" />{{ \'Undo removal\' if encoded in panel.pending_unlinks else \'Remove from relationship\' }}',
)
replace_once(
    row_actions,
    'aria-pressed="{{ \'true\' if encoded in panel.pending_unlinks else \'false\' }}" tabindex="-1">Toggle relationship removal</button>',
    'aria-pressed="{{ \'true\' if encoded in panel.pending_unlinks else \'false\' }}" aria-label="Toggle removal of {{ row.candidate.label }} from {{ panel.relationship.label }}" tabindex="-1">Toggle relationship removal</button>',
)
replace_once(
    row_actions,
    'data-rakit-preview-delete hx-post=',
    'data-rakit-preview-delete aria-label="Delete {{ row.candidate.label }}" hx-post=',
)

# Contextual relationship names: compact/non-paginated duplicate controls.
to_many = "packages/rakit-web/src/rakit_web/templates/relationships/to_many.html"
replace_once(
    to_many,
    'data-rakit-unlink-input type="checkbox" name="{{ panel.prefix }}unlink__{{ encoded }}" value="{{ encoded }}" checked />Undo removal',
    'data-rakit-unlink-input type="checkbox" name="{{ panel.prefix }}unlink__{{ encoded }}" value="{{ encoded }}" checked aria-label="Undo removal of {{ row.candidate.label }} from {{ panel.relationship.label }}" />Undo removal',
)
replace_once(
    to_many,
    'data-rakit-unlink-destructive aria-pressed="true" tabindex="-1">Undo removal</button>',
    'data-rakit-unlink-destructive aria-pressed="true" aria-label="Undo removal of {{ row.candidate.label }} from {{ panel.relationship.label }}" tabindex="-1">Undo removal</button>',
)
replace_once(
    to_many,
    'data-rakit-unlink-destructive data-rakit-preview-unlink aria-pressed="false" hx-post=',
    'data-rakit-unlink-destructive data-rakit-preview-unlink aria-pressed="false" aria-label="Remove {{ row.candidate.label }} from {{ panel.relationship.label }}" hx-post=',
)
replace_once(
    to_many,
    'data-rakit-unlink-input type="checkbox" name="{{ panel.prefix }}unlink__{{ encoded }}" value="{{ encoded }}"{% if encoded in panel.pending_unlinks %} checked{% endif %} />{{ \'Undo removal\' if encoded in panel.pending_unlinks else \'Remove from relationship\' }}',
    'data-rakit-unlink-input type="checkbox" name="{{ panel.prefix }}unlink__{{ encoded }}" value="{{ encoded }}"{% if encoded in panel.pending_unlinks %} checked{% endif %} aria-label="{{ \'Undo removal of \' if encoded in panel.pending_unlinks else \'Remove \' }}{{ row.candidate.label }} from {{ panel.relationship.label }}" />{{ \'Undo removal\' if encoded in panel.pending_unlinks else \'Remove from relationship\' }}',
)
replace_once(
    to_many,
    'aria-pressed="{{ \'true\' if encoded in panel.pending_unlinks else \'false\' }}" tabindex="-1">Toggle relationship removal</button>',
    'aria-pressed="{{ \'true\' if encoded in panel.pending_unlinks else \'false\' }}" aria-label="Toggle removal of {{ row.candidate.label }} from {{ panel.relationship.label }}" tabindex="-1">Toggle relationship removal</button>',
)
replace_once(
    to_many,
    'data-rakit-preview-delete hx-post=',
    'data-rakit-preview-delete aria-label="Delete {{ row.candidate.label }}" hx-post=',
)
