# UI-06 Integration & Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate UI-06A/B/C/D in a controlled sequence, verify the combined security/runtime/UI contract, obtain maintainer browser acceptance, and only then make the integration branch eligible for merge to `main`.

**Architecture:** `ui-06-advanced-operations` is the sole integration branch. Each child slice starts from the latest integration head, lands through a PR back to that branch, and must pass its own focused/full CI + browser acceptance first. After UI-06D lands, run one fresh deterministic matrix across actions, bulk, relationships, uploads, auth/system surfaces, custom pages, API error format, themes, mount paths, and no-JS flows. No direct feature commit or slice PR targets `main`.

**Tech Stack:** Git/GitHub PRs, Python 3.12–3.14 CI matrix, Starlette/Jinja2/HTMX/Tailwind Rakit runtime, pytest/pytest-cov, Ruff, ty, MkDocs, artifact checks, browser/manual acceptance.

**Spec:** `docs/superpowers/specs/2026-08-19-ui-06-advanced-operations-auth-system-design.md`

**Slice Plans:**
- `docs/superpowers/plans/2026-08-19-ui-06a-actions-bulk.md`
- `docs/superpowers/plans/2026-08-19-ui-06b-relationships-uploads.md`
- `docs/superpowers/plans/2026-08-19-ui-06c-auth-system-surfaces.md`
- `docs/superpowers/plans/2026-08-19-ui-06d-custom-pages-feedback.md`

## Global Constraints

- Keep `main` unchanged until all four slices are integrated and the maintainer explicitly approves the combined browser experience.
- Child branch names:
  - `ui-06a-actions-bulk`
  - `ui-06b-relationships-uploads`
  - `ui-06c-auth-system-surfaces`
  - `ui-06d-custom-pages-feedback`
- Every child branch is created from the **current integration head at the time that slice starts**, never stale `main`.
- Required order: A -> integration -> B -> integration -> C -> integration -> D -> integration. Shared templates/CSS/runtime wiring make sequential integration safer than parallel slice development.
- Feature-first/tests-last workflow applies inside each slice exactly as documented in its plan.
- A slice is not complete merely because local tests pass; its PR needs fresh GitHub PR CI and maintainer browser acceptance where visual behavior is involved.
- Do not squash away approved design/planning artifacts. Planning-doc cleanup belongs to UI-08.
- Rebuild generated CSS whenever source CSS changes; never hand-edit `static/rakit.css`.
- Do not claim push-to-main CI success if connected tooling cannot retrieve that push run. PR-triggered CI is the authoritative connected evidence available here.
- No tag, GitHub Release, TestPyPI, or PyPI action.
- `examples/reference_app` begins only after UI-06 is merged; do not smuggle it into UI-06.

---

### Task 1: Execute the Sequential Slice Branch/PR Workflow

**Files:**
- Branch/PR orchestration only.

**Interfaces:**
- Consumes: latest `ui-06-advanced-operations` head.
- Produces: one reviewed child PR at a time targeting integration.

- [ ] **Step 1: Verify integration branch before UI-06A**

```powershell
git fetch origin
git checkout ui-06-advanced-operations
git pull --ff-only origin ui-06-advanced-operations
git status --short
git rev-parse HEAD
```

Expected: clean tree. Record this SHA as UI-06A base.

- [ ] **Step 2: Create UI-06A from the exact integration head**

```powershell
git checkout -b ui-06a-actions-bulk
git push -u origin ui-06a-actions-bulk
```

Execute `2026-08-19-ui-06a-actions-bulk.md` fully.

- [ ] **Step 3: Open UI-06A PR with base `ui-06-advanced-operations`**

PR body records public Web contract, runtime/security non-goals, local verification, and browser checklist. Never target `main`.

- [ ] **Step 4: Require fresh UI-06A CI + maintainer browser acceptance**

Require green Python matrix, dependency compatibility, PR release gate, and artifact dry-run jobs before merging into integration.

- [ ] **Step 5: Refresh integration after each slice and branch the next slice from it**

After every merge:

```powershell
git checkout ui-06-advanced-operations
git pull --ff-only origin ui-06-advanced-operations
git rev-parse HEAD
git status --short
```

Then create the next branch and execute only its approved plan:

```text
UI-06A -> integration
UI-06B -> integration
UI-06C -> integration
UI-06D -> integration
```

- [ ] **Step 6: Do not start from stale pre-existing child refs**

If a named child branch already exists from an older integration head, rebase/fast-forward it to the current integration head **before implementation**. Do not resolve shared-template conflicts by dropping behavior from previous slices.

---

### Task 2: Verify Public Contract and Backward Compatibility After A/B/C/D Land

**Files:**
- Verification only unless a regression-fix child PR is required.

**Interfaces:**
- Consumes: combined integration head.
- Produces: evidence UI-06 remains additive/core-neutral.

- [ ] **Step 1: Confirm core does not depend on Web**

```powershell
git grep -n "rakit_web" -- packages/rakit-core
```

Expected: **no output**. `git grep` exits 1 when there are no matches; that exit code is expected for this check.

- [ ] **Step 2: Run public API import smoke**

```powershell
uv run python -c "from rakit import Admin, ActionDefinition, ActionIntent, ActionPresentation, ResourceWebPresentation, PageDefinition, PageWebPresentation; print('ui06-public-api-ok')"
```

Expected: `ui06-public-api-ok`.

- [ ] **Step 3: Reassert legacy construction paths**

Use existing/new tests to prove these remain valid:

```python
admin.register(MyAdmin)
admin.register(MyAdminWithFilters, web=ResourceWebPresentation(filters=...))
admin.register_page(PageDefinition(...))
admin.register_page(PageDefinition(...), actions=(... ,))
ActionDefinition(...)
PageDefinition(template="my_page.html", ...)
```

`register_page(..., web=...)` is additive and optional.

- [ ] **Step 4: Confirm no UI presentation contract leaked into core**

```powershell
git diff origin/main...HEAD -- packages/rakit-core/src/rakit_core/actions.py packages/rakit-core/src/rakit_core/relationships.py packages/rakit-core/src/rakit_core/fields.py packages/rakit-core/src/rakit_core/definitions.py
```

Expected: no UI-06 additions such as action intent, relationship presentation, upload presentation, or page-builder fields. Any unrelated diff must be explained/reviewed before continuing.

- [ ] **Step 5: Confirm custom page templates still receive raw payload**

Run UI-06D compatibility test and inspect `page_routes.py`; `payload_view` is additive while raw `payload` remains in custom-template context.

---

### Task 3: Run the Combined Automated Verification Matrix

**Files:**
- Verification only unless a dedicated integration-fix child PR is required.

**Interfaces:**
- Consumes: combined UI-06 integration head.
- Produces: fresh local evidence from exactly that SHA.

- [ ] **Step 1: Rebuild CSS and verify no generated drift**

```powershell
bun run css:build
git status --short
```

Unexpected generated CSS changes mean a slice failed to commit its build output; fix through an integration child PR before continuing.

- [ ] **Step 2: Run format/lint/type checks**

```powershell
uv run ruff format --check .
uv run ruff check .
uv run ty check
```

- [ ] **Step 3: Run all four new UI-06 maturity modules together**

```powershell
uv run pytest packages/rakit-web/tests/test_advanced_ui_maturity.py packages/rakit-web/tests/test_relationship_upload_ui_maturity.py packages/rakit-web/tests/test_auth_ui_maturity.py packages/rakit-web/tests/test_custom_page_ui_maturity.py -q
```

- [ ] **Step 4: Run the exact authoritative existing behavior suites**

```powershell
uv run pytest packages/rakit-web/tests/test_actions.py packages/rakit-web/tests/test_bulk_actions.py packages/rakit-web/tests/test_bulk_list_ui.py packages/rakit-web/tests/test_relationship_ui.py packages/rakit-web/tests/test_files.py packages/rakit-web/tests/test_write_forms.py packages/rakit-web/tests/test_resource_detail_form_ui_maturity.py packages/rakit-web/tests/test_auth_enforcement.py packages/rakit-web/tests/test_login_security.py packages/rakit-web/tests/test_csrf.py packages/rakit-web/tests/test_generated_rest_http_errors.py packages/rakit-web/tests/test_pages.py packages/rakit-web/tests/test_page_admin_runtime.py packages/rakit-web/tests/test_page_input_guardrails.py packages/rakit-web/tests/test_page_runtime_validation.py packages/rakit-web/tests/test_public_resource_composition.py packages/rakit-web/tests/test_public_page_composition.py packages/rakit-web/tests/test_resource_pages.py -q
```

Expected: PASS. These suites protect the real operation/security/runtime contracts behind the new presentation tests.

- [ ] **Step 5: Run complete repository suite**

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

- [ ] **Step 7: Record exact evidence**

Capture integration SHA, pytest pass/warning count, Ruff/ty result, MkDocs/artifact result, and clean CSS/worktree status. Do not call integration complete without fresh output from this head.

---

### Task 4: Run the Combined Browser Acceptance Matrix

**Files:**
- No changes unless a problem is found; fixes use a dedicated child PR back to integration.

**Interfaces:**
- Consumes: `examples/ui_showcase` at the combined integration SHA.
- Produces: explicit maintainer acceptance of the combined product experience.

- [ ] **Step 1: Start showcase from exact integration head**

```powershell
git rev-parse HEAD
uv run python -m examples.ui_showcase.main
```

Record SHA before review.

- [ ] **Step 2: Review Actions & Bulk together**

Verify normal/default, primary hierarchy, danger separation, HIDDEN omission where context exists, DISABLED safe reason/non-invokable state, form validation, preview/confirmation, success/rejection, bulk one/many selected, safe/danger bulk, and permission-hidden actions absent from markup.

- [ ] **Step 3: Review Relationships & Uploads together**

Verify TO_ONE current/empty/change/clear, compact and real-paginated TO_MANY, read-only/inline/nested where configured, unlink vs delete, reorder available/unavailable, current-file replacement, policy help, no field-level Remove without clear capability, and validation retaining current file.

- [ ] **Step 4: Review Auth & System surfaces**

Verify login, invalid credentials, signed-out/session-expired messages, 403, 404, Light/Dark, mounted path behavior where applicable, and production 500 using automated debug=False fixture/evidence. Auth/system pages have no admin sidebar.

- [ ] **Step 5: Review Custom Pages**

Verify scalar, flat mapping, table sequence, empty, unsupported/deep safe fallback, explicit custom template compatibility, mutating validation/rejection/redirect, and PAGE action hierarchy.

- [ ] **Step 6: Review no-JS critical flows**

Disable JavaScript and verify ordinary forms/navigation remain usable for login, action GET->POST, preview/confirmation, bulk select+submit, relationship link/unlink/reorder fallback, and mutating custom page. Enhancements may be less convenient but operations must remain possible.

- [ ] **Step 7: Review narrow + desktop widths in both themes**

UI-07 owns exhaustive responsive/a11y hardening, but UI-06 may not ship blocker-level mobile overflow/unusable action/auth/system controls.

- [ ] **Step 8: Obtain explicit combined maintainer acceptance**

Individual slice approvals do not substitute for acceptance of the final integrated SHA.

---

### Task 5: Verify Browser/API Error Separation and Security Leakage Boundaries

**Files:**
- Verification only.

**Interfaces:**
- Consumes: integrated security/error renderer.
- Produces: explicit status/format/leakage evidence.

- [ ] **Step 1: Confirm status/format matrix**

```text
browser unauthenticated protected -> 303 login
API unauthenticated               -> JSON 401
browser forbidden                 -> HTML 403
API forbidden                     -> JSON 403
browser missing after access      -> HTML 404
API missing                       -> JSON 404
browser unexpected production     -> HTML 500
API unexpected                    -> JSON 500
```

- [ ] **Step 2: Confirm unknown-route security ordering**

Anonymous unknown protected path must not get informative 404; principal lacking admin access gets 403; authorized admin-shell principal reaches normal 404.

- [ ] **Step 3: Confirm production 500 redaction**

Seed exception fixture with credential/path text; verify rendered browser/API production response excludes it and request id remains available.

- [ ] **Step 4: Confirm arbitrary login reason is never reflected**

Request encoded arbitrary `reason` input and verify it is absent from HTML.

---

### Task 6: Open Final UI-06 PR to `main` Only After Combined Approval

**Files:**
- PR metadata only.

**Interfaces:**
- Consumes: approved integration branch.
- Produces: one final UI-06 PR targeting `main`.

- [ ] **Step 1: Ensure integration is current with `main`**

```powershell
git fetch origin
git checkout ui-06-advanced-operations
git status --short
git rev-list --left-right --count origin/main...HEAD
```

If `main` advanced, update integration according to repository policy and rerun the **entire automated + browser integration matrix** before continuing.

- [ ] **Step 2: Inspect complete UI-06 diff**

```powershell
git diff --stat origin/main...HEAD
git diff --name-status origin/main...HEAD
```

Confirm expected UI-06 source/templates/tests/examples/spec/plans only; no `.env`, credentials, local files, release metadata, or unrelated refactor.

- [ ] **Step 3: Open final PR with base `main`**

PR body summarizes A/B/C/D separately and records combined SHA, local full-suite result, browser acceptance, security compatibility, and deliberate deferral of `examples/reference_app`.

- [ ] **Step 4: Require fresh final PR CI**

Use this PR-triggered CI as authoritative connected evidence for the integrated head. Require all jobs green.

- [ ] **Step 5: Do not merge automatically**

Report status/evidence to maintainer. Merge only after explicit instruction.

---

### Task 7: Post-Merge Boundary

**Files:**
- No UI-06 feature work.

**Interfaces:**
- Consumes: explicit maintainer-approved main merge.
- Produces: clean handoff to reference app.

- [ ] **Step 1: Verify local main after merge**

```powershell
git checkout main
git pull --ff-only origin main
git rev-parse HEAD
git status --short
```

- [ ] **Step 2: Do not fabricate post-merge push CI evidence**

If connected tooling cannot retrieve push-triggered runs, state only that final PR CI was green and merge completed.

- [ ] **Step 3: Start `examples/reference_app` separately**

Do not implement it inside this plan. It must consume public Rakit APIs as the realistic mini-backoffice acceptance app agreed for post-UI-06 work.

- [ ] **Step 4: Keep UI maturity spec/plans through UI-08**

Do not delete UI-06 design/planning docs during integration.
