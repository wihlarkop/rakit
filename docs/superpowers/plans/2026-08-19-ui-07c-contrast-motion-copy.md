# UI-07C Contrast, Motion, Copy, and Accessibility Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish UI-07 by hardening light/dark contrast, reduced-motion behavior, pending/loading communication, consequential UX copy, and the accuracy of Rakit's accessibility documentation.

**Architecture:** Use semantic Rakit design tokens and existing feedback primitives rather than one-off color fixes. Reduced-motion is implemented as a shared CSS/interaction policy; copy changes remain presentation-only and do not alter route, status, or mutation semantics. Documentation is updated last to describe only guarantees proven by the final code and tests.

**Tech Stack:** Tailwind CSS v4, Jinja2, vanilla JS/HTMX, pytest, MkDocs.

**Spec:** `docs/superpowers/specs/2026-08-19-ui-07-ui-08-phase-a-hardening-design.md`

## Global Constraints

- Branch from the epic head after UI-07B merge.
- Source implementation first, structural/non-test review second, regression tests last.
- Normal text target >= 4.5:1; large text target >= 3:1.
- Status meaning cannot depend only on color or icon.
- Reduced motion must preserve understandable state changes and loading feedback.
- Documentation may claim only verified framework-owned guarantees.
- No new product capability, browser automation infrastructure, or release publication.

---

### Task 1: Audit and Harden Semantic Color/Contrast Roles

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/assets/rakit.css`
- Regenerate: `packages/rakit-web/src/rakit_web/static/rakit.css`
- Modify only when a semantic class application is wrong: affected framework templates.

**Interfaces:**
- Consumes: existing Rakit semantic tokens for background, surface, text, muted/subtle text, border, brand, focus, success, warning, danger, and info.
- Produces: readable light/dark role combinations without replacing semantic tokens with concrete ad-hoc palette classes.

- [ ] **Step 1: Review current token pairings and component states**

Inspect normal body text, muted text, subtle text, placeholder/help text, links, chips, table headers, disabled states, alerts, status chips, focus rings, and dark-mode overrides. Prefer correcting the semantic token definition or reusable `.rakit-*` primitive when a problem is systemic.

- [ ] **Step 2: Implement contrast corrections**

Keep normal text and large text at the stated targets. Ensure focus indicators remain visible against background, surface, raised, and danger contexts in both themes.

- [ ] **Step 3: Structural review**

Confirm the UI still uses semantic Rakit roles, dark mode remains independently calibrated, brand usage stays restrained, and disabled/muted presentation is readable without appearing interactive.

- [ ] **Step 4: Add contrast/token regression tests last**

Create `packages/rakit-web/tests/test_ui07_contrast_motion_contracts.py` with source-token/component assertions that prevent regression to concrete generic colors and verify the required semantic roles/focus/reduced-motion rule exist. Numeric contrast is manually verified for the selected token pairs and documented in the PR evidence; this slice does not introduce a new color-analysis dependency.

- [ ] **Step 5: Rebuild CSS and run focused tests**

```powershell
bun run css:build
uv run pytest packages/rakit-web/tests/test_ui07_contrast_motion_contracts.py packages/rakit-web/tests/test_ui_tokens.py -q
```

---

### Task 2: Harden Reduced Motion and Pending/Loading Communication

**Files:**
- Modify: `packages/rakit-web/src/rakit_web/assets/rakit.css`
- Regenerate: `packages/rakit-web/src/rakit_web/static/rakit.css`
- Modify as needed: `packages/rakit-web/src/rakit_web/static/rakit-ui.js`
- Modify as needed: templates containing HTMX loading/pending feedback, especially `packages/rakit-web/src/rakit_web/templates/resources/_table.html` and action/page feedback templates.

**Interfaces:**
- Consumes: existing transitions, spinners/loading states, HTMX indicators, live announcer.
- Produces: reduced-motion-safe UI where state change remains textual/semantic even when animation is removed.

- [ ] **Step 1: Implement one shared reduced-motion policy**

Use `@media (prefers-reduced-motion: reduce)` in maintainer CSS to remove or sharply reduce nonessential transition/animation duration on framework-owned UI while avoiding changes that hide visibility/state transitions.

- [ ] **Step 2: Verify pending/loading states have text or accessible status meaning**

Examples such as deferred counts, action submissions, and loading widgets must remain understandable when motion is absent. Do not add decorative spinner-only communication.

- [ ] **Step 3: Structural review**

Confirm HTMX request behavior and live-announcement hooks remain unchanged; motion changes are presentation-only.

- [ ] **Step 4: Extend regression tests last**

Add assertions to `test_ui07_contrast_motion_contracts.py` for the reduced-motion media query and representative textual pending/loading states.

- [ ] **Step 5: Run focused tests**

```powershell
uv run pytest packages/rakit-web/tests/test_ui07_contrast_motion_contracts.py packages/rakit-web/tests/test_accessibility_contracts.py -q
```

---

### Task 3: Clarify Consequential, Empty, Error, and Session Copy

**Files:**
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/forms/delete_confirm.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/actions/_confirm.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/actions/_bulk_delete_content.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/actions/_bulk_feedback_content.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/resources/_table.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/auth/login.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/system/page.html`
- Modify as needed: `packages/rakit-web/src/rakit_web/templates/pages/rejected.html`

**Interfaces:**
- Consumes: current operation result/status and safe server-provided labels/reasons.
- Produces: concise copy that states what happened, what destructive action will do, and what the user can do next.

- [ ] **Step 1: Clarify destructive confirmations**

Delete/bulk/danger confirmation copy must name the operation and state that the change is destructive/irreversible where that is true. Do not imply deletion when a custom action has different domain semantics.

- [ ] **Step 2: Clarify empty and no-results states**

Keep the distinction between an empty resource and an active query with no matches. Preserve relevant clear-search/clear-filter recovery actions.

- [ ] **Step 3: Clarify auth/session/system feedback**

Invalid credentials, signed-out/session-expired, forbidden, missing, and production-error screens use safe copy that does not expose internal exception/auth reason details.

- [ ] **Step 4: Structural review**

Confirm HTTP status codes, redirect targets, safe reason models, and production redaction are unchanged.

- [ ] **Step 5: Add copy/semantic regression assertions last**

Update existing maturity/accessibility tests to pin only meaningful copy and semantic roles, not full snapshots.

- [ ] **Step 6: Run focused tests**

```powershell
uv run pytest packages/rakit-web/tests/test_auth_ui_maturity.py packages/rakit-web/tests/test_advanced_ui_maturity.py packages/rakit-web/tests/test_custom_page_ui_maturity.py packages/rakit-web/tests/test_accessibility_contracts.py -q
```

---

### Task 4: Update Accessibility Documentation from Verified Guarantees

**Files:**
- Modify: `docs/accessibility.md`

**Interfaces:**
- Consumes: final UI-07A/B/C code and regression evidence.
- Produces: accurate public accessibility guarantees and explicit non-certification boundary.

- [ ] **Step 1: Re-read final tests and source before editing docs**

For each documented guarantee, point to an automated contract or combined manual acceptance item. Remove or narrow wording that cannot be defended.

- [ ] **Step 2: Update `docs/accessibility.md`**

Document verified guarantees for responsive built-in surfaces, keyboard/focus behavior, form error linkage, dialogs/popovers, status meaning, light/dark/system themes, reduced motion, no-JS critical flows, and representative duplicate-ID checks. Retain the statement that this is not formal WCAG certification and that application-owned custom templates remain the application's responsibility.

- [ ] **Step 3: Structural review**

Ensure docs do not claim Playwright/axe/cross-browser automation because those remain deferred roadmap items.

- [ ] **Step 4: Run docs build**

```powershell
uv run mkdocs build --strict
```

---

### Task 5: Run Full UI-07C Gate

**Files:** generated CSS, tests, docs, and only source files required by Tasks 1–4.

**Interfaces:**
- Consumes: completed UI-07C source/tests/docs.
- Produces: CI-ready final child head for merge to epic.

- [ ] **Step 1: Rebuild CSS and verify generated output is committed**

```powershell
bun run css:build
```

- [ ] **Step 2: Run JS syntax verification if JS changed**

- [ ] **Step 3: Run format/lint/types**

```powershell
uv run ruff format --check .
uv run ruff check .
uv run ty check
```

- [ ] **Step 4: Run complete repository tests and coverage**

```powershell
uv run pytest
uv run pytest --cov
```

- [ ] **Step 5: Run docs/artifact checks**

```powershell
uv run mkdocs build --strict
uv run python scripts/check_artifacts.py
```

- [ ] **Step 6: Inspect final diff**

Confirm only contrast/motion/copy/docs/regression changes are present; no new feature or release work is included.

- [ ] **Step 7: Open child PR and require fresh full GitHub CI before merge to epic**
