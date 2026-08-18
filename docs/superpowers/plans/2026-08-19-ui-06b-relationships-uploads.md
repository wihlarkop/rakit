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
- Existing relationship editor page size/candidate limits remain runtime policy; UI-06B does not add a second Web threshold.
- `INLINE` / `NESTED` remain editable-row modes only when explicitly declared; `LINK` is not silently converted into an inline editor.
- `READ_ONLY` renders information only; `HIDDEN` remains absent.
- Unlink/remove membership and persistent child delete must remain visibly and semantically distinct.
- Persistent delete controls appear only when `delete_available` is true from the existing compiled policy + permission + preview/confirmation capability.
- Reorder controls appear only when `reorderable` is true. `reorder_unavailable` explains why ordering cannot be changed instead of showing fake controls.
- Drag-and-drop is optional enhancement only; the existing move-up/move-down form transport is the SSR baseline.
- Candidate search remains server-side and permission-scoped through the existing relationship helper route. Do not add browser-side full-resource filtering or an unbounded candidate fetch.
- `FileField.delete_behavior` controls cleanup when an owning record/replacement lifecycle deletes stored objects; it is **not** permission to clear a file field during edit. UI-06B must not expose a field-level “Remove file” control unless an explicit field-clear mutation capability exists. No such capability is added in this slice.
- File validation and storage remain server-authoritative; client-visible hints are explanatory only.
- Do not expose storage keys, internal paths, checksums, storage ids, or backend configuration as UI help text.
- Do not show fake upload progress.
- Edit `packages/rakit-web/src/rakit_web/assets/rakit.css`; regenerate `packages/rakit-web/src/rakit_web/static/rakit.css` with `bun run css:build`. Never hand-edit generated CSS.
- No JavaScript-only critical relationship path.
- No release/tag/PyPI action.

---

## File Map

### Create
- `packages/rakit-web/src/rakit_web/file_presentation.py` — internal Web-only safe file metadata/hint formatting; not exported as a public customization API.
- `packages/rakit-web/tests/test_relationship_upload_ui_maturity.py` — slice-level UI contract tests, created only after the feature exists.

### Modify
- `packages/rakit-web/src/rakit_web/relationship_routes.py` — add explicit result-driven presentation flags to the existing panel view; no mutation semantics changes.
- `packages/rakit-web/src/rakit_web/form_routes.py` — attach safe `FileField` policy/current-file presentation metadata to field controls.
- `packages/rakit-web/src/rakit_web/templates/relationships/panel.html`
- `packages/rakit-web/src/rakit_web/templates/relationships/to_one.html`
- `packages/rakit-web/src/rakit_web/templates/relationships/to_many.html`
- `packages/rakit-web/src/rakit_web/templates/relationships/inline_rows.html`
- `packages/rakit-web/src/rakit_web/templates/relationships/options.html`
- `packages/rakit-web/src/rakit_web/templates/relationships/error_summary.html`
- `packages/rakit-web/src/rakit_web/templates/relationships/preview_confirm.html`
- `packages/rakit-web/src/rakit_web/templates/relationships/preview_dialog.html`
- `packages/rakit-web/src/rakit_web/templates/forms/form.html` — mature file current/replace presentation.
- `packages/rakit-web/src/rakit_web/assets/rakit.css`
- `packages/rakit-web/src/rakit_web/static/rakit.css` — generated output.
- `packages/rakit-web/src/rakit_web/static/rakit-ui.js` — only if needed for non-critical disclosure/dialog polish; existing relationship state transport stays authoritative.
- `examples/ui_showcase/main.py` and `examples/ui_showcase/data.py` only as needed for deterministic states.
- Existing regression suites: `test_relationship_ui.py`, `test_files.py`, `test_write_forms.py`, `test_resource_detail_form_ui_maturity.py`.

---

### Task 1: Make Relationship Presentation State Explicit and Result-Driven

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/relationship_routes.py`

**Interfaces:**
- Consumes: existing `relationship_panel_view()` values including `rows`, `has_previous_page`, `has_next_page`, `reorderable`, `reorder_unavailable`, `delete_available`, `clear_available`, `relationship.cardinality`, and `relationship.edit_mode`.
- Produces: template-only flags `presentation_mode`, `paginated`, and `empty` while preserving all existing panel keys.

- [ ] **Step 1: Add a private presentation resolver without changing graph semantics**

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

The resolver must not inspect total count against a new UI number.

- [ ] **Step 2: Extend the panel view with presentation-only state**

Before return:

```python
presentation_mode = _relationship_presentation_mode(
    definition=definition,
    has_previous=editor_page.has_previous,
    has_next=editor_page.has_next,
)
```

Add:

```python
"presentation_mode": presentation_mode,
"paginated": bool(editor_page.has_previous or editor_page.has_next),
"empty": not bool(rows) and not bool(draft_rows),
```

Keep `rows`, `total_label`, pagination URLs, destructive flags, order values, pending inputs, concurrency token, and confirmation state unchanged.

- [ ] **Step 3: Verify the diff is presentation-only**

```powershell
uv run ruff format packages/rakit-web/src/rakit_web/relationship_routes.py
uv run ruff check packages/rakit-web/src/rakit_web/relationship_routes.py
uv run ty check
```

Inspect the diff and confirm no code inside `build_relationship_changes`, confirmation issuance/verification, authorization, or graph-mutation construction changed.

- [ ] **Step 4: Commit**

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
- Consumes: `panel.presentation_mode`, existing rows/options/selected/clear/unlink state.
- Produces: compact relationship UI preserving every existing form field name/value.

- [ ] **Step 1: Make `panel.html` a calm relationship container**

Keep hidden concurrency/pending/error inputs exactly. Visible structure:
- title + `total_label` in one header;
- concise edit/read-only context;
- semantic error summary using `rakit-alert rakit-alert-danger`;
- divider-based body rather than nested-card noise;
- pagination controls only when `panel.paginated`.

- [ ] **Step 2: Refine TO_ONE LINK**

For LINK:
- current row renders as a plain record label with Change/Clear affordances;
- empty state says no record linked yet;
- Clear only when `panel.clear_available`;
- candidate select/search keeps the existing names and encoded identity values;
- READ_ONLY shows current label/empty state with no mutation controls.

Do not reinterpret Clear as child delete. Existing destructive cascade preview/confirmation remains authoritative when relevant.

- [ ] **Step 3: Refine compact TO_MANY LINK**

When `presentation_mode == "compact"`:
- linked rows render as a divided vertical list;
- unlink control copy is `Remove from relationship` or resource-specific equivalent;
- persistent child deletion uses explicit `Delete record` wording and danger treatment only when `delete_available`;
- candidate add/connect controls stay separate from existing membership;
- pending unlink/delete intent remains visible while keeping existing form transport.

Keep names such as `unlink__<identity>`, `delete_intent__<identity>`, confirmation inputs, and link fields unchanged.

- [ ] **Step 4: Use semantic tokens only**

Replace direct slate/red/amber palette usage in touched relationship templates with Rakit semantic tokens/primitives.

- [ ] **Step 5: Template smoke check**

```powershell
uv run python -c "from rakit_web.resource_routes import build_templates; t=build_templates(()); [t.env.get_template(p) for p in ('relationships/panel.html','relationships/to_one.html','relationships/to_many.html')]"
uv run ruff format --check .
uv run ruff check .
```

- [ ] **Step 6: Commit**

```powershell
git add packages/rakit-web/src/rakit_web/templates/relationships/panel.html packages/rakit-web/src/rakit_web/templates/relationships/to_one.html packages/rakit-web/src/rakit_web/templates/relationships/to_many.html packages/rakit-web/src/rakit_web/templates/relationships/error_summary.html
git commit -m "feat(web): refine compact relationship editors"
```

---

### Task 3: Mature Paginated, Inline/Nested, Ordering, and Destructive States

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/templates/relationships/to_many.html`
- Modify: `packages/rakit-web/src/rakit_web/templates/relationships/inline_rows.html`
- Modify: `packages/rakit-web/src/rakit_web/templates/relationships/options.html`
- Modify: `packages/rakit-web/src/rakit_web/templates/relationships/preview_confirm.html`
- Modify: `packages/rakit-web/src/rakit_web/templates/relationships/preview_dialog.html`
- Modify: `packages/rakit-web/src/rakit_web/assets/rakit.css`
- Regenerate: `packages/rakit-web/src/rakit_web/static/rakit.css`

**Interfaces:**
- Consumes: existing page/rows/reorder/destructive/preview state.
- Produces: scalable server-paginated relationship UI with accessible ordering fallback.

- [ ] **Step 1: Render paginated TO_MANY from real editor pagination state**

When `presentation_mode == "paginated"`, render current linked members as a semantic table/divided list plus server Previous/Next controls using the existing `page_path`. Do not add browser-local pagination or fetch the entire relationship client-side.

- [ ] **Step 2: Keep candidate discovery bounded and server-scoped**

Refine `options.html` presentation only. Continue using the existing `/options` helper, encoded identity values, selected state, query parameter, and bounded server candidate page. UI-06B does not add a new candidate pagination protocol.

- [ ] **Step 3: Refine INLINE/NESTED rows without converting modes**

Preserve create/update/association input names, row validation, add-row capability checks, and target update permissions. Do not introduce deeper recursion or another nested data model.

- [ ] **Step 4: Make ordering accessible and capability-bound**

If `panel.reorderable`, retain hidden `order__NNNN` values and provide native Move up/Move down submit controls through the existing `move__<identity>__up|down` transport. Drag/drop is optional and not required.

If `panel.reorder_unavailable`, show neutral explanatory text and no fake move controls.

- [ ] **Step 5: Mature destructive confirmation copy**

`preview_confirm.html` / `preview_dialog.html` distinguish relationship removal from persistent child deletion. Keep confirmation tokens/intents/impact fields and data attributes unchanged.

- [ ] **Step 6: Add only reusable CSS, rebuild, verify**

```powershell
bun run css:build
uv run ruff format --check .
uv run ruff check .
uv run ty check
```

- [ ] **Step 7: Commit**

```powershell
git add packages/rakit-web/src/rakit_web/templates/relationships packages/rakit-web/src/rakit_web/assets/rakit.css packages/rakit-web/src/rakit_web/static/rakit.css
git commit -m "feat(web): mature advanced relationship states"
```

---

### Task 4: Add Safe File-Field Presentation Metadata

**Files:**
- Create: `packages/rakit-web/src/rakit_web/file_presentation.py`
- Modify: `packages/rakit-web/src/rakit_web/form_routes.py`
- Reuse unchanged lifecycle helpers in: `packages/rakit-web/src/rakit_web/file_uploads.py`

**Interfaces:**
- Consumes: `FileField`, `StoredFile`, `record_stored_file()`, current update record.
- Produces: safe internal metadata for the Jinja form control.

- [ ] **Step 1: Create internal immutable file presentation types**

```python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CurrentFilePresentation:
    name: str
    size_label: str
    content_type: str


@dataclass(frozen=True, slots=True)
class FileFieldPresentation:
    accept: str
    policy_hint: str
    current: CurrentFilePresentation | None = None
```

Do not export them through `rakit`.

- [ ] **Step 2: Add deterministic file-size formatting**

Use one internal formatter for B/KB/MB and strip unnecessary `.0` consistently.

- [ ] **Step 3: Build only safe policy hints**

`file_field_presentation(field, current)` may expose:
- human-readable allowed extension labels;
- MIME wording only when useful;
- maximum size;
- a filename-length hint only when materially constrained;
- current original filename, content type, and size.

Never expose `storage_id`, `prefix`, stored `key`, `checksum`, or metadata.

- [ ] **Step 4: Pass actual current stored file separately from submitted display values**

Extend `_form_response(..., current_record: object | None = None)`.

For every `FileField`, use existing `record_stored_file(current_record, field)` and include a `file` presentation value in the control mapping. `update_get` passes the loaded record. Update validation re-renders pass the same previously loaded record so a failed replacement still shows the current file. Create routes pass no current record.

- [ ] **Step 5: Explicitly do not add a clear/delete field transport**

Do not add names such as `delete_file`, `clear_file`, or `remove_file`, and do not reinterpret an empty upload as deletion. Existing `prepare_file_submission()` keeps the previous file when no replacement is uploaded; that behavior remains unchanged.

- [ ] **Step 6: Verify and commit**

```powershell
uv run ruff format packages/rakit-web/src/rakit_web/file_presentation.py packages/rakit-web/src/rakit_web/form_routes.py
uv run ruff check packages/rakit-web/src/rakit_web/file_presentation.py packages/rakit-web/src/rakit_web/form_routes.py
uv run ty check
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
- Consumes: `field.file.current`, `field.file.policy_hint`, existing file input metadata/issues.
- Produces: empty/current/replace file states without changing form transport.

- [ ] **Step 1: Render empty file state**

Keep the native `<input type="file">` field name, `accept`, required state, `aria-describedby`, and `aria-invalid`; show policy hint as field help.

- [ ] **Step 2: Render current + replace state**

Show current `original_name`, formatted size, and content type. Keep the same native file input and explain that choosing a new file replaces the current one. Empty submission still means keep current.

- [ ] **Step 3: Explicitly omit a field-level Remove button**

No Remove/Delete control appears because the write contract has no explicit file-clear mutation.

- [ ] **Step 4: Keep validation server-authoritative**

Render existing server field issues; do not duplicate upload validation in JS.

- [ ] **Step 5: Add only stable CSS, rebuild, verify**

```powershell
bun run css:build
uv run ruff format --check .
uv run ruff check .
uv run ty check
```

- [ ] **Step 6: Commit**

```powershell
git add packages/rakit-web/src/rakit_web/templates/forms/form.html packages/rakit-web/src/rakit_web/assets/rakit.css packages/rakit-web/src/rakit_web/static/rakit.css
git commit -m "feat(web): mature file upload fields"
```

---

### Task 6: Exercise Relationships and Uploads in `examples/ui_showcase`

**Files:**
- Modify: `examples/ui_showcase/main.py`
- Modify if needed: `examples/ui_showcase/data.py`

**Interfaces:**
- Consumes: existing public relationship/FileField/form APIs only.
- Produces: deterministic browser acceptance states without private UI hooks.

- [ ] **Step 1: Add relationship scenarios through existing public declarations/runtime**

Exercise:
- TO_ONE selected and empty;
- writable TO_ONE change/clear;
- compact TO_MANY whose linked result fits one editor page;
- paginated TO_MANY where the actual editor result reports previous/next;
- READ_ONLY;
- INLINE/NESTED only if the existing graph mutation fixture supports them;
- reorderable and reorder-unavailable;
- unlink-only;
- persistent delete only where explicit destructive policy + permission/preview runtime permits it.

- [ ] **Step 2: Add a deterministic FileField write form**

Use public `FileField` and the existing development storage/test infrastructure, with a representative PDF field such as 10 MB max. Provide one edit scenario with an actual `StoredFile` descriptor and one create/empty scenario. Do not fake current-file metadata only in the template.

- [ ] **Step 3: Manual browser review before tests**

```powershell
uv run python -m examples.ui_showcase.main
```

Verify compact/paginated switching is result-driven, no-JS relationship submission works, unlink/delete wording differs, move up/down works without drag/drop, current-file replacement is clear, policy help is readable, no field Remove button appears, and validation re-render retains current-file context.

- [ ] **Step 4: Commit**

```powershell
git add examples/ui_showcase/main.py examples/ui_showcase/data.py
git commit -m "feat(examples): cover relationship and upload states"
```

Only stage `data.py` if it changed.

---

### Task 7: Add Regression Tests Last and Run the UI-06B Gate

**Files:**
- Create: `packages/rakit-web/tests/test_relationship_upload_ui_maturity.py`
- Modify existing relationship/file/form suites only when needed for new presentation assertions.

**Interfaces:**
- Consumes: completed UI-06B behavior.
- Produces: durable graph/storage/presentation regression coverage.

- [ ] **Step 1: Test result-driven adaptive relationship mode**

Cover compact vs paginated from `has_previous/has_next`, and prove INLINE/NESTED remain inline regardless of pagination state.

- [ ] **Step 2: Test destructive and ordering visibility boundaries**

Assert unlink exists independently of persistent delete, delete control is absent when `delete_available` is false, reorder controls are absent when `reorderable` is false, unavailable-ordering copy is shown when appropriate, and HIDDEN relationship panels are absent.

- [ ] **Step 3: Test safe FileField presentation**

Construct a `FileField` with non-public `storage_id`/`prefix` and assert the presentation contains user-safe extension/size information but never storage id/prefix/key/checksum.

- [ ] **Step 4: Test current-file + replace semantics**

Render an update form with a real `StoredFile` and assert filename/size/type are visible, the native field name is unchanged, no file-clear transport/button exists, and a failed replacement validation re-render keeps the old current file visible.

- [ ] **Step 5: Reassert existing storage lifecycle semantics**

Do not alter expectations for no-replacement preservation, replacement cleanup after durable success, failed-upload compensation, or owning-record delete cleanup according to `delete_behavior`.

- [ ] **Step 6: Run the exact focused suite**

```powershell
uv run pytest packages/rakit-web/tests/test_relationship_upload_ui_maturity.py packages/rakit-web/tests/test_relationship_ui.py packages/rakit-web/tests/test_files.py packages/rakit-web/tests/test_write_forms.py packages/rakit-web/tests/test_resource_detail_form_ui_maturity.py -q
```

Expected: PASS.

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

- [ ] **Step 8: Commit tests**

```powershell
git add packages/rakit-web/tests/test_relationship_upload_ui_maturity.py packages/rakit-web/tests/test_relationship_ui.py packages/rakit-web/tests/test_files.py packages/rakit-web/tests/test_write_forms.py packages/rakit-web/tests/test_resource_detail_form_ui_maturity.py
git commit -m "test(web): cover mature relationship and upload UI"
```

Only stage existing files that actually changed.

- [ ] **Step 9: Open UI-06B PR against `ui-06-advanced-operations`**

Require fresh PR CI and maintainer browser acceptance. Merge only into the integration branch, never directly to `main`.
