# UI-07 Responsive & Accessibility Hardening Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate UI-07A/B/C serially, verify the combined responsive/accessibility contract, obtain maintainer browser acceptance, and only then merge UI-07 to `main`.

**Architecture:** `ui-07-responsive-a11y-hardening` is the sole integration branch. Each child slice starts from the latest epic head and lands through a PR back to the epic. Browser acceptance is intentionally combined at the end; every child still requires structural review, regression coverage, and fresh full CI before integration.

**Tech Stack:** Python 3.12–3.14, Starlette/Jinja2/HTMX, Tailwind CSS v4, Bun asset build, pytest/pytest-cov, Ruff, ty, MkDocs, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-19-ui-07-ui-08-phase-a-hardening-design.md`

**Slice plans:**
- `docs/superpowers/plans/2026-08-19-ui-07a-responsive-overflow.md`
- `docs/superpowers/plans/2026-08-19-ui-07b-keyboard-focus-semantics.md`
- `docs/superpowers/plans/2026-08-19-ui-07c-contrast-motion-copy.md`

## Global Constraints

- `main` remains unchanged until combined UI-07 browser acceptance succeeds.
- Child sequence is strictly 07A -> epic -> 07B -> epic -> 07C -> epic.
- Every later child starts from the current epic head, never stale `main` or a sibling branch.
- Maintainer workflow is source first, structural/non-test review second, regression tests last, then focused/full verification.
- No Playwright, axe-core, cross-browser automation, or visual-regression infrastructure in UI-07.
- No business capability, adapter, CLI, generated API, reference app, release tag, GitHub Release, TestPyPI, or PyPI work.
- Rebuild `packages/rakit-web/src/rakit_web/static/rakit.css` whenever maintainer CSS changes.
- Existing security/runtime semantics remain authoritative.

---

### Task 1: Integrate UI-07A

**Files:** branch/PR orchestration plus files owned by the UI-07A slice plan.

**Interfaces:**
- Consumes: exact current `ui-07-responsive-a11y-hardening` head.
- Produces: responsive/overflow-hardened epic head.

- [ ] **Step 1: Record epic base**

Fetch the epic ref and record its exact SHA. Confirm the spec and all UI-07 plan documents exist on that SHA.

- [ ] **Step 2: Create `ui-07a-responsive-overflow` from that exact SHA**

No source change is made on the epic branch itself.

- [ ] **Step 3: Execute the UI-07A plan completely**

Follow the source-first/tests-last order in the slice plan.

- [ ] **Step 4: Open a child PR targeting `ui-07-responsive-a11y-hardening`**

PR body records responsive surfaces touched, non-goals, structural review findings, focused verification, full CI, and generated CSS status.

- [ ] **Step 5: Require fresh full CI on the exact child head**

Require Python 3.12/3.13/3.14 tests, Ruff format/check, ty, dependency suites, coverage/release gate, MkDocs, artifact checks, and artifact dry run where configured.

- [ ] **Step 6: Merge only to the epic branch**

Do not merge UI-07A to `main`.

---

### Task 2: Integrate UI-07B

**Files:** branch/PR orchestration plus files owned by the UI-07B slice plan.

**Interfaces:**
- Consumes: epic head after UI-07A merge.
- Produces: responsive + keyboard/focus/semantic-hardened epic head.

- [ ] **Step 1: Refresh epic and record the new SHA**

Confirm the UI-07A merge is present and `main` is still unchanged.

- [ ] **Step 2: Create `ui-07b-keyboard-focus-semantics` from the refreshed epic SHA**

- [ ] **Step 3: Execute the UI-07B plan completely**

- [ ] **Step 4: Open a child PR targeting the epic branch**

- [ ] **Step 5: Require fresh full CI on the exact child head**

- [ ] **Step 6: Merge only to the epic branch**

---

### Task 3: Integrate UI-07C

**Files:** branch/PR orchestration plus files owned by the UI-07C slice plan.

**Interfaces:**
- Consumes: epic head after UI-07B merge.
- Produces: complete UI-07 combined tree.

- [ ] **Step 1: Refresh epic and record the new SHA**

- [ ] **Step 2: Create `ui-07c-contrast-motion-copy` from the refreshed epic SHA**

- [ ] **Step 3: Execute the UI-07C plan completely**

- [ ] **Step 4: Open a child PR targeting the epic branch**

- [ ] **Step 5: Require fresh full CI on the exact child head**

- [ ] **Step 6: Merge only to the epic branch**

---

### Task 4: Run Combined Automated Verification

**Files:** verification only unless a dedicated `ui-07-polish-*` child branch is required.

**Interfaces:**
- Consumes: epic head containing 07A/B/C.
- Produces: fresh evidence from exactly that combined tree.

- [ ] **Step 1: Verify generated CSS is synchronized**

Run the CSS build from the exact combined tree and confirm no uncommitted generated drift.

- [ ] **Step 2: Run quality checks**

```powershell
uv run ruff format --check .
uv run ruff check .
uv run ty check
```

- [ ] **Step 3: Run UI-07 focused contracts together**

Run the accessibility contract suite plus the new responsive and keyboard/focus/contrast-motion contract modules created by the slice plans.

- [ ] **Step 4: Run all authoritative `rakit-web` behavior/security tests**

```powershell
uv run pytest packages/rakit-web/tests -q
```

- [ ] **Step 5: Run complete repository tests and release-sensitive checks**

```powershell
uv run pytest
uv run pytest --cov
uv run mkdocs build --strict
uv run python scripts/check_artifacts.py
```

- [ ] **Step 6: Obtain fresh GitHub CI evidence for the combined tree**

If a PR-triggered run is needed to obtain authoritative connected CI, create a no-product-change CI trigger only when necessary and remove any helper before final integration. Prefer normal PR CI from an actual polish/final PR whenever available.

---

### Task 5: Combined Browser Acceptance

**Files:** no changes unless a defect is found.

**Interfaces:**
- Consumes: exact combined UI-07 epic SHA.
- Produces: explicit maintainer acceptance or a bounded polish backlog.

- [ ] **Step 1: Start `examples.ui_showcase` from the exact epic head**

Record the SHA before testing.

- [ ] **Step 2: Responsive matrix**

For shell/navigation, dashboard, list, detail, form, delete confirmation, record actions, bulk actions, relationships, uploads, login/system pages, custom pages, and UI Lab, inspect approximately 1440, 1024, 768, and 390 CSS-pixel widths.

Acceptance rules:
- no accidental document-level horizontal scroll;
- no clipped critical controls;
- no action collisions;
- wide tables scroll inside their own region;
- mobile/tablet layouts remain readable and operable.

- [ ] **Step 3: Keyboard/focus matrix**

Exercise skip link, navigation, theme chooser, search/filter, selection/select-all, row/record actions, dialogs/popovers, forms, relationship controls, submit/cancel, and focus return without relying on a pointer.

- [ ] **Step 4: Contrast/motion/copy matrix**

Inspect light and dark themes; verify status meaning is textual, focus is visible, reduced-motion behavior remains understandable, and destructive/error/session copy is explicit.

- [ ] **Step 5: No-JS critical flow spot check**

Verify representative login, form mutation, destructive confirmation, bulk action, relationship mutation, and custom-page mutation remain operable without JavaScript.

- [ ] **Step 6: Record maintainer result**

If findings exist, create a dedicated `ui-07-polish-*` child branch from the current epic head. Never patch the epic directly.

---

### Task 6: Polish Loop When Findings Exist

**Files:** only files required for accepted browser findings.

**Interfaces:**
- Consumes: concrete maintainer acceptance findings.
- Produces: corrected epic tree with fresh CI.

- [ ] **Step 1: Create a bounded polish child branch from the exact epic head**

- [ ] **Step 2: Implement only reported findings using source-first/tests-last**

- [ ] **Step 3: Add regression contracts for semantic/behavioral regressions**

- [ ] **Step 4: Require fresh full CI and merge back to epic**

- [ ] **Step 5: Repeat only the affected browser paths plus a quick whole-matrix sanity pass**

---

### Task 7: Final UI-07 PR to `main`

**Files:** PR metadata only.

**Interfaces:**
- Consumes: combined epic tree explicitly accepted by the maintainer.
- Produces: one final UI-07 PR targeting `main`.

- [ ] **Step 1: Confirm `main` has not advanced unexpectedly**

Compare `main` and the epic. If `main` advanced after UI-07 started, update the epic according to repository policy and rerun the combined automated/browser acceptance matrix before continuing.

- [ ] **Step 2: Inspect the complete UI-07 diff**

Confirm only expected UI/accessibility/docs/tests/planning changes are present; no unrelated feature or release metadata is included.

- [ ] **Step 3: Open `ui-07-responsive-a11y-hardening -> main`**

PR body records slice summaries, exact combined SHA, automated evidence, maintainer browser acceptance, accessibility guarantees, deferred automation, and non-goals.

- [ ] **Step 4: Require fresh final PR CI on the exact integrated head**

- [ ] **Step 5: Wait for explicit maintainer merge instruction**

Do not merge automatically.

---

### Task 8: UI-07 Post-Merge Boundary

**Files:** no UI-08 product change yet.

**Interfaces:**
- Consumes: maintainer-approved UI-07 merge to `main`.
- Produces: clean starting point for UI-08 audit.

- [ ] **Step 1: Verify `main` points to the UI-07 merge commit**

- [ ] **Step 2: Verify the merged tree matches the accepted/tested UI-07 tree**

- [ ] **Step 3: Begin UI-08 design/audit plan from that exact `main` state**

UI-08 findings must be derived from the final UI-07 product, not guessed in advance.
