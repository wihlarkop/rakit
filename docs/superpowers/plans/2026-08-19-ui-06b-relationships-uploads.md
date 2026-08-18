# UI-06B Relationships & Uploads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mature relationship editors and file fields into adaptive, policy-aware default UI without adding new relationship/storage semantics or weakening graph-mutation, permission, confirmation, ordering, or storage lifecycle contracts.

**Architecture:** Keep relationship semantics entirely in the compiled `RelationshipDefinition` / `RelationshipEditorBinding` contracts and derive presentation from the existing editor result. Compact-vs-paginated relationship rendering is result/capability-driven, not based on a new magic threshold. File presentation remains a normal `FileField` form control: expose safe policy/current-file metadata to the template, but do not invent a field-clear/delete mutation that the current write runtime does not own.

**Tech Stack:** Python 3.12+, Starlette ASGI, Jinja2, HTMX progressive enhancement, Tailwind CSS 4.1.18, existing Rakit graph-mutation/file-storage services, pytest/pytest-anyio, Ruff, ty.

**Spec:** `docs/superpowers/specs/2026-08-19-ui-06-advanced-operations-auth-system-design.md`

## Global Constraints

- Work from the latest `ui-06-advanced-operations` integration head after UI-06A is merged; implement UI-06B on a child branch.
- Feature/source implementation comes first; regression tests are added at the end of the slice.
- Do not create `RelationshipPresentation` or `UploadPresentation` public APIs in UI-06B.
- `RelationshipDefinition.cardinality`, `edit_mode`, `effective_writable`, compiled permissions, destructive policy, and ordering capability remain authoritative.
- Compact-vs-paginated TO_MANY rendering is driven by the existing relationship result: when `has_previous_page` or `has_next_page` is true, use the paginated/table presentation; when the entire current linked set is available in one result, use the compact presentation. Do not introduce another cardinality threshold.
- `INLINE` / `NESTED` remain editable-row modes only when explicitly declared; `LINK` is not silently converted into an inline editor.
- `READ_ONLY` renders information only; `HIDDEN` remains absent.
- Unlink/remove membership and persistent child delete must remain visibly and semantically distinct.
- Persistent delete controls appear only when `delete_available` is true from the existing compiled policy + permission + preview/confirmation capability.
- Reorder controls appear only when `reorderable` is true. `reorder_unavailable` must explain why ordering cannot be changed instead of showing fake controls.
- Drag-and-drop is optional enhancement only; the existing move-up/move-down form transport is the SSR baseline.
- Candidate search/pagination remains server-side and permission-scoped.
- `FileField.delete_behavior` controls cleanup when a record/replacement lifecycle deletes stored objects; it is **not** permission to clear a file field during edit. UI-06B must not expose a field-level “Remove file” control unless an explicit field-clear mutation capability exists. No such capability is added in this slice.
- File validation and storage remain server-authoritative; client-visible hints are explanatory only.
- Do not expose storage keys, internal paths, checksums, or backend configuration as UI help text.
- Do not show fake upload progress.
- Edit `packages/rakit-web/src/rakit_web/assets/rakit.css`; regenerate `packages/rakit-web/src/rakit_web/static/rakit.css` with `bun run css:build`. Never hand-edit generated CSS.
- No JavaScript-only critical relationship path.
- No release/tag/PyPI action.

---

## File Map

### Create
- `packages/rakit-web/src/rakit_web/file_presentation.py` — internal, Web-only safe file metadata/hint formatting; not exported as a public customization API.
- `packages/rakit-web/tests/test_relationship_upload_ui_maturity.py` — slice-level UI contract tests, created only after the feature exists.

### Modify
- `packages/rakit-web/src/rakit_web/relationship_routes.py` — add explicit result-driven presentation flags to the existing panel view; no mutation semantics changes.
- `packages/rakit-web/src/rakit_web/form_routes.py` — attach safe `FileField` policy/current-file presentation metadata to field controls.
- `packages/rakit-web/src/rakit_web/file_uploads.py` — reuse existing stored-file parsing; no storage lifecycle behavior changes.
- `packages/rakit-web/src/rakit_web/templates/relationships/panel.html`
- `packages/rakit-web/src/rakit_web/templates/relationships/to_one.html`
- `packages/rakit-web/src/rakit_web/templates/relationships/to_many.html`
- `packages/rakit-web/src/rakit_web/templates/relationships/inline_rows.html`
- `packages/rakit-web/src/rakit_web/templates/relationships/options.html`
- `packages/rakit-web/src/rakit_web/templates/relationships/error_summary.html`
- `packages/rakit-web/src/rakit_web/templates/relationships/preview_confirm.html`
- `packages/rakit-web/src/rakit_web/templates/relationships/preview_dialog.html`
- `packages/rakit-web/src/rakit_web/templates/forms/form.html` — mature file field current/replace presentation.
- `packages/rakit-web/src/rakit_web/assets/rakit.css`
- `packages/rakit-web/src/rakit_web/static/rakit.css` — generated output.
- `packages/rakit-web/src/rakit_web/static/rakit-ui.js` — only if needed for non-critical disclosure/dialog polish; existing relationship state transport stays authoritative.
- `examples/ui_showcase/main.py` — deterministic relationship/upload states.
- Existing regression suites covering relationship forms/routes, graph mutation, file uploads, and form routes.

---

### Task 1: Make Relationship Presentation State Explicit and Result-Driven

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/relationship_routes.py`

**Interfaces:**
- Consumes: existing `relationship_panel_view()` values including `rows`, `has_previous_page`, `has_next_page`, `reorderable`, `reorder_unavailable`, `delete_available`, `clear_available`, `relationship.cardinality`, and `relationship.edit_mode`.
- Produces: template-only flags `presentation_mode`, `paginated`, and `empty` while preserving all existing panel keys.

- [ ] **Step 1: Add a private presentation resolver without changing graph semantics**

Add near `relationship_panel_view()`:

```python
def _relationship_presentation_mode(
    *,
    definition: RelationshipDefinition,
    has_previous: bool,
    has_next: bool,
) -> str:
    if definition.cardinality is RelationshipCardinality.TO_ONE:
        return "to_one"
    if definition.edit_mode in {RelationshipEditMode.INLINE, RelationshipEditMode.NESTED}:
        return "inline"
    if has_previous or has_next:
        return "paginated"
    return "compact"
```

Import `RelationshipDefinition` only if needed for annotation. This function must not inspect record count against a new number.

- [ ] **Step 2: Extend the panel view with template-only state**

Before returning from `relationship_panel_view()`, calculate:

```python
presentation_mode = _relationship_presentation_mode(
    definition=definition,
    has_previous=editor_page.has_previous,
    has_next=editor_page.has_next,
)
```

Add only:

```python
"presentation_mode": presentation_mode,
"paginated": bool(editor_page.has_previous or editor_page.has_next),
"empty": not bool(rows) and not bool(draft_rows),
```

Keep `rows`, `total_label`, pagination URLs, destructive flags, order values, pending inputs, and confirmation state unchanged.

- [ ] **Step 3: Verify the change is presentation-only**

```powershell
uv run ruff format packages/rakit-web/src/rakit_web/relationship_routes.py
uv run ruff check packages/rakit-web/src/rakit_web/relationship_routes.py
uv run ty check
```

Inspect the diff and confirm no code inside `build_relationship_changes`, confirmation issuance/verification, authorization, or graph-mutation construction changed.

- [ ] **Step 4: Commit the relationship view state**

```powershell
git add packages/rakit-web/src/rakit_web/relationship_routes.py
git commit -m "feat(web): expose adaptive relationship presentation state"
```

---

### Task 2: Refine TO_ONE and Compact TO_MANY Relationship Surfaces

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/templates/relationships/panel.html`
- Modify: `packages/rakit-web/src/rakit_web/templates/relationships/to_one.html`
- Modify: `packages/rakit-web/src/rakit_web/templates/relationships/to_many.html`
- Modify: `packages/rakit-web/src/rakit_web/templates/relationships/error_summary.html`

**Interfaces:**
- Consumes: `panel.presentation_mode`, existing panel rows/options/selected/clear/unlink state.
- Produces: compact relationship UI that preserves every existing field name and submission value.

- [ ] **Step 1: Make `panel.html` the calm relationship container**

Keep the existing hidden concurrency/pending/error inputs exactly. Restructure visible chrome to:
- title + `total_label` in one header;
- concise edit-mode/read-only context;
- semantic error summary using `rakit-alert rakit-alert-danger`;
- divider-based body rather than nested cards;
- pagination controls only when `panel.paginated`.

Do not add a second nested panel around `to_one.html` / `to_many.html`.

- [ ] **Step 2: Refine TO_ONE LINK**

For `RelationshipEditMode.LINK`:
- selected/current row renders as plain record label with Change/Clear affordances;
- empty state uses `No <label-lower> linked yet.`;
- Clear appears only when `panel.clear_available`;
- candidate `<select>` / search helper keeps existing `name="{{ panel.prefix }}set"` and option identity values;
- read-only mode shows the current label or a neutral empty state and no controls.

Do not reinterpret Clear as child delete. If clear/unlink has destructive cascade semantics, keep the existing preview/confirmation flow.

- [ ] **Step 3: Refine compact TO_MANY LINK**

When `panel.presentation_mode == "compact"`:
- render linked rows as a vertical list with record label and compact per-row actions;
- use “Remove from relationship” for unlink controls;
- use “Delete record” only when `panel.delete_available` and keep it visually in danger treatment;
- empty state is explicit;
- candidate add/connect controls stay separate from existing membership;
- pending unlink/delete state remains visually obvious but keeps existing input transport.

Keep all names such as `unlink__<identity>`, `delete_intent__<identity>`, confirmation inputs, and link fields unchanged.

- [ ] **Step 4: Use semantic tokens only**

Replace direct slate/red/amber palette utility usage in these templates with `text-rakit-*`, `border-rakit-*`, `rakit-alert-*`, `rakit-button-*`, and existing semantic status primitives.

- [ ] **Step 5: Render templates in a structural smoke check**

```powershell
uv run python -c "from rakit_web.resource_routes import build_templates; t=build_templates(()); [t.env.get_template(p) for p in ('relationships/panel.html','relationships/to_one.html','relationships/to_many.html')]"
uv run ruff format --check .
uv run ruff check .
```

Expected: templates load without Jinja syntax errors.

- [ ] **Step 6: Commit compact relationship UI**

```powershell
git add packages/rakit-web/src/rakit_web/templates/relationships/panel.html packages/rakit-web/src/rakit_web/templates/relationships/to_one.html packages/rakit-web/src/rakit_web/templates/relationships/to_many.html packages/rakit-web/src/rakit_web/templates/relationships/error_summary.html
git commit -m "feat(web): refine compact relationship editors"
```

---

### Task 3: Mature Paginated, Inline/Nested, Ordering, and Destructive Relationship States

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/templates/relationships/to_many.html`
- Modify: `packages/rakit-web/src/rakit_web/templates/relationships/inline_rows.html`
- Modify: `packages/rakit-web/src/rakit_web/templates/relationships/options.html`
- Modify: `packages/rakit-web/src/rakit_web/templates/relationships/preview_confirm.html`
- Modify: `packages/rakit-web/src/rakit_web/templates/relationships/preview_dialog.html`
- Modify: `packages/rakit-web/src/rakit_web/assets/rakit.css`
- Regenerate: `packages/rakit-web/src/rakit_web/static/rakit.css`

**Interfaces:**
- Consumes: existing `panel.page`, `has_previous_page`, `has_next_page`, `page_path`, `rows`, `inline_fields`, `reorderable`, `order_values`, `reorder_unavailable`, `unlink_destructive`, `delete_available`, preview paths.
- Produces: scalable table/list UI with server-side paging and accessible ordering controls.

- [ ] **Step 1: Render result-driven paginated TO_MANY as a compact table/list**

When `panel.presentation_mode == "paginated"`, render:
- current linked members in a semantic table or divided list;
- total/page label;
- Previous/Next buttons using the existing relationship page helper route;
- existing membership controls per row according to editability/destructive flags.

Do not introduce local client-side pagination; navigation must continue using the server helper route and form state.

- [ ] **Step 2: Keep candidate discovery server-scoped**

Refine `options.html` so search results are readable and selectable, but do not preload the full target resource or filter options in JavaScript. Existing server candidate query remains authoritative.

Keep encoded identity values and selected state unchanged.

- [ ] **Step 3: Refine INLINE/NESTED rows without converting modes**

In `inline_rows.html`:
- use a clear row/table hierarchy;
- preserve create/update/association input names exactly;
- retain row-level validation messages;
- keep “Add row” only when target create capability/schema exists;
- keep update controls only for writable rows;
- distinguish unlink vs permanent delete labels.

`NESTED` uses the same existing runtime data model; do not introduce deeper recursion beyond the already compiled `max_nested_depth` behavior.

- [ ] **Step 4: Make reorder controls accessible and capability-bound**

If `panel.reorderable`:
- keep hidden `order__NNNN` inputs;
- expose native submit buttons for Move up / Move down using the existing `move__<identity>__up|down` transport;
- disable/impossible-direction buttons at first/last row where the template can determine position;
- add drag handles only if an existing JS enhancement can map back to the same complete order transport. Dragging is not required for UI-06B.

If `panel.reorder_unavailable`, show neutral help text such as `Reordering is unavailable for this relationship view.` and no move controls.

- [ ] **Step 5: Mature destructive preview/confirmation copy**

`preview_confirm.html` and `preview_dialog.html` must name the operation accurately:
- unlink/cascade-removal: “Remove from relationship”;
- persistent child deletion: “Delete record” / “Delete related record permanently”.

Use semantic warning/danger styling, but keep every confirmation token/intent/impact data attribute and hidden field unchanged.

- [ ] **Step 6: Add only reusable relationship CSS primitives**

If repeated across compact and paginated modes, add stable primitives such as `.rakit-relationship-row` or `.rakit-relationship-actions`. Do not create page-specific classes for one template.

Rebuild:

```powershell
bun run css:build
```

- [ ] **Step 7: Run structural verification**

```powershell
uv run ruff format --check .
uv run ruff check .
uv run ty check
```

- [ ] **Step 8: Commit scalable relationship states**

```powershell
git add packages/rakit-web/src/rakit_web/templates/relationships packages/rakit-web/src/rakit_web/assets/rakit.css packages/rakit-web/src/rakit_web/static/rakit.css
git commit -m "feat(web): mature advanced relationship states"
```

---

### Task 4: Add Safe File-Field Presentation Metadata

**Files:**
- Create: `packages/rakit-web/src/rakit_web/file_presentation.py`
- Modify: `packages/rakit-web/src/rakit_web/form_routes.py`
- Reuse: `packages/rakit-web/src/rakit_web/file_uploads.py`

**Interfaces:**
- Consumes: `FileField`, `stored_file_from_value()`, current update-record value.
- Produces: internal `FileFieldPresentation` containing only user-safe policy/current-file information.

- [ ] **Step 1: Create internal immutable file presentation types**

Use:

```python
from __future__ import annotations

from dataclasses import dataclass

from rakit_core.fields import FileField
from rakit_storage import StoredFile


@dataclass(frozen=True, slots=True)
class CurrentFilePresentation:
    name: str
    size_label: str
    content_type: str | None


@dataclass(frozen=True, slots=True)
class FileFieldPresentation:
    accept: str
    policy_hint: str
    current: CurrentFilePresentation | None = None
```

Do not export these from `rakit` public API.

- [ ] **Step 2: Add deterministic byte-size formatting**

Implement:

```python
def format_file_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"
```

Strip trailing `.0` if desired, but use one deterministic formatter everywhere.

- [ ] **Step 3: Build only safe policy hints**

`file_field_presentation(field, current)` constructs copy like:
- extension labels from `allowed_extensions` when present (`PDF`, `JPG` etc.);
- otherwise a generic MIME label only when it is human-readable enough;
- maximum size using `format_file_size(field.max_size)`;
- optional filename limit only when unusually constrained and useful.

Example result: `PDF only · Maximum 10 MB`.

Never include `storage_id`, `prefix`, stored key, checksum, or backend path.

- [ ] **Step 4: Pass the actual existing file separately from submitted scalar display state**

Extend `_form_response(..., current_record: object | None = None)`.

For each `FileField`, derive:

```python
current = record_stored_file(current_record, field) if current_record is not None else None
```

and include:

```python
"file": file_field_presentation(field, current),
```

inside the existing control dict.

For `update_get`, pass `current_record=record` to `_form_response`.

For update validation re-render paths, pass the same `record` that was loaded before parsing/mutation so the current stored file remains visible even after a failed replacement attempt.

Create routes use `current_record=None`.

- [ ] **Step 5: Do not add field-clear transport**

Do **not** add form names such as `delete_file`, `clear_file`, `remove_file`, or reinterpret empty upload as deletion. Existing `prepare_file_submission()` intentionally preserves the previous file when no replacement is submitted; keep that behavior unchanged.

- [ ] **Step 6: Run static verification**

```powershell
uv run ruff format packages/rakit-web/src/rakit_web/file_presentation.py packages/rakit-web/src/rakit_web/form_routes.py
uv run ruff check packages/rakit-web/src/rakit_web/file_presentation.py packages/rakit-web/src/rakit_web/form_routes.py
uv run ty check
```

- [ ] **Step 7: Commit file presentation metadata**

```powershell
git add packages/rakit-web/src/rakit_web/file_presentation.py packages/rakit-web/src/rakit_web/form_routes.py
git commit -m "feat(web): expose safe file field presentation"
```

---

### Task 5: Mature the File Input Surface

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/templates/forms/form.html`
- Modify: `packages/rakit-web/src/rakit_web/assets/rakit.css`
- Regenerate: `packages/rakit-web/src/rakit_web/static/rakit.css`

**Interfaces:**
- Consumes: `field.file.current`, `field.file.policy_hint`, existing `field.accept`, `field.required`, validation issues.
- Produces: empty/current/replace file states without changing form transport.

- [ ] **Step 1: Render empty file state**

When `field.is_file` and `not field.file.current`:
- label remains a normal form label;
- file input stays a native `<input type="file">` with the same field name;
- show `field.file.policy_hint` in `rakit-field-help`;
- preserve `accept`, `required`, `aria-describedby`, and `aria-invalid`.

- [ ] **Step 2: Render current + replace state**

When `field.file.current` exists, show before the input:

```text
<original_name>
<size_label>[ · <content_type>]
```

Label the upload control contextually as replacement, e.g. visible helper `Choose a new file to replace the current file.` The underlying field name stays unchanged; an empty native upload continues to mean “keep current file”.

Do not render stored keys or download URLs unless the existing write route already provides a separately authorized file-download capability to this template. UI-06B does not add that link.

- [ ] **Step 3: Explicitly omit a Remove button**

There must be no field-level Remove/Delete button in this baseline because the current mutation contract has no explicit clear-file operation. Record deletion/replacement cleanup policy is not presented as field clearing.

- [ ] **Step 4: Keep validation user-correctable**

Use existing field-local messages from the server (`File extension is not allowed.`, `File exceeds...`) and the existing global form summary. Do not duplicate validation in client JS.

- [ ] **Step 5: Add stable upload surface CSS only if needed**

Possible reusable class:

```css
.rakit-file-current {
  @apply rounded-rakit-sm border border-rakit-border bg-rakit-surface-subtle px-3 py-2;
}
```

Keep local spacing in Jinja utilities.

- [ ] **Step 6: Rebuild and visually inspect**

```powershell
bun run css:build
uv run ruff format --check .
uv run ruff check .
uv run ty check
```

- [ ] **Step 7: Commit file UI**

```powershell
git add packages/rakit-web/src/rakit_web/templates/forms/form.html packages/rakit-web/src/rakit_web/assets/rakit.css packages/rakit-web/src/rakit_web/static/rakit.css
git commit -m "feat(web): mature file upload fields"
```

---

### Task 6: Exercise Relationships and Uploads in `examples/ui_showcase`

**Files:**
- Modify: `examples/ui_showcase/main.py`
- Modify if deterministic records are needed: `examples/ui_showcase/data.py`

**Interfaces:**
- Consumes: existing public relationship/FileField/form APIs only.
- Produces: browser-reachable acceptance states without private CSS or private presentation hooks.

- [ ] **Step 1: Add relationship scenarios through existing public declarations**

Ensure the showcase exposes:
- TO_ONE selected;
- TO_ONE empty;
- writable TO_ONE clear/change;
- TO_MANY all-on-one-page compact state;
- TO_MANY where editor page reports previous/next and therefore renders paginated mode;
- READ_ONLY;
- INLINE or NESTED writable rows if the existing showcase mutation service supports them;
- ordered/reorderable;
- an ordering-unavailable state;
- unlink-only;
- persistent delete only where the explicit destructive policy + permission/preview runtime supports it.

Do not use a new presentation configuration to force these modes.

- [ ] **Step 2: Add a deterministic FileField write form**

Use existing public `FileField` / write-resource setup already supported by Rakit. Configure at least:

```python
FileField(
    field_id="invoice",
    label="Invoice",
    max_size=10 * 1024 * 1024,
    allowed_extensions=(".pdf",),
    allowed_mime_types=("application/pdf",),
)
```

Provide a deterministic current stored-file descriptor on one edit scenario and an empty state on create. Use development-only storage already supported by the showcase/test infrastructure; do not create a browser-only fake file object.

- [ ] **Step 3: Manually exercise the slice before adding tests**

```powershell
uv run python -m examples.ui_showcase.main
```

Browser checklist:
- compact and paginated TO_MANY switch because of actual result pagination state;
- relationship candidate search/paging remains usable;
- no-JS TO_ONE/TO_MANY submission works;
- unlink wording differs from delete wording;
- delete only where allowed;
- move up/down works without drag/drop;
- current file + replacement hint;
- file policy help is readable;
- no file Remove button;
- validation re-render keeps the previous current file visible.

- [ ] **Step 4: Commit showcase states**

```powershell
git add examples/ui_showcase/main.py examples/ui_showcase/data.py
git commit -m "feat(examples): cover relationship and upload states"
```

---

### Task 7: Add Regression Tests Last and Run the UI-06B Gate

**Files:**
- Create: `packages/rakit-web/tests/test_relationship_upload_ui_maturity.py`
- Modify existing relationship/file/form tests only for new presentation assertions.

**Interfaces:**
- Consumes: completed UI-06B behavior.
- Produces: contract coverage proving visual maturity did not change graph/storage semantics.

- [ ] **Step 1: Test result-driven adaptive relationship mode**

Directly cover the private resolver or rendered panel state:

```python
assert _relationship_presentation_mode(
    definition=to_many_link,
    has_previous=False,
    has_next=False,
) == "compact"
assert _relationship_presentation_mode(
    definition=to_many_link,
    has_previous=False,
    has_next=True,
) == "paginated"
```

Also assert INLINE/NESTED are `inline` regardless of page size so the renderer never silently changes edit semantics.

- [ ] **Step 2: Test destructive and ordering visibility boundaries**

Render panels and assert:
- unlink text exists independently of child delete;
- permanent-delete control is absent when `delete_available` is false;
- reorder controls are absent when `reorderable` is false;
- `reorder_unavailable` copy appears when the existing state provider cannot return the complete ordering state;
- hidden relationship does not render.

Keep existing graph mutation tests green; do not rewrite them around UI markup.

- [ ] **Step 3: Test safe FileField presentation**

```python
def test_file_presentation_exposes_safe_policy_not_storage_details() -> None:
    field = FileField(
        field_id="invoice",
        storage_id="private-bucket",
        prefix="orders/invoices",
        max_size=10 * 1024 * 1024,
        allowed_extensions=(".pdf",),
        allowed_mime_types=("application/pdf",),
    )
    view = file_field_presentation(field, current=None)

    assert "PDF" in view.policy_hint
    assert "10 MB" in view.policy_hint
    assert "private-bucket" not in view.policy_hint
    assert "orders/invoices" not in view.policy_hint
```

- [ ] **Step 4: Test current-file + replace semantics**

Render an update form with an existing `StoredFile` and assert:
- original filename and size are shown;
- the native upload input still has `name="invoice"`;
- there is no `name="remove_file"`, `clear_file`, or field-level Remove/Delete button;
- a failed replacement validation re-render still shows the original current file.

- [ ] **Step 5: Confirm storage lifecycle behavior is unchanged**

Run existing file upload tests covering:
- previous file preserved when no replacement uploaded;
- replacement cleanup after durable success;
- compensation after failure;
- record delete cleanup according to `delete_behavior`.

Do not change expected semantics to satisfy UI tests.

- [ ] **Step 6: Run focused relationship/upload tests**

```powershell
uv run pytest packages/rakit-web/tests/test_relationship_upload_ui_maturity.py packages/rakit-web/tests -q -k "relationship or file_upload or file_field or form"
```

If the `-k` selection is too broad, run the concrete existing relationship/file test modules discovered in the branch plus the new maturity module. Expected: PASS.

- [ ] **Step 7: Run full verification**

```powershell
bun run css:build
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
uv run mkdocs build --strict
uv run python scripts/check_artifacts.py
git status --short
```

Expected: all green; no generated CSS drift.

- [ ] **Step 8: Commit tests**

```powershell
git add packages/rakit-web/tests/test_relationship_upload_ui_maturity.py packages/rakit-web/tests
git commit -m "test(web): cover mature relationship and upload UI"
```

Before committing, inspect `git diff --cached --name-only` and unstage any unrelated existing test file; only actual new/updated relationship/file presentation tests belong in this commit.

- [ ] **Step 9: Open the UI-06B PR against `ui-06-advanced-operations`**

Require fresh PR CI and maintainer browser acceptance. Merge only into the integration branch, never directly to `main`.
