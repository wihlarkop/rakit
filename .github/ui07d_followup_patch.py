from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected exactly one match in {path}, got {count}: {old[:120]!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


# Apply web sidecars after ResourceAdmin registration has produced write bindings.
replace_once(
    "packages/rakit-web/src/rakit_web/dashboard_admin.py",
    '''        definition = self._resource_definitions[admin_cls.resource_id]\n        bind_resource_web_presentation(definition, presentation)\n        for action in declared_actions:\n''',
    '''        definition = self._resource_definitions[admin_cls.resource_id]\n        bind_resource_web_presentation(definition, presentation)\n        existing_write_binding = self._write_resource_bindings.get(admin_cls.resource_id)\n        if existing_write_binding is not None:\n            self._write_resource_bindings[admin_cls.resource_id] = self._configured_write_binding(\n                admin_cls.resource_id, existing_write_binding, presentation\n            )\n        for action in declared_actions:\n''',
)
old_method = '''    def register_write_resource(self, resource_id: str, binding: WriteResourceBinding) -> None:\n        definition = self._resource_definitions.get(resource_id)\n        if definition is None:\n            super().register_write_resource(resource_id, binding)\n            return\n        web = resource_web_presentation(definition)\n        known_fields = {field.field_id for field in binding.form_schema.fields}\n        unknown_fields = sorted(set(web.fields).difference(known_fields))\n        relationship_form = binding.relationship_form\n        known_relationships = (\n            {editor.relationship_id for editor in relationship_form.editors}\n            if relationship_form is not None\n            else set()\n        )\n        unknown_relationships = sorted(set(web.relationships).difference(known_relationships))\n        if unknown_fields or unknown_relationships:\n            raise RakitError(\n                code=ErrorCode.CONFIG_INVALID_RESOURCE_POLICY,\n                message="Invalid resource Web presentation declaration",\n                status_code=500,\n                details={\n                    "resource_id": resource_id,\n                    "reason": "unknown_web_widget_presentation",\n                    "field_ids": unknown_fields,\n                    "relationship_ids": unknown_relationships,\n                },\n            )\n        if relationship_form is not None:\n            try:\n                relationship_form = replace(\n                    relationship_form,\n                    editors=tuple(\n                        replace(\n                            editor,\n                            presentation=resolve_relationship_presentation(\n                                editor.relationship.definition.presentation,\n                                web.relationships.get(editor.relationship_id),\n                            ),\n                        )\n                        for editor in relationship_form.editors\n                    ),\n                )\n            except (TypeError, ValueError):\n                raise RakitError(\n                    code=ErrorCode.CONFIG_INVALID_RESOURCE_POLICY,\n                    message="Invalid resource Web presentation declaration",\n                    status_code=500,\n                    details={\n                        "resource_id": resource_id,\n                        "reason": "invalid_relationship_widget_presentation",\n                    },\n                ) from None\n        configured = replace(\n            binding,\n            field_presentations=web.fields,\n            relationship_form=relationship_form,\n        )\n        super().register_write_resource(resource_id, configured)\n\n'''
new_method = '''    def _configured_write_binding(\n        self,\n        resource_id: str,\n        binding: WriteResourceBinding,\n        web: ResourceWebPresentation,\n    ) -> WriteResourceBinding:\n        known_fields = {field.field_id for field in binding.form_schema.fields}\n        unknown_fields = sorted(set(web.fields).difference(known_fields))\n        relationship_form = binding.relationship_form\n        known_relationships = (\n            {editor.relationship_id for editor in relationship_form.editors}\n            if relationship_form is not None\n            else set()\n        )\n        unknown_relationships = sorted(set(web.relationships).difference(known_relationships))\n        if unknown_fields or unknown_relationships:\n            raise RakitError(\n                code=ErrorCode.CONFIG_INVALID_RESOURCE_POLICY,\n                message="Invalid resource Web presentation declaration",\n                status_code=500,\n                details={\n                    "resource_id": resource_id,\n                    "reason": "unknown_web_widget_presentation",\n                    "field_ids": unknown_fields,\n                    "relationship_ids": unknown_relationships,\n                },\n            )\n        if relationship_form is not None:\n            try:\n                relationship_form = replace(\n                    relationship_form,\n                    editors=tuple(\n                        replace(\n                            editor,\n                            presentation=resolve_relationship_presentation(\n                                editor.relationship.definition.presentation,\n                                web.relationships.get(editor.relationship_id),\n                            ),\n                        )\n                        for editor in relationship_form.editors\n                    ),\n                )\n            except (TypeError, ValueError):\n                raise RakitError(\n                    code=ErrorCode.CONFIG_INVALID_RESOURCE_POLICY,\n                    message="Invalid resource Web presentation declaration",\n                    status_code=500,\n                    details={\n                        "resource_id": resource_id,\n                        "reason": "invalid_relationship_widget_presentation",\n                    },\n                ) from None\n        return replace(\n            binding,\n            field_presentations=web.fields,\n            relationship_form=relationship_form,\n        )\n\n    def register_write_resource(self, resource_id: str, binding: WriteResourceBinding) -> None:\n        definition = self._resource_definitions.get(resource_id)\n        if definition is None:\n            super().register_write_resource(resource_id, binding)\n            return\n        configured = self._configured_write_binding(\n            resource_id, binding, resource_web_presentation(definition)\n        )\n        super().register_write_resource(resource_id, configured)\n\n'''
replace_once("packages/rakit-web/src/rakit_web/dashboard_admin.py", old_method, new_method)

# Boolean controls add one bounded hidden field per bool; keep max-field policy exact.
replace_once(
    "packages/rakit-web/src/rakit_web/form_routes.py",
    '''    file_ids = {field.field_id for field in file_fields(binding.form_schema)}\n    try:\n        form = await request.form(\n            max_files=len(file_ids),\n            max_fields=len(binding.form_schema.fields)\n            + (1_000 if binding.relationship_form else 4),\n        )\n''',
    '''    file_ids = {field.field_id for field in file_fields(binding.form_schema)}\n    boolean_field_count = sum(\n        field.python_type is bool for field in binding.form_schema.fields\n    )\n    try:\n        form = await request.form(\n            max_files=len(file_ids),\n            max_fields=len(binding.form_schema.fields)\n            + boolean_field_count\n            + (1_000 if binding.relationship_form else 4),\n        )\n''',
)

# Switch JS receives its typed labels; checkbox does not duplicate visible field label.
replace_once(
    "packages/rakit-web/src/rakit_web/templates/forms/_field_control.html",
    '''  <label class="rakit-boolean-control{% if key == 'switch' %} rakit-switch{% endif %}" data-rakit-widget="{{ key }}">\n''',
    '''  <label class="rakit-boolean-control{% if key == 'switch' %} rakit-switch{% endif %}" data-rakit-widget="{{ key }}"{% if key == 'switch' %} data-rakit-on-label="{{ field.presentation.on_label }}" data-rakit-off-label="{{ field.presentation.off_label }}"{% endif %}>\n''',
)
replace_once(
    "packages/rakit-web/src/rakit_web/templates/forms/_field_control.html",
    '''    {% if key == 'switch' %}<span class="rakit-switch-track" aria-hidden="true"><span class="rakit-switch-thumb"></span></span><span data-rakit-switch-label>{{ field.presentation.on_label if field.checked else field.presentation.off_label }}</span>{% else %}<span>{{ field.label }}</span>{% endif %}\n''',
    '''    {% if key == 'switch' %}<span class="rakit-switch-track" aria-hidden="true"><span class="rakit-switch-thumb"></span></span><span data-rakit-switch-label>{{ field.presentation.on_label if field.checked else field.presentation.off_label }}</span>{% endif %}\n''',
)

# Initialize single autocomplete from the canonical fallback selection.
replace_once(
    "packages/rakit-web/src/rakit_web/static/rakit-widgets.js",
    '''    for (const hidden of hiddenInputs()) {\n      const identity = hidden.value;\n''',
    '''    if (mode === "single") {\n      const select = fallback.querySelector("select");\n      const current = select?.selectedOptions?.[0];\n      if (current && current.value) {\n        input.value = current.textContent.trim();\n        if (selectedLabel) selectedLabel.textContent = current.textContent.trim();\n      }\n    }\n\n    for (const hidden of hiddenInputs()) {\n      const identity = hidden.value;\n''',
)

# Add semantic component primitives to maintainer Tailwind source.
css = Path("packages/rakit-web/src/rakit_web/assets/rakit.css")
text = css.read_text(encoding="utf-8")
marker = "\n@keyframes rakit-spin"
if marker not in text:
    raise SystemExit("could not locate rakit-spin marker")
addition = r'''

  .rakit-input-affix {
    @apply flex min-w-0 items-stretch overflow-hidden rounded-rakit-sm border border-rakit-border-strong bg-rakit-surface shadow-rakit-sm focus-within:border-rakit-focus;
  }

  .rakit-input-affix .rakit-input {
    @apply min-w-0 flex-1 rounded-none border-0 shadow-none focus:border-transparent;
  }

  .rakit-input-prefix,
  .rakit-input-suffix {
    @apply inline-flex shrink-0 items-center bg-rakit-surface-subtle px-3 text-sm font-medium text-rakit-text-muted;
  }

  .rakit-boolean-control {
    @apply inline-flex min-h-9 max-w-full items-center gap-2 rounded-rakit-sm text-sm font-medium text-rakit-text;
  }

  .rakit-switch-track {
    @apply relative inline-flex h-6 w-11 shrink-0 rounded-full border border-rakit-border-strong bg-rakit-surface-subtle transition;
  }

  .rakit-switch-thumb {
    @apply absolute left-0.5 top-0.5 size-[1.125rem] rounded-full bg-rakit-text-muted shadow-rakit-sm transition;
  }

  .rakit-switch:has(input:checked) .rakit-switch-track {
    @apply border-rakit-brand-600 bg-rakit-brand-600;
  }

  .rakit-switch:has(input:checked) .rakit-switch-thumb {
    @apply translate-x-5 bg-white;
  }

  .rakit-segmented {
    @apply inline-flex max-w-full flex-wrap overflow-hidden rounded-rakit-sm border border-rakit-border-strong bg-rakit-surface;
  }

  .rakit-segmented-option {
    @apply relative inline-flex min-h-9 cursor-pointer items-center border-r border-rakit-border px-3 text-sm font-medium text-rakit-text-muted last:border-r-0;
  }

  .rakit-segmented-option:has(input:checked) {
    @apply bg-rakit-brand-subtle text-rakit-text;
  }

  .rakit-segmented-option input {
    @apply sr-only;
  }

  .rakit-upload-control {
    @apply rounded-rakit-sm border border-dashed border-rakit-border-strong bg-rakit-surface-subtle p-3;
  }

  .rakit-upload-summary {
    @apply mt-2 text-xs text-rakit-text-muted [overflow-wrap:anywhere];
  }

  .rakit-image-preview {
    @apply mb-3 overflow-hidden rounded-rakit-sm border border-rakit-border bg-rakit-surface;
  }

  .rakit-image-preview img {
    @apply max-h-56 w-full object-contain;
  }

  .rakit-choice-chips {
    @apply flex flex-wrap gap-2;
  }

  .rakit-choice-chip {
    @apply inline-flex min-h-8 max-w-full items-center gap-1.5 rounded-full border border-rakit-border bg-rakit-brand-subtle px-3 py-1 text-sm font-medium text-rakit-text [overflow-wrap:anywhere];
  }

  .rakit-choice-chip-remove {
    @apply inline-flex size-6 shrink-0 items-center justify-center rounded-full text-rakit-text-muted transition hover:bg-rakit-surface hover:text-rakit-text;
  }

  .rakit-autocomplete-listbox {
    @apply z-40 max-h-64 w-full overflow-y-auto rounded-rakit-sm border border-rakit-border bg-rakit-surface p-1 shadow-rakit-lg;
  }

  .rakit-autocomplete-option {
    @apply flex cursor-pointer flex-col gap-0.5 rounded-rakit-sm px-3 py-2 text-sm text-rakit-text;
  }

  .rakit-autocomplete-option:hover,
  .rakit-autocomplete-option.is-active,
  .rakit-autocomplete-option[aria-selected="true"] {
    @apply bg-rakit-brand-subtle;
  }

  .rakit-autocomplete-option-label {
    @apply font-medium [overflow-wrap:anywhere];
  }

  .rakit-autocomplete-option-description,
  .rakit-autocomplete-empty {
    @apply text-xs text-rakit-text-muted;
  }

  .rakit-autocomplete-empty {
    @apply px-3 py-3;
  }
'''
text = text.replace(marker, addition + marker, 1)
css.write_text(text, encoding="utf-8")
