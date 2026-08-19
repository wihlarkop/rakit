from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected exactly one match in {path}, got {count}: {old[:120]!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


# Make presentation metadata keyword-only so FileField positional compatibility is also preserved.
replace_once(
    "packages/rakit-core/src/rakit_core/fields.py",
    "    presentation: object | None = None\n",
    "    presentation: object | None = field(default=None, kw_only=True)\n",
)

# Wire the user's relationship acceptance surface to the preferred inline API.
replace_once(
    "examples/ui_showcase/advanced_states.py",
    "    Admin,\n    DataSourceCapabilities,\n",
    "    Admin,\n    Autocomplete,\n    DataSourceCapabilities,\n    FileUpload,\n",
)
replace_once(
    "examples/ui_showcase/advanced_states.py",
    "    LauncherItem,\n    PageDefinition,\n",
    "    LauncherItem,\n    MultiAutocomplete,\n    PageDefinition,\n",
)
replace_once(
    "examples/ui_showcase/advanced_states.py",
    '''    edit_mode=RelationshipEditMode.LINK,\n    record_label_field="name",\n)\n_TAGS = RelationshipDefinition(\n''',
    '''    edit_mode=RelationshipEditMode.LINK,\n    record_label_field="name",\n    presentation=Autocomplete(\n        search_fields=("name",),\n        display_fields=("name", "team"),\n        placeholder="Search customer...",\n        min_query_length=1,\n        page_size=12,\n    ),\n)\n_TAGS = RelationshipDefinition(\n''',
)
replace_once(
    "examples/ui_showcase/advanced_states.py",
    '''    edit_mode=RelationshipEditMode.LINK,\n    record_label_field="name",\n)\n_PARTICIPANTS = RelationshipDefinition(\n''',
    '''    edit_mode=RelationshipEditMode.LINK,\n    record_label_field="name",\n    presentation=MultiAutocomplete(\n        search_fields=("name",),\n        display_fields=("name", "team"),\n        placeholder="Add team links...",\n        min_query_length=1,\n        page_size=12,\n    ),\n)\n_PARTICIPANTS = RelationshipDefinition(\n''',
)
replace_once(
    "examples/ui_showcase/advanced_states.py",
    '''    edit_mode=RelationshipEditMode.LINK,\n    record_label_field="name",\n)\n_LINE_ITEMS = RelationshipDefinition(\n''',
    '''    edit_mode=RelationshipEditMode.LINK,\n    record_label_field="name",\n    presentation=MultiAutocomplete(\n        search_fields=("name",),\n        display_fields=("name", "team"),\n        placeholder="Add participants...",\n        min_query_length=1,\n        page_size=10,\n    ),\n)\n_LINE_ITEMS = RelationshipDefinition(\n''',
)
replace_once(
    "examples/ui_showcase/advanced_states.py",
    '''                    allowed_mime_types=("application/pdf",),\n                ),\n''',
    '''                    allowed_mime_types=("application/pdf",),\n                    presentation=FileUpload(drag_drop=True, preview=True),\n                ),\n''',
)

# Add deterministic scalar advanced-widget states to the existing UI Lab.
ui_lab = Path("examples/ui_showcase/templates/ui_lab.html")
text = ui_lab.read_text(encoding="utf-8")
marker = '''  <section class="rakit-panel">\n    <header class="rakit-panel-header"><h2 class="text-sm font-semibold text-rakit-text">Status</h2></header>\n'''
if text.count(marker) != 1:
    raise SystemExit("could not locate unique UI Lab Status section")
advanced = r'''  <section class="rakit-panel" id="ui-lab-advanced-widgets">
    <header class="rakit-panel-header"><h2 class="text-sm font-semibold text-rakit-text">Advanced field presentations</h2></header>
    <div class="rakit-panel-body grid gap-5 lg:grid-cols-2">
      <div class="space-y-1.5" data-rakit-widget="searchable_select">
        <label class="block text-sm font-medium text-rakit-text" for="lab-searchable-status">Searchable select</label>
        <input class="rakit-input" type="search" data-rakit-searchable-select-input placeholder="Search status..." autocomplete="off" hidden />
        <select class="rakit-select" id="lab-searchable-status"><option>Published</option><option>Pending review</option><option>Archived</option></select>
      </div>
      <div class="space-y-1.5">
        <label class="block text-sm font-medium text-rakit-text" for="lab-date">Date picker</label>
        <input class="rakit-input" data-rakit-widget="date" id="lab-date" type="date" value="2026-08-19" />
      </div>
      <div class="space-y-1.5">
        <label class="block text-sm font-medium text-rakit-text" for="lab-time">Time picker</label>
        <input class="rakit-input" data-rakit-widget="time" id="lab-time" type="time" value="14:30" />
      </div>
      <div class="space-y-1.5">
        <label class="block text-sm font-medium text-rakit-text" for="lab-datetime">Date and time</label>
        <input class="rakit-input" data-rakit-widget="datetime" id="lab-datetime" type="datetime-local" value="2026-08-19T14:30" />
      </div>
      <div class="space-y-1.5">
        <label class="block text-sm font-medium text-rakit-text" for="lab-currency">Currency</label>
        <div class="rakit-input-affix" data-rakit-widget="currency" data-rakit-currency="IDR" data-rakit-locale="id-ID"><span class="rakit-input-prefix" aria-hidden="true">IDR</span><input class="rakit-input" id="lab-currency" type="number" value="1250000" step="1000" /></div>
      </div>
      <div class="space-y-1.5">
        <label class="block text-sm font-medium text-rakit-text" for="lab-percentage">Percentage</label>
        <div class="rakit-input-affix" data-rakit-widget="percentage" data-rakit-percentage-scale="whole"><input class="rakit-input" id="lab-percentage" type="number" value="15" min="0" max="100" /><span class="rakit-input-suffix" aria-hidden="true">%</span></div>
      </div>
      <div class="space-y-1.5">
        <span class="block text-sm font-medium text-rakit-text">Switch</span>
        <label class="rakit-boolean-control rakit-switch" data-rakit-widget="switch" data-rakit-on-label="Enabled" data-rakit-off-label="Disabled"><input class="rakit-checkbox" type="checkbox" checked /><span class="rakit-switch-track" aria-hidden="true"><span class="rakit-switch-thumb"></span></span><span data-rakit-switch-label>Enabled</span></label>
      </div>
      <fieldset class="space-y-1.5">
        <legend class="block text-sm font-medium text-rakit-text">Segmented control</legend>
        <div class="rakit-segmented" data-rakit-widget="segmented" role="radiogroup" aria-label="Priority"><label class="rakit-segmented-option"><input type="radio" name="lab-priority" checked /><span>Normal</span></label><label class="rakit-segmented-option"><input type="radio" name="lab-priority" /><span>High</span></label><label class="rakit-segmented-option"><input type="radio" name="lab-priority" /><span>Urgent</span></label></div>
      </fieldset>
      <div class="space-y-1.5" data-rakit-widget="file_upload">
        <label class="block text-sm font-medium text-rakit-text" for="lab-advanced-file">Advanced file upload</label>
        <div class="rakit-upload-control"><input class="rakit-file-input" data-rakit-file-input id="lab-advanced-file" type="file" /><div class="rakit-upload-summary" data-rakit-file-summary role="status" aria-live="polite"></div></div>
      </div>
      <div class="space-y-1.5" data-rakit-widget="image_upload">
        <label class="block text-sm font-medium text-rakit-text" for="lab-advanced-image">Image preview</label>
        <div class="rakit-upload-control"><div class="rakit-image-preview" data-rakit-image-preview hidden><img alt="Selected image preview" data-rakit-image-preview-image /></div><input class="rakit-file-input" data-rakit-file-input id="lab-advanced-image" type="file" accept="image/*" /><div class="rakit-upload-summary" data-rakit-file-summary role="status" aria-live="polite"></div></div>
      </div>
    </div>
  </section>

'''
ui_lab.write_text(text.replace(marker, advanced + marker, 1), encoding="utf-8")
