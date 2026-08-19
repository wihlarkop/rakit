# UI-08 Final Polish Implementation Plan

> **Execution note:** Follow the approved Phase A hardening design in `docs/superpowers/specs/2026-08-19-ui-07-ui-08-phase-a-hardening-design.md`. UI-08 is a bounded polish pass, not a feature phase.

## Execution Result

- Product finding classification: **no P0, P1, or material P2 findings** after the accepted UI-07 browser result and final framework-owned source audit.
- Product source changes: **none by design**; cosmetic churn was deferred rather than manufactured.
- Planning-document classification: retained existing UI maturity specs/plans as useful design/execution history; no unconditional deletions performed.
- Remaining gate: fresh UI-08 PR CI on the exact documentation-only head, followed by merge to `main`.
- Release side effects: none.

## Goal

Close Phase A after UI-07 by performing one final product-quality audit, fixing only P0/P1/material-P2 findings, verifying consistency across representative themes/viewports, conservatively classifying completed planning artifacts, and opening the final UI-08 PR without release side effects.

## Baseline

- Base branch: `main`
- Base commit: `0ce275b475c94da0152e94bfed343d1decabcf06`
- Working branch: `ui-08-final-polish`
- UI-07 combined browser acceptance: PASS
- UI-07 final PR CI #871: PASS

## Hard Boundaries

UI-08 may change framework-owned UI/templates/CSS/JS, deterministic showcase fixtures, semantic regression tests, and documentation only when justified by a final-audit finding.

UI-08 must not add:

- business capabilities;
- new advanced widget families;
- adapter expansion;
- CRUD lifecycle APIs;
- CLI/scaffolding;
- generated REST/OpenAPI work;
- `examples/reference_app`;
- Playwright/axe/visual-regression infrastructure;
- tag/GitHub Release/TestPyPI/PyPI publication.

If the audit exposes a large architectural problem, stop and classify it outside UI-08 rather than absorbing it into polish.

## Severity Policy

- **P0** — broken/unusable/security/accessibility blocker: must fix.
- **P1** — major UX/accessibility inconsistency: must fix.
- **Material P2** — clearly harms product quality: fix.
- **Cosmetic/minor** — defer unless trivial and demonstrably low-risk.

## Task 1 — Final Source Audit and Finding Classification

Audit these framework-owned surfaces on the merged UI-07 tree:

- shell/navigation/theme chooser;
- dashboard;
- resource list/filter/search/table/pagination;
- resource detail;
- create/edit forms and error states;
- delete confirmation;
- record actions and confirmation;
- bulk selection/actions;
- relationships/autocomplete/multi-autocomplete/no-JS picker;
- uploads and advanced scalar presentations;
- login/session/system errors;
- custom pages;
- UI Lab.

Inspect for:

- stale concrete color/style tokens;
- inconsistent button/input/panel hierarchy;
- duplicate or conflicting focus/disclosure behavior;
- accidental page overflow or fixed widths that escaped UI-07;
- inaccessible names/labels/status-only-color meaning;
- inconsistent error/empty/loading copy;
- stale showcase-only hacks;
- duplicated markup/runtime behavior that creates visible inconsistency;
- planning comments/docs that contradict the current UI-07 result.

Record findings in the UI-08 PR body or commit messages rather than introducing another audit document.

Expected output: a short classified finding list. If there are no P0/P1/material-P2 findings, do not invent cosmetic work.

## Task 2 — Implement Meaningful Findings Only

For every accepted finding:

1. change source/behavior first;
2. perform structural/non-test review;
3. preserve auth/permission/CSRF/idempotency/concurrency/mutation semantics;
4. rebuild generated CSS if maintainer CSS changes;
5. avoid unrelated refactors.

Rules:

- prefer existing semantic Tailwind tokens and shared UI primitives;
- keep reusable JS behavior centralized;
- preserve progressive enhancement and no-JS critical paths;
- do not add new public capability merely to polish a demo;
- runtime Python changes require a concrete presentation need.

## Task 3 — Regression Tests Last

After source changes are structurally reviewed, add/update focused tests that lock the actual regression or semantic contract.

Prefer assertions for:

- important roles/labels/attributes;
- stable focus/error/disclosure hooks;
- route behavior;
- bounded layout/presentation contracts;
- shared primitive usage.

Avoid full HTML snapshots and cosmetic exact-class tests unless the class is itself a stable framework contract.

## Task 4 — Focused Verification

Run focused checks for every changed area, then:

```powershell
bun run css:build
uv run ruff format --check .
uv run ruff check .
uv run ty check
```

If CSS source did not change, still verify generated CSS has no unintended diff.

## Task 5 — Full Repository Gate

Run the repository-equivalent final gate:

```powershell
bun run css:build
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest --cov
uv run mkdocs build --strict
uv run python scripts/check_artifacts.py
```

GitHub PR CI remains authoritative for supported Python/dependency/artifact matrix coverage.

## Task 6 — Planning-Document Classification

Classify candidate UI maturity planning/spec documents individually:

```text
temporary execution artifact, fully superseded -> delete
useful architecture/design history            -> keep
still referenced by architecture/docs          -> keep
```

Before deletion:

- search repository references;
- inspect whether the document still records meaningful architectural decisions;
- confirm MkDocs/artifact checks remain valid;
- perform deletions in a separate auditable commit.

Do **not** delete `2026-08-17-ui-ux-maturity-design.md` or `2026-08-17-ui-ux-maturity.md` merely because the old master plan instructed it. The newer approved Phase A spec supersedes that unconditional cleanup rule.

## Task 7 — Final Diff Review

Compare `ui-08-final-polish` against `main` and confirm:

- only accepted final-polish changes are present;
- no helper workflows/debug artifacts remain;
- no release/tag/publication changes exist;
- no new feature scope leaked into UI-08;
- planning cleanup, if any, is separately auditable.

## Task 8 — Final PR and Acceptance

Open:

```text
ui-08-final-polish -> main
```

PR description must include:

- classified findings and what was fixed/deferred;
- automated verification results;
- planning-doc cleanup classification;
- explicit statement that UI-01 through UI-08 complete Phase A;
- explicit statement that no tag/release/PyPI/TestPyPI action occurred.

Require fresh final PR CI.

If browser-visible changes were made, request a narrow maintainer browser acceptance focused only on those changes. If UI-08 is documentation/test-only because no material visual findings exist, no redundant full browser matrix is required beyond the already-completed UI-07 acceptance and final source audit.

After merge, Phase A is complete and the roadmap moves to Phase B alpha hardening.
