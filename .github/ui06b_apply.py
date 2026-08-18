from __future__ import annotations

from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    if text.count(old) != 1:
        raise RuntimeError(f"expected exactly one match in {path}: {old[:80]!r}; got {text.count(old)}")
    path.write_text(text.replace(old, new, 1))


relationship = Path("packages/rakit-web/src/rakit_web/relationship_routes.py")
replace_once(
    relationship,
    "    RelationshipKind,\n    resolve_record_label,",
    "    RelationshipDefinition,\n    RelationshipKind,\n    resolve_record_label,",
)
replace_once(
    relationship,
    "\n\nasync def relationship_panel_view(\n",
    '''\n\ndef _relationship_presentation_mode(\n    *,\n    definition: RelationshipDefinition,\n    has_previous: bool,\n    has_next: bool,\n) -> str:\n    \"\"\"Choose a Web presentation only from compiled semantics and page state.\"\"\"\n\n    if definition.cardinality is RelationshipCardinality.TO_ONE:\n        return \"to_one\"\n    if definition.edit_mode in {RelationshipEditMode.INLINE, RelationshipEditMode.NESTED}:\n        return \"inline\"\n    if has_previous or has_next:\n        return \"paginated\"\n    return \"compact\"\n\n\nasync def relationship_panel_view(\n''',
)
replace_once(
    relationship,
    '''    return {\n        "relationship": definition,\n''',
    '''    presentation_mode = _relationship_presentation_mode(\n        definition=definition,\n        has_previous=editor_page.has_previous,\n        has_next=editor_page.has_next,\n    )\n    return {\n        "relationship": definition,\n        "presentation_mode": presentation_mode,\n        "paginated": bool(editor_page.has_previous or editor_page.has_next),\n        "empty": not bool(rows) and not bool(draft_rows),\n''',
)

form_routes = Path("packages/rakit-web/src/rakit_web/form_routes.py")
replace_once(
    form_routes,
    "from ._paths import mounted_path\nfrom .file_uploads import (",
    "from ._paths import mounted_path\nfrom .file_presentation import file_field_presentation\nfrom .file_uploads import (",
)
replace_once(form_routes, "    file_accept,\n", "")
replace_once(
    form_routes,
    '''    parent_identity: RecordIdentity | None = None,\n    relationship_issues: tuple[Mapping[str, object], ...] = (),\n) -> Response:\n''',
    '''    parent_identity: RecordIdentity | None = None,\n    relationship_issues: tuple[Mapping[str, object], ...] = (),\n    current_record: object | None = None,\n) -> Response:\n''',
)
replace_once(
    form_routes,
    '''    controls = {\n        field.field_id: {\n            "id": _field_dom_id(binding, field.field_id),\n            "name": field.field_id,\n            "label": field.label or field.field_id,\n            "description": field.description,\n            "description_id": f"{_field_dom_id(binding, field.field_id)}-description",\n            "error_id": f"{_field_dom_id(binding, field.field_id)}-error",\n            "value": (submitted or {}).get(field.field_id, ""),\n            "issues": issue_map.get(field.field_id, ()),\n            "is_file": isinstance(field, FileField),\n            "accept": file_accept(field) if isinstance(field, FileField) else "",\n            "required": field.required,\n        }\n        for field in binding.form_schema.fields\n        if field.writable and field.readable and not field.sensitive\n    }\n''',
    '''    if current_record is None and parent_identity is not None:\n        getter = getattr(binding.mutation_service, "get", None)\n        if callable(getter):\n            current_record = await getter(parent_identity)\n\n    controls: dict[str, dict[str, object]] = {}\n    for field in binding.form_schema.fields:\n        if not (field.writable and field.readable and not field.sensitive):\n            continue\n        file_view = None\n        if isinstance(field, FileField):\n            current_file = (\n                record_stored_file(current_record, field) if current_record is not None else None\n            )\n            file_view = file_field_presentation(field, current_file)\n        controls[field.field_id] = {\n            "id": _field_dom_id(binding, field.field_id),\n            "name": field.field_id,\n            "label": field.label or field.field_id,\n            "description": field.description,\n            "description_id": f"{_field_dom_id(binding, field.field_id)}-description",\n            "error_id": f"{_field_dom_id(binding, field.field_id)}-error",\n            "file_help_id": f"{_field_dom_id(binding, field.field_id)}-file-help",\n            "current_file_id": f"{_field_dom_id(binding, field.field_id)}-current-file",\n            "value": (submitted or {}).get(field.field_id, ""),\n            "issues": issue_map.get(field.field_id, ()),\n            "is_file": isinstance(field, FileField),\n            "accept": file_view.accept if file_view is not None else "",\n            "file": file_view,\n            "required": field.required and not (file_view is not None and file_view.current is not None),\n        }\n''',
)
# Avoid an unnecessary second fetch on the normal edit GET while retaining the fallback for
# relationship preview/validation re-renders that only have the canonical parent identity.
replace_once(
    form_routes,
    '''            parent_identity=identity,\n            operation="update",\n        )\n\n    async def update_post''',
    '''            parent_identity=identity,\n            operation="update",\n            current_record=record,\n        )\n\n    async def update_post''',
)

form_template = Path("packages/rakit-web/src/rakit_web/templates/forms/form.html")
replace_once(
    form_template,
    '''        {% if field.description %}{% set _ = descriptions.append(field.description_id) %}{% endif %}\n        {% if field.issues %}{% set _ = descriptions.append(field.error_id) %}{% endif %}\n        {% if field.is_file %}\n        <input class="rakit-file-input" type="file" id="{{ field.id }}" name="{{ field.name }}"{% if field.accept %} accept="{{ field.accept }}"{% endif %}{% if field.required %} required{% endif %}{% if descriptions %} aria-describedby="{{ descriptions | join(' ') }}"{% endif %}{% if field.issues %} aria-invalid="true"{% endif %} />\n        {% else %}\n''',
    '''        {% if field.description %}{% set _ = descriptions.append(field.description_id) %}{% endif %}\n        {% if field.is_file and field.file %}{% set _ = descriptions.append(field.file_help_id) %}{% endif %}\n        {% if field.is_file and field.file and field.file.current %}{% set _ = descriptions.append(field.current_file_id) %}{% endif %}\n        {% if field.issues %}{% set _ = descriptions.append(field.error_id) %}{% endif %}\n        {% if field.is_file %}\n          {% if field.file and field.file.current %}\n            <div id="{{ field.current_file_id }}" class="mb-2 rounded-rakit-sm border border-rakit-border bg-rakit-surface-subtle p-3">\n              <p class="text-xs font-medium uppercase tracking-wide text-rakit-text-subtle">Current file</p>\n              <p class="mt-1 text-sm font-medium text-rakit-text">{{ field.file.current.name }}</p>\n              <p class="mt-1 text-xs text-rakit-text-muted">{{ field.file.current.size_label }} · {{ field.file.current.content_type }}</p>\n            </div>\n          {% endif %}\n          <input class="rakit-file-input" type="file" id="{{ field.id }}" name="{{ field.name }}"{% if field.accept %} accept="{{ field.accept }}"{% endif %}{% if field.required %} required{% endif %}{% if descriptions %} aria-describedby="{{ descriptions | join(' ') }}"{% endif %}{% if field.issues %} aria-invalid="true"{% endif %} />\n          {% if field.file %}<p id="{{ field.file_help_id }}" class="rakit-field-help">{{ field.file.policy_hint }}{% if field.file.current %} Choose a new file to replace the current file; leave this empty to keep it.{% endif %}</p>{% endif %}\n        {% else %}\n''',
)

inline = Path("packages/rakit-web/src/rakit_web/templates/relationships/inline_rows.html")
text = inline.read_text()
replacements = {
    "border-slate-200": "border-rakit-border",
    "divide-slate-200": "divide-rakit-border",
    "divide-slate-100": "divide-rakit-border",
    "bg-slate-50": "bg-rakit-surface-subtle",
    "bg-white": "bg-rakit-surface",
    "text-slate-500": "text-rakit-text-muted",
    "text-slate-800": "text-rakit-text",
    "text-slate-700": "text-rakit-text-muted",
    "text-red-700": "text-rakit-danger-text",
    "text-amber-700": "text-rakit-text-muted",
    "bg-red-50/60": "bg-rakit-danger-subtle",
    "bg-amber-50": "bg-rakit-surface-subtle",
    "border-slate-300": "border-rakit-border",
    "border-blue-200": "border-rakit-border",
    "bg-blue-50/50": "bg-rakit-surface-subtle",
    "text-blue-950": "text-rakit-text",
    "hover:bg-slate-50": "hover:bg-rakit-surface-subtle",
    "hover:bg-red-50": "hover:bg-rakit-danger-subtle",
    "Delete item": "Delete record",
}
for old, new in replacements.items():
    text = text.replace(old, new)
# Native submit controls preserve the exact move grammar when JavaScript is disabled.
text = text.replace(
    '''class="rakit-button rakit-button-quiet" type="button" aria-label="Move {{ row.candidate.label }} up"''',
    '''class="rakit-button rakit-button-quiet" type="submit" name="{{ panel.prefix }}move__{{ encoded }}__up" value="up" aria-label="Move {{ row.candidate.label }} up"''',
)
text = text.replace(
    '''class="rakit-button rakit-button-quiet" type="button" aria-label="Move {{ row.candidate.label }} down"''',
    '''class="rakit-button rakit-button-quiet" type="submit" name="{{ panel.prefix }}move__{{ encoded }}__down" value="down" aria-label="Move {{ row.candidate.label }} down"''',
)
inline.write_text(text)

error_summary = Path("packages/rakit-web/src/rakit_web/templates/relationships/error_summary.html")
error_summary.write_text('''<div class="rakit-alert rakit-alert-danger" role="alert" tabindex="-1">\n  <p class="font-semibold">There are problems with this relationship</p>\n  <ul class="mt-2 list-disc pl-5"><li>{{ message }}</li></ul>\n</div>\n''')

for template_name in ("preview_confirm.html", "preview_dialog.html"):
    path = Path("packages/rakit-web/src/rakit_web/templates/relationships") / template_name
    text = path.read_text()
    for old, new in {
        "border-slate-200": "border-rakit-border",
        "text-slate-500": "text-rakit-text-muted",
        "text-slate-950": "text-rakit-text",
        "text-slate-900": "text-rakit-text",
        "text-slate-600": "text-rakit-text-muted",
        "border-amber-200 bg-amber-50 p-3 text-sm text-amber-950": "border-rakit-border bg-rakit-surface-subtle p-3 text-sm text-rakit-text",
    }.items():
        text = text.replace(old, new)
    path.write_text(text)

print("UI-06B source presentation patch applied")
