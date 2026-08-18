# UI-06 Integration & Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate UI-06A/B/C/D in a controlled sequence, verify the combined security/runtime/UI contract, obtain maintainer browser acceptance, and only then make the integration branch eligible for merge to `main`.

**Architecture:** `ui-06-advanced-operations` is the sole integration branch. Each child slice starts from the latest integration head, lands through a PR back to that branch, and must pass its own focused/full CI + browser acceptance first. After UI-06D lands, run a fresh combined matrix across actions, bulk, relationships, uploads, auth/system surfaces, custom pages, API error format, themes, mount paths, and no-JS flows. No direct feature commit or slice PR targets `main`.

**Tech Stack:** Git/GitHub PRs, Python 3.12–3.14 CI matrix, Starlette/Jinja2/HTMX/Tailwind Rakit runtime, pytest/pytest-cov, Ruff, ty, MkDocs, artifact checks, browser/manual acceptance.

**Spec:** `docs/superpowers/specs/2026-08-19-ui-06-advanced-operations-auth-system-design.md`

**Slice Plans:**
- `docs/superpowers/plans/2026-08-19-ui-06a-actions-bulk.md`
- `docs/superpowers/plans/2026-08-19-ui-06b-relationships-uploads.md`
- `docs/superpowers/plans/2026-08-19-ui-06c-auth-system-surfaces.md`
- `docs/superpowers/plans/2026-08-19-ui-06d-custom-pages-feedback.md`

## Global Constraints

- Keep `main` unchanged until all four slices are integrated and the maintainer explicitly approves the combined browser experience.
- Child branch names are fixed for the plan:
  - `ui-06a-actions-bulk`
  - `ui-06b-relationships-uploads`
  - `ui-06c-auth-system-surfaces`
  - `ui-06d-custom-pages-feedback`
- Every child branch is created from the **current integration head at the time work starts**, never from stale `main`.
- UI-06B starts only after UI-06A is merged into integration; UI-06C after B; UI-06D after C. This avoids parallel presentation/runtime conflicts in shared templates/CSS.
- Feature-first/tests-last workflow applies inside each slice exactly as documented in its plan.
- A slice is not complete merely because local tests pass; its PR must receive fresh GitHub CI and maintainer browser acceptance where visual behavior is involved.
- Do not squash away planning/spec artifacts. Keep the approved design spec and UI-06 plans in the branch through implementation; final planning-doc cleanup belongs to UI-08.
- Generated CSS must be rebuilt from source and committed whenever source CSS changes.
- Never hand-edit generated `static/rakit.css`.
- Do not use `main` push CI as evidence if the connected GitHub tooling cannot retrieve that push run. PR-triggered CI is the authoritative connected evidence.
- No tag, GitHub Release, TestPyPI, or PyPI action.
- After UI-06 merges to `main`, `examples/reference_app` is a separate follow-up. Do not smuggle it into UI-06 integration.

---

### Task 1: Establish the Sequential Slice Branch Workflow

**Files:**
- No product files; branch/PR orchestration only.

**Interfaces:**
- Consumes: latest `ui-06-advanced-operations` head.
- Produces: one child branch at a time targeting the integration branch.

- [ ] **Step 1: Verify integration branch is current and clean before UI-06A**

Local workflow:

```powershell
git fetch origin
git checkout ui-06-advanced-operations
git pull --ff-only origin ui-06-advanced-operations
git status --short
git rev-parse HEAD
```

Expected: clean working tree. Record the HEAD used as UI-06A base.

- [ ] **Step 2: Create UI-06A child branch from that exact integration head**

```powershell
git checkout -b ui-06a-actions-bulk
git push -u origin ui-06a-actions-bulk
```

Execute `2026-08-19-ui-06a-actions-bulk.md` completely.

- [ ] **Step 3: Open UI-06A PR with base `ui-06-advanced-operations`**

PR body must summarize:
- public Web presentation contract added;
- action/bulk UI states exercised;
- security/runtime semantics intentionally unchanged;
- focused/full local verification evidence;
- browser acceptance checklist.

Do not target `main`.

- [ ] **Step 4: Require fresh UI-06A CI and maintainer visual approval before merge**

Minimum connected evidence:
- Python test matrix green;
- dependency compatibility green;
- PR release gate green;
- artifact dry run green.

Then merge PR into `ui-06-advanced-operations` only.

- [ ] **Step 5: Repeat from the new integration head for B, C, D**

After each merge:

```powershell
git checkout ui-06-advanced-operations
git pull --ff-only origin ui-06-advanced-operations
git rev-parse HEAD
```

Then create the next child branch from that head and execute only its approved plan.

The required order is:

```text
UI-06A -> integration
UI-06B -> integration
UI-06C -> integration
UI-06D -> integration
```

- [ ] **Step 6: Do not reuse stale child branches**

If a child branch already exists but was created before the preceding slice merged, rebase/fast-forward it onto the latest integration branch before implementation begins. Never resolve shared-template conflicts by silently dropping prior slice behavior.

---

### Task 2: Verify Public Contract and Backward Compatibility After All Four Slices Land

**Files:**
- Verification only unless a regression fix is required; any fix must be made on a dedicated integration-fix child branch/PR, not directly on `main`.

**Interfaces:**
- Consumes: combined integration head.
- Produces: evidence that UI-06 is additive and core-neutral.

- [ ] **Step 1: Confirm `rakit-core` has no Web dependency**

```powershell
rg "rakit_web" packages/rakit-core
```

Expected: no production import from `rakit-core` to `rakit_web`.

- [ ] **Step 2: Run a public API import smoke**

```powershell
uv run python -c "from rakit import Admin, ActionDefinition, ActionIntent, ActionPresentation, ResourceWebPresentation, PageDefinition, PageWebPresentation; print('ui06-public-api-ok')"
```

Expected: `ui06-public-api-ok`.

- [ ] **Step 3: Verify legacy construction paths**

Use a tiny script or existing tests to prove all remain valid:

```python
admin.register(MyAdmin)
admin.register(MyAdminWithFilters, web=ResourceWebPresentation(filters=...))
admin.register_page(PageDefinition(...))
admin.register_page(PageDefinition(...), actions=(... ,))
ActionDefinition(...)
PageDefinition(template="my_page.html", ...)
```

The new `web=` page parameter is optional.

- [ ] **Step 4: Confirm no new core presentation fields**

Inspect:

```powershell
git diff main...ui-06-advanced-operations -- packages/rakit-core/src/rakit_core/actions.py packages/rakit-core/src/rakit_core/relationships.py packages/rakit-core/src/rakit_core/fields.py packages/rakit-core/src/rakit_core/definitions.py
```

Expected: no UI-06 change adding action intent, relationship presentation, file presentation, or page-builder fields to core. If an unrelated conflict changed these files, review it explicitly before continuing.

- [ ] **Step 5: Confirm custom templates still receive raw page payload**

Run the UI-06D compatibility test and inspect page context code. The default page may use `payload_view`, but `payload` must remain present for explicit custom templates.

---

### Task 3: Run the Combined Automated Verification Matrix

**Files:**
- Verification only unless regression fix PR is required.

**Interfaces:**
- Consumes: integrated UI-06 application.
- Produces: fresh local evidence before final PR/main consideration.

- [ ] **Step 1: Rebuild CSS from source and verify no drift**

```powershell
bun run css:build
git status --short
```

If `static/rakit.css` changes unexpectedly, determine whether source CSS was not rebuilt in a slice. Commit the generated update through an integration-fix PR before proceeding.

- [ ] **Step 2: Run formatting, linting, and typing**

```powershell
uv run ruff format --check .
uv run ruff check .
uv run ty check
```

Expected: all clean.

- [ ] **Step 3: Run focused UI-06 maturity modules together**

```powershell
uv run pytest packages/rakit-web/tests/test_advanced_ui_maturity.py packages/rakit-web/tests/test_relationship_upload_ui_maturity.py packages/rakit-web/tests/test_auth_ui_maturity.py packages/rakit-web/tests/test_custom_page_ui_maturity.py -q
```

Expected: PASS.

- [ ] **Step 4: Run authoritative behavior suites together**

At minimum include existing modules for:
- actions;
- bulk actions/list selection;
- relationship routes/forms/graph mutation;
- file uploads/forms;
- authentication/CSRF/session enforcement;
- pages/page guardrails;
- resource runtime;
- generated API error contracts.

Use discovered concrete test module names from the branch. Do not rely only on maturity/markup tests.

- [ ] **Step 5: Run the complete repository suite**

```powershell
uv run pytest
```

Expected: PASS with only already-known warnings.

- [ ] **Step 6: Run release/documentation/artifact checks**

```powershell
uv run pytest --cov
uv run mkdocs build --strict
uv run python scripts/check_artifacts.py
```

Expected: PASS.

- [ ] **Step 7: Record exact verification evidence**

Capture:
- integration commit SHA;
- total pytest pass count/warnings;
- Ruff/ty result;
- MkDocs/artifact result;
- CSS clean status.

Do not describe the integration as complete without fresh output from this head.

---

### Task 4: Run the Combined Browser Acceptance Matrix

**Files:**
- No code changes unless an issue is found. Fixes go through a dedicated child PR back to integration.

**Interfaces:**
- Consumes: `examples/ui_showcase` running from the combined integration head.
- Produces: maintainer acceptance across the complete user journey.

- [ ] **Step 1: Start the showcase from the exact integration head**

```powershell
uv run python -m examples.ui_showcase.main
```

Record the SHA shown by `git rev-parse HEAD` before review.

- [ ] **Step 2: Review Actions & Bulk together**

Verify:
- normal/default action;
- primary hierarchy if configured;
- danger action separated visually;
- disabled availability + safe reason;
- form validation;
- preview/confirmation;
- success/rejection;
- one selected vs many selected bulk state;
- safe vs danger bulk action;
- no action hidden by permission becomes exposed in overflow markup.

- [ ] **Step 3: Review Relationships & Uploads together**

Verify:
- TO_ONE current/empty/change/clear;
- compact TO_MANY;
- result-driven paginated TO_MANY;
- read-only;
- inline/nested if present;
- unlink vs delete wording/treatment;
- reorder available/unavailable;
- current file + replace;
- file policy help;
- no field-level file Remove button without explicit clear capability;
- validation keeps current file visible.

- [ ] **Step 4: Review Auth & System surfaces**

Verify:
- login normal;
- invalid credentials;
- signed-out message;
- session-expired message;
- 403;
- 404;
- production 500 using test fixture/evidence;
- no sidebar on auth/system pages;
- Light and Dark theme control works;
- mounted paths are correct where tested.

- [ ] **Step 5: Review Custom Pages**

Verify:
- scalar;
- flat mapping;
- table-like sequence;
- empty;
- unsupported/deep safe fallback;
- explicit custom template still works;
- mutating page validation/rejection/redirect;
- PAGE actions use the same hierarchy.

- [ ] **Step 6: Review no-JS critical flows**

Disable JavaScript and verify ordinary navigation/forms remain usable for:
- login;
- resource/action GET -> POST flow;
- action preview/confirmation;
- bulk selection/action form;
- relationship link/unlink/reorder fallback;
- mutating custom page.

HTMX/dialog/selection enhancements may be less convenient without JS, but the operation must not become impossible solely because enhancement is absent.

- [ ] **Step 7: Review narrow viewport and both themes**

UI-07 owns exhaustive responsive/a11y hardening, but UI-06 integration must have no blocker-level mobile overflow or unusable auth/system/action controls. Check at least one narrow phone-like viewport and one desktop viewport in Light/Dark.

- [ ] **Step 8: Maintainer records explicit combined acceptance**

Do not infer acceptance from individual slice approvals. The maintainer must review the combined integration head and explicitly approve it before main merge.

---

### Task 5: Verify Browser/API Error Separation and Security Leakage Boundaries

**Files:**
- Verification only.

**Interfaces:**
- Consumes: integrated authorization/error renderer.
- Produces: explicit security acceptance evidence.

- [ ] **Step 1: Run the browser/API status-format matrix**

Confirm:

```text
browser unauthenticated protected -> 303 login
API unauthenticated              -> JSON 401
browser forbidden                -> HTML 403
API forbidden                    -> JSON 403
browser missing after access     -> HTML 404
API missing                      -> JSON 404
browser unexpected production    -> HTML 500
API unexpected                   -> JSON 500
```

- [ ] **Step 2: Confirm security ordering for unknown routes**

Use the tests/browser fixture to prove:
- anonymous unknown protected path does not get informative 404;
- principal without admin access gets 403, not route information;
- only an authorized admin-shell principal reaches the normal 404 surface.

- [ ] **Step 3: Confirm 500 redaction**

Search the rendered production 500 fixture response for seeded exception secrets/path text and verify absence. Confirm request id remains present.

- [ ] **Step 4: Confirm unknown login reason cannot reflect user input**

Request an arbitrary encoded `reason` value and ensure it is absent from rendered HTML.

---

### Task 6: Open the UI-06 Integration PR to `main` Only After Local/Browser Approval

**Files:**
- PR metadata only.

**Interfaces:**
- Consumes: approved, fully integrated branch.
- Produces: one final UI-06 PR targeting `main`.

- [ ] **Step 1: Confirm integration branch is not behind `main`**

```powershell
git fetch origin
git checkout ui-06-advanced-operations
git status --short
git rev-list --left-right --count origin/main...HEAD
```

If `main` advanced during UI-06, rebase/merge according to repository policy, rerun the **entire** automated + browser integration matrix, and only then continue.

- [ ] **Step 2: Compare the complete UI-06 diff**

```powershell
git diff --stat origin/main...HEAD
git diff --name-status origin/main...HEAD
```

Confirm:
- expected UI-06 source/templates/tests/examples/plans/spec only;
- no `.env`, credentials, local files, release metadata, or unrelated refactor;
- planning/spec docs remain present.

- [ ] **Step 3: Open final PR with base `main`**

PR description must summarize four slices separately and include:
- combined integration SHA;
- local full-suite result;
- CI expectations;
- browser acceptance statement;
- explicit security compatibility notes;
- note that `examples/reference_app` is intentionally deferred until after UI-06.

- [ ] **Step 4: Require fresh final PR CI**

Because CI is PR-triggered, use this final PR as authoritative connected evidence for the integrated head. Require all jobs green before considering merge.

- [ ] **Step 5: Do not merge automatically**

Report the final PR status and evidence to the maintainer. Merge to `main` only after the maintainer explicitly says to merge.

---

### Task 7: Post-Merge Boundary

**Files:**
- No UI-06 code changes.

**Interfaces:**
- Consumes: maintainer-approved main merge.
- Produces: clean handoff to the next project step.

- [ ] **Step 1: Verify main points at the merged UI-06 commit**

After an explicit merge instruction and merge completion:

```powershell
git checkout main
git pull --ff-only origin main
git rev-parse HEAD
git status --short
```

- [ ] **Step 2: Do not claim push-to-main CI success without retrievable evidence**

If connected tooling cannot retrieve push-triggered runs, state only that the final PR CI was green and that the merge completed. Do not fabricate post-merge CI evidence.

- [ ] **Step 3: Start `examples/reference_app` as a separate architectural/bounded workflow**

Do not implement it as part of this plan. Its approved purpose is to consume only public Rakit APIs for a realistic mini backoffice, then serve as a second acceptance target for UI-07/UI-08.

- [ ] **Step 4: Keep all UI maturity planning/spec docs until UI-08**

No cleanup/deletion of UI-06 spec/plans during this integration.
