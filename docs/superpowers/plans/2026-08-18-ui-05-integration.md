# UI-05 Integration Workflow

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver UI-05 as three independently reviewable slices that accumulate on a dedicated integration branch before the combined UI-05 changes are proposed to `main`.

**Architecture:** `ui-05-resource-experience` is the staging/integration branch for UI-05. UI-05A, UI-05B, and UI-05C are implemented sequentially from the current integration head, reviewed independently, and merged back into the integration branch. Only the final combined integration branch is proposed to `main` after maintainer review.

**Tech Stack:** Git/GitHub workflow plus the existing Rakit Python/Starlette/Jinja/HTMX/Tailwind stack defined by the slice plans.

## Global Constraints

- `main` remains untouched by UI-05 slice merges until the combined integration branch is reviewed.
- Integration branch: `ui-05-resource-experience`.
- Slice branches:
  - `ui-05a-dashboard-experience`
  - `ui-05b-resource-list-experience`
  - `ui-05c-resource-detail-forms`
- UI-05A starts from the integration branch baseline containing all approved UI-05 specs and plans.
- UI-05B is created from the integration branch only after UI-05A has merged into integration.
- UI-05C is created from the integration branch only after UI-05B has merged into integration.
- The maintainer explicitly permits completed/reviewed slices to merge into `ui-05-resource-experience` without a separate merge-approval round for each slice.
- Merging `ui-05-resource-experience` into `main` still requires explicit maintainer approval.
- No release, tag, GitHub Release, PyPI, or TestPyPI action is part of UI-05.
- Keep all UI maturity planning docs in the repo until UI-08 cleanup.
- Approved execution style for each slice is feature implementation first, visual/manual review second, focused tests at the end, then the full verification gate.

## Source of Truth

Approved design specs:

- `docs/superpowers/specs/2026-08-18-ui-05a-dashboard-experience-design.md`
- `docs/superpowers/specs/2026-08-18-ui-05b-resource-list-experience-design.md`
- `docs/superpowers/specs/2026-08-18-ui-05c-resource-detail-forms-design.md`

Implementation plans:

- `docs/superpowers/plans/2026-08-18-ui-05a-dashboard-experience.md`
- `docs/superpowers/plans/2026-08-18-ui-05b-resource-list-experience.md`
- `docs/superpowers/plans/2026-08-18-ui-05c-resource-detail-forms.md`

The three slice specs supersede the original single-PR UI-05 section in the older UI/UX maturity master plan whenever the scopes conflict.

## Merge Sequence

```text
main
  |
  +-- ui-05-resource-experience
        |
        +-- ui-05a-dashboard-experience
        |      -> review -> merge into integration
        |
        +-- ui-05b-resource-list-experience
        |      -> review -> merge into integration
        |
        +-- ui-05c-resource-detail-forms
               -> review -> merge into integration

ui-05-resource-experience
  -> combined visual/local verification
  -> maintainer approval
  -> PR to main
```

## Slice Completion Gate

Each slice must complete this sequence before merge into integration:

1. Feature surface complete.
2. Source-level self-review against its approved spec.
3. Visual/manual review using `examples/ui_showcase` when the surface is visible there.
4. Focused regression tests added/finalized.
5. Tailwind source regenerated where CSS changed.
6. Ruff format/check, `ty`, and `git diff --check` green.
7. Relevant focused tests green.
8. Full test/coverage gate green when execution environment is available; otherwise the slice is explicitly marked as requiring maintainer local verification before the final integration-to-main PR.
9. PR diff reviewed for security, capability, query, progressive-enhancement, and scope boundaries.
10. Merge into `ui-05-resource-experience`.

## Final UI-05 Gate

After UI-05C merges into integration:

- inspect dashboard, resource list, detail, create/edit, delete, empty/no-results, pagination, filtering, and dark mode together;
- run the repository release-quality gate:

```powershell
uv run ruff format --check .
uv run ruff check .
uv run ty check
git diff --check
uv run pytest -n auto --cov
uv run mkdocs build --strict
uv run python scripts/check_artifacts.py
```

Only after this combined review should `ui-05-resource-experience` be proposed to `main`.