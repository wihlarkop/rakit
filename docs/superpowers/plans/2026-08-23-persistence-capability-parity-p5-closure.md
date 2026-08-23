# Persistence Capability Parity Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the additive persistence parity workstream after P1-P4 by making documentation, capability discovery, compatibility proof, artifacts, and CI reflect the final honest provider capability matrix.

**Architecture:** P5 introduces no new persistence mechanism. It reconciles provider-local results into repository-level truth, re-runs the existing canonical capability and release gates, and records any provider that honestly stopped below 5/5 without rewriting completed D3 history.

**Tech Stack:** Rakit monorepo, Markdown/MkDocs, existing capability discovery, pytest, uv, GitHub Actions, artifact build/install smoke.

**Spec:** `docs/superpowers/specs/2026-08-23-persistence-capability-parity-design.md`

## Global Constraints

- Start from canonical `main` after P1-P4 are merged or have an explicitly documented lower capability ceiling.
- Recommended branch: `parity-p5-persistence-closure`.
- Do not implement missing provider behavior in P5; route provider defects back to the provider workstream or document the honest ceiling.
- D3 remains Complete. Record parity as additive completion, not as D3 rework.
- No release, tag, TestPyPI, PyPI, or version bump.

---

## Task 1: Build the final shipped capability matrix from code, not expectation

**Files to inspect:**
- `packages/rakit-sqlalchemy/src/rakit_sqlalchemy/capabilities.py`
- `packages/rakit-tortoise/src/rakit_tortoise/capabilities.py`
- `packages/rakit-piccolo/src/rakit_piccolo/capabilities.py`
- `packages/rakit-peewee/src/rakit_peewee/capabilities.py`
- provider capability-profile tests

- [ ] Record exact shipped capability names for SQLAlchemy ORM, SQLAlchemy Core, Tortoise, Piccolo, and Peewee.
- [ ] Verify SQLAlchemy ORM remains 5/5.
- [ ] Verify each P1-P4 provider is either 5/5 or has a documented evidence-backed lower ceiling.
- [ ] Ensure no provider advertises a capability whose required backend/runtime matrix failed.
- [ ] Confirm Masonite remains absent/unadvertised.

Expected successful target matrix:

```text
persistence.sqlalchemy       5/5
persistence.sqlalchemy-core  5/5
persistence.tortoise         5/5
persistence.piccolo          5/5
persistence.peewee           5/5
```

If implementation evidence produced a different honest result, documentation and artifact assertions must use the actual shipped matrix instead of forcing this target.

---

## Task 2: Update persistence documentation and compatibility notes

**Files:**
- Modify: `docs/guides/persistence-adapters.md`
- Modify: `docs/roadmap.md` only in the additive parity/workstream status area; do not reopen D3
- Modify or create a focused parity completion note only if the roadmap needs a link to detailed evidence
- Keep research/spec/plan documents immutable except for explicit completion/status addenda if needed

- [ ] Update the provider/capability table to the final shipped truth.
- [ ] Document provider-native concurrency mechanism succinctly: Core sane rowcount, Tortoise affected rows, Piccolo RETURNING, Peewee affected rows.
- [ ] Document explicit relationship semantics/limits: Core physical binding ambiguity, Tortoise explicit association model, Piccolo joining table/Cockroach gate, Peewee through/intermediary model and async discipline.
- [ ] Update supported dependency ranges, including Peewee `>=4.0.8,<5` if P4 succeeded as designed.
- [ ] Document Piccolo SQLite RETURNING runtime requirement and any Cockroach limitation/fail-closed behavior that remains relevant.
- [ ] Make clear that SQLAlchemy ORM remains the default/reference provider and `rakit[standard]` does not become install-everything.
- [ ] Keep Plan 03 authentication-provider parity explicitly separate.

Verification:

```bash
uv run mkdocs build --strict
```

---

## Task 3: Update repository-level capability/artifact assertions

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify if final behavior is asserted there: `tests/release/test_installed_artifacts.py`
- Modify any centralized persistence matrix test discovered on current `main`

- [ ] Update clean-install Tortoise, Peewee, and Piccolo artifact snippets to the final exact capability sets.
- [ ] Add/update SQLAlchemy Core exact capability assertion if the artifact/release tests expose it.
- [ ] Preserve the all-persistence-extras entry-point inventory and continue asserting Masonite is absent.
- [ ] Ensure built artifact imports resolve from the clean artifact virtualenv, not the workspace checkout.
- [ ] Keep provider-specific external database proof jobs added in P1-P4; do not duplicate them in a second closure matrix unless needed for aggregate gating.
- [ ] Ensure artifact-dry-run still builds all official distributions and installs `rakit[sqlalchemy,tortoise,peewee,piccolo]` together successfully.

---

## Task 4: Run canonical provider conformance as one closure gate

**Files:** tests only unless a missing neutral assertion is discovered.

Run targeted provider suites:

```bash
uv run pytest packages/rakit-sqlalchemy/tests -q
uv run pytest packages/rakit-tortoise/tests -q
uv run pytest packages/rakit-piccolo/tests -q
uv run pytest packages/rakit-peewee/tests -q
```

- [ ] Verify each advertised `persistence.relationships` provider executes its `assert_relationship_semantics()` canonical hook.
- [ ] Verify each advertised `concurrency.atomic-optimistic` provider executes its `assert_atomic_optimistic_semantics()` canonical hook.
- [ ] Confirm no provider-specific test bypasses the canonical capability registry simply to obtain a green profile.
- [ ] Re-run SQLAlchemy ORM concurrency/relationship/graph suites as the reference regression set.

If two or more provider implementations now contain genuinely identical backend-neutral test assertion code, P5 may extract a helper into `packages/rakit-core/src/rakit_core/testing/` only if it satisfies the locked shared-code extraction policy. Do not extract merely for aesthetic symmetry.

---

## Task 5: Run web/integration regressions without making web ORM-aware

**Files:** existing integration tests, especially:
- `tests/integration/test_relationship_asgi_actions.py`
- `tests/integration/test_relationship_asgi_create_update.py`
- `tests/integration/test_relationship_asgi_errors.py`
- `tests/integration/test_relationship_asgi_graph_ops.py`
- `tests/integration/test_relationship_asgi_query.py`
- `tests/integration/test_relationship_asgi_transaction.py`

- [ ] Run the existing relationship ASGI integration suite.
- [ ] Confirm `rakit-web` still imports only neutral relationship/concurrency contracts and contains no Tortoise/Piccolo/Peewee/Core implementation imports.
- [ ] Confirm neutral relationship form/state protocols still accept provider-local services without transport changes.
- [ ] Confirm transaction/concurrency errors still render through existing neutral error handling.

```bash
uv run pytest tests/integration/test_relationship_asgi_actions.py tests/integration/test_relationship_asgi_create_update.py tests/integration/test_relationship_asgi_errors.py tests/integration/test_relationship_asgi_graph_ops.py tests/integration/test_relationship_asgi_query.py tests/integration/test_relationship_asgi_transaction.py -q
```

---

## Task 6: Run lowest-direct and latest-allowed compatibility gates

Use the repository's existing CI semantics:

```bash
uv sync --all-packages --dev --resolution lowest-direct
uv run --no-sync pytest -q --tb=short --maxfail=5

uv sync --all-packages --dev --upgrade
uv run --no-sync pytest -q --tb=short --maxfail=5
```

- [ ] Verify lowest-direct exercises SQLAlchemy 2.0 lower bound, Tortoise lower bound, Piccolo 1.30, and Peewee >=4.0.8 after the approved floor change.
- [ ] Verify latest allowed dependencies remain green.
- [ ] Ensure provider-specific external DB gates from P1-P4 also run at the minimum/latest versions required by their research acceptance matrix where practical.
- [ ] Restore and verify normal `uv.lock` after compatibility runs.

---

## Task 7: Run full static, test, docs, and artifact gates

From a clean locked environment:

```bash
uv sync --all-packages --dev --locked
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
uv run pytest --cov
uv run mkdocs build --strict
uv run python scripts/check_artifacts.py
uv run pytest tests/release -v
```

- [ ] Build all official packages to a clean `dist/` directory using the same loop as `.github/workflows/ci.yml` artifact-dry-run.
- [ ] Clean-install each persistence extra from built artifacts.
- [ ] Clean-install all persistence extras together.
- [ ] Verify entry points and exact capability profiles from installed artifacts.
- [ ] Confirm no source-tree import leakage.

---

## Task 8: Final roadmap/research completion record

**Files:**
- Modify: `docs/roadmap.md` if the additive parity workstream is tracked there
- Create a small completion addendum under `docs/superpowers/research/` only if needed to preserve immutable evidence while recording final implementation outcome

- [ ] Mark persistence capability parity Complete only after Tasks 1-7 are green.
- [ ] Record final provider capability matrix and any permanent compatibility limits.
- [ ] Keep D3 itself Complete and historical subphase statuses unchanged.
- [ ] Keep D4 roadmap status unchanged unless the current canonical roadmap independently says it should advance.
- [ ] State that Plan 03 may resume next without implying auth-provider parity.
- [ ] Do not add release language or version promises.

---

## Task 9: Exact-head closure PR and squash merge

- [ ] Push the closure branch.
- [ ] Wait for/inspect all GitHub Actions jobs on the exact head: Python 3.12, 3.13, 3.14; web assets; lowest-direct; latest; release gate; artifact dry run; plus provider-specific DB jobs retained from P1-P4.
- [ ] Inspect failed/skipped jobs rather than treating a partial green set as closure.
- [ ] Review the exact-head diff for accidental runtime feature work, dependency drift, version bumps, or D3 history rewrites.
- [ ] Require docs, capability matrices, artifact assertions, and code profiles to agree exactly.
- [ ] Squash merge P5 when the exact head is green.
- [ ] Do not tag or publish.

**Expected final result:** the shipped persistence ecosystem has one truthful documented capability matrix, ideally 5/5 across SQLAlchemy ORM, SQLAlchemy Core, Tortoise, Piccolo, and Peewee; all higher capabilities are behaviorally proven with provider-native mechanisms and no ORM assumptions leaked into core/web.
