from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected exactly one match in {path}, got {count}: {old!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


css = "packages/rakit-web/src/rakit_web/assets/rakit.css"
replace_once(
    css,
    "  --color-rakit-text-subtle: oklch(0.66 0.018 285);",
    "  --color-rakit-text-subtle: oklch(0.54 0.018 285);",
)
replace_once(
    css,
    "    --color-rakit-text-subtle: oklch(0.54 0.022 285);",
    "    --color-rakit-text-subtle: oklch(0.62 0.022 285);",
)
replace_once(
    css,
    "    @apply border-rakit-danger bg-rakit-danger text-white hover:brightness-90;",
    "    @apply border-rakit-danger bg-rakit-danger text-rakit-bg hover:brightness-90;",
)
replace_once(
    css,
    "    @apply border-rakit-danger bg-rakit-danger text-white shadow-rakit-sm hover:brightness-90;",
    "    @apply border-rakit-danger bg-rakit-danger text-rakit-bg shadow-rakit-sm hover:brightness-90;",
)

confirm = "packages/rakit-web/src/rakit_web/templates/actions/_confirm.html"
replace_once(
    confirm,
    '<div class="rounded-rakit-md border border-amber-300 bg-amber-50 p-4 text-sm leading-6 text-amber-950" role="note">',
    '<div class="rakit-alert rakit-alert-warning" role="note">',
)
replace_once(
    confirm,
    '<p class="text-sm leading-6 text-rakit-text-muted">This change is applied only when you confirm and submit.</p>',
    '{% if danger %}<p class="text-sm leading-6 text-rakit-text-muted">This action is marked as potentially destructive. Review the impact carefully; it runs only when you confirm and submit.</p>{% else %}<p class="text-sm leading-6 text-rakit-text-muted">This change is applied only when you confirm and submit.</p>{% endif %}',
)

delete_confirm = "packages/rakit-web/src/rakit_web/templates/forms/delete_confirm.html"
replace_once(
    delete_confirm,
    '<p class="mt-2 text-sm leading-6 text-rakit-text-muted">Review this action before continuing.</p>',
    '<p class="mt-2 text-sm leading-6 text-rakit-text-muted">Review the deletion details before continuing.</p>',
)
replace_once(
    delete_confirm,
    '<p class="font-semibold">This record will be removed through the configured resource adapter.</p>\n        <p class="mt-1">The framework does not assume whether the adapter performs a physical or recoverable deletion.</p>',
    '<p class="font-semibold">Deleting invokes the configured resource adapter for this record.</p>\n        <p class="mt-1">Depending on the adapter, removal may be permanent or recoverable. Confirm only if you intend to remove this record.</p>',
)
