# Piccolo ORM Persistence Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise `persistence.piccolo` from 3/5 to truthful 5/5 using Piccolo's native `Table` metadata, root transaction context, explicit joining tables, and UPDATE/DELETE `RETURNING` results.

**Architecture:** Preserve `PiccoloUnitOfWork` as the sole transaction owner. Add conditional version predicates to the existing `RETURNING(identity)` generated mutations and use returned-row cardinality as the atomic success detector. Build relationships from stable Piccolo `_meta` FK/reverse-FK/M2M seams and execute graph writes with explicit table queries, especially for M2M/association behavior.

**Tech Stack:** `piccolo>=1.30,<2`, Python 3.12-3.14, SQLite >=3.35 for RETURNING, PostgreSQL, selected Cockroach proof, pytest/anyio, uv, ruff, ty.

**Spec:** `docs/superpowers/specs/2026-08-23-persistence-capability-parity-design.md`

## Global Constraints

- Start after P2 is squash-merged; branch from canonical `main`, recommended `parity-p3-piccolo`.
- Do not add driver-rowcount dependence to Piccolo atomic concurrency; use the existing RETURNING result.
- Keep current dependency line `piccolo>=1.30,<2` unless implementation evidence disproves the research finding.
- M2M/association source of truth is the explicit joining `Table`; convenience M2M helpers are optional.
- Cockroach's upstream M2M shortcut caveat must be proven around with explicit joining-table queries or fail closed.
- Source-first workflow; capability profile last.

---

## Task 1: Enable conditional RETURNING-based concurrency

**Files:**
- Modify: `packages/rakit-piccolo/src/rakit_piccolo/generated.py`
- Create if isolation improves clarity: `packages/rakit-piccolo/src/rakit_piccolo/concurrency.py`

- [ ] Accept either no concurrency configuration or a complete provider/token pair in `PiccoloGeneratedResourceExecutorProvider.build()`; reject partial configuration.
- [ ] Store the neutral concurrency provider/token service on the executor.
- [ ] Keep `participates_in_uow=True`; set `atomic_concurrency=True` only after the conditional path is implemented.
- [ ] On UPDATE, read current scoped row for initial not-found and token verification, then build one Piccolo UPDATE with identity + expected predicate values.
- [ ] Resolve provider predicate field names to concrete Piccolo columns and fail closed for unknown fields.
- [ ] Merge user changes with next version values. For integer version, use `Model.version + 1` in the same UPDATE rather than a separate write.
- [ ] Preserve `.returning(identity_column)` and classify `len(returned) == 1` as success, `0` after initial validation as `RESOURCE_CONFLICT`, and any other count as fail-closed configuration/integrity error.
- [ ] Reload the updated row after success.
- [ ] Apply the same identity + expected-state predicate to DELETE and classify empty RETURNING after initial validation as conflict.
- [ ] Preserve non-concurrency generated CRUD for resources without a registered concurrency provider.

**Non-test verification:**

- [ ] Run `uv run python -m compileall packages/rakit-piccolo/src/rakit_piccolo`.
- [ ] Run ruff on touched source.
- [ ] Run a throwaway SQLite Piccolo script: version=1 -> returned identity + version=2; stale version=1 -> empty RETURNING; stale delete -> empty RETURNING and row remains.
- [ ] Print/check `sqlite3.sqlite_version` and explicitly refuse the smoke if it is below 3.35 rather than treating unsupported RETURNING as a provider result.

---

## Task 2: Add Piccolo relationship introspection/validation

**Files:**
- Create: `packages/rakit-piccolo/src/rakit_piccolo/relationships.py`
- Modify: `packages/rakit-piccolo/src/rakit_piccolo/datasource.py`
- Modify only for shared scalar metadata reuse if needed: `packages/rakit-piccolo/src/rakit_piccolo/introspection.py`

- [ ] Inspect forward FK relations from stable Piccolo table metadata.
- [ ] Inspect reverse FK references and named M2M declarations from Piccolo `_meta` seams documented/used by upstream.
- [ ] Translate supported facts to neutral `RelationshipMetadata` without returning Piccolo objects through core.
- [ ] Validate many-to-one and one-to-many by exact native edge/target.
- [ ] Treat a relation as O2O only when uniqueness is proven by the FK/native constraint metadata; a plain FK never becomes O2O from Rakit declaration alone.
- [ ] Resolve M2M to its real joining `Table`, including explicit FK-column selection when the join table has more than two FK candidates.
- [ ] For association object, require an explicit registered joining `Table` resource with supported scalar identity and declared safe scalar fields.
- [ ] Validate ordering only when an explicit safe position field exists on child/association table.
- [ ] Add datasource `relationship_metadata` and `validate_relationship(...)` using the compiler's existing duck-typed seam.
- [ ] Reject incompatible datasource/target types and ambiguous relation shapes.
- [ ] Keep `on_delete` / `on_update` metadata separate from Rakit destructive policy.

**Non-test verification:**

- [ ] Define native Piccolo tables covering forward FK, reverse FK, unique FK O2O, M2M, joining table with extra scalar columns, ordering, and ambiguous >2-FK joining table.
- [ ] Validate each supported `RelationshipDefinition` directly.
- [ ] Confirm ambiguous joining paths fail until explicitly bound by provider-local metadata/configuration.

---

## Task 3: Implement explicit joining-table relationship state/mutations

**Files:**
- Create: `packages/rakit-piccolo/src/rakit_piccolo/relationship_mutations.py`
- Modify as needed: `packages/rakit-piccolo/src/rakit_piccolo/datasource.py`

- [ ] Implement scoped parent/target resolution through datasource-owned Piccolo queries.
- [ ] Implement neutral editor methods `editor_page`, `issue_concurrency_token`, and `reorder_identities` without exposing `Table` instances outside adapter-facing service internals.
- [ ] Implement singular SET/CLEAR by explicit FK UPDATE.
- [ ] Implement reverse collection link/unlink through child FK UPDATE.
- [ ] Implement M2M read/link/unlink/clear with explicit joining-table SELECT/INSERT/DELETE rather than depending on the upstream M2M subquery shortcut.
- [ ] Implement association-object scalar edits against the explicit joining `Table` resource and preserve association identity in `RelationshipEditorRow`/neutral receipts.
- [ ] Reorder only through explicit position-field updates.
- [ ] Resolve all targets through their target datasource scope before linking.
- [ ] Keep graph operations inside the active Piccolo root transaction context; do not open another transaction.
- [ ] Verify parent/child/association concurrency before durable completion and map stale state to conflict with rollback.
- [ ] Enforce compiled destructive policy independently of Piccolo FK cascade settings.

**Non-test verification:**

- [ ] Exercise FK set/clear, reverse link/unlink, M2M link/unlink, association scalar update, and reorder in one root UoW.
- [ ] Force an exception after an earlier graph step and verify rollback.
- [ ] Confirm explicit M2M joining-table read does not use the upstream Cockroach-problematic shortcut shape.

---

## Task 4: Add focused atomic-concurrency regression coverage

**Files:**
- Create: `packages/rakit-piccolo/tests/test_piccolo_concurrency.py`
- Modify: `packages/rakit-piccolo/tests/test_piccolo_capability_conformance.py`

- [ ] Successful conditional UPDATE returns one identity and advances version.
- [ ] Stale UPDATE returns no identity and maps to `RESOURCE_CONFLICT`.
- [ ] Initial missing row remains `RESOURCE_NOT_FOUND`.
- [ ] Wrong token binding maps to conflict.
- [ ] Conditional DELETE succeeds at expected state; stale delete leaves row durable.
- [ ] Root-UoW rollback undoes a previously successful conditional update when later work fails.
- [ ] Unsupported SQLite RETURNING runtime fails closed with a clear capability/runtime error path where practical to simulate.
- [ ] Extend `assert_atomic_optimistic_semantics()` after focused tests pass.

```bash
uv run pytest packages/rakit-piccolo/tests/test_piccolo_concurrency.py -q
uv run pytest packages/rakit-piccolo/tests/test_piccolo_capability_conformance.py -q
```

---

## Task 5: Add focused relationship regression coverage

**Files:**
- Create: `packages/rakit-piccolo/tests/test_piccolo_relationships.py`
- Modify: `packages/rakit-piccolo/tests/test_piccolo_capability_conformance.py`

- [ ] Cover forward FK, reverse FK, O2O uniqueness, M2M joining-table discovery, association object with scalar fields, ordering, and ambiguous join-FK selection.
- [ ] Cover scoped candidate rejection.
- [ ] Cover SET/CLEAR, reverse link/unlink, M2M link/unlink/clear, duplicate link behavior, association scalar update, and reorder.
- [ ] Cover destructive denial despite native cascade configuration.
- [ ] Cover graph commit/rollback and stale parent/association conflict with no partial durability.
- [ ] Extend `assert_relationship_semantics()` with the representative neutral set.

```bash
uv run pytest packages/rakit-piccolo/tests/test_piccolo_relationships.py -q
uv run pytest packages/rakit-piccolo/tests/test_piccolo_capability_conformance.py -q
```

---

## Task 6: Add the minimum explicit backend/runtime gates

**Files:**
- Modify `.github/workflows/ci.yml` only if the existing matrix lacks the required proof path.
- Add provider-local backend test modules/markers only when needed to isolate external DB runs.

- [ ] SQLite: assert runtime >=3.35 in the relevant write/concurrency conformance setup and run conditional UPDATE/DELETE RETURNING cases.
- [ ] PostgreSQL: run the same atomic cases plus representative explicit joining-table graph cases.
- [ ] Cockroach: prove conditional mutation and explicit joining-table M2M read/write path. Do not test the known problematic convenience-subquery path and then generalize success.
- [ ] If Cockroach explicit joining-table semantics cannot be proven reliably, fail closed/narrow that shape in adapter validation rather than weakening `persistence.relationships` behavior silently.
- [ ] Do not add MySQL to Piccolo parity unless the shipped Piccolo backend matrix actually claims/supports it and the capability requires proof there.

---

## Task 7: Lowest/latest and package verification

- [ ] `uv sync --all-packages --dev --locked`.
- [ ] `uv run pytest packages/rakit-piccolo/tests -q`.
- [ ] `uv run ruff format --check .`.
- [ ] `uv run ruff check .`.
- [ ] `uv run ty check`.
- [ ] Run package tests at lowest-direct resolution, ensuring Piccolo 1.30 remains green.
- [ ] Run package tests at latest allowed Piccolo 1.x.
- [ ] Restore normal locked environment after compatibility-only runs.

No dependency-floor bump is expected. If 1.30 fails a required primitive, stop before changing `pyproject.toml` and document the exact contradiction with research.

---

## Task 8: Promote Piccolo capability profile last

**Files:**
- Modify: `packages/rakit-piccolo/src/rakit_piccolo/capabilities.py`
- Modify: `packages/rakit-piccolo/tests/test_piccolo_capability_profile.py`
- Modify: `.github/workflows/ci.yml` clean-install Piccolo capability assertion

- [ ] Add `PERSISTENCE_RELATIONSHIPS` and `CONCURRENCY_ATOMIC_OPTIMISTIC` only after Tasks 1-7 are green.
- [ ] Update exact provider capability expectations from 3 to 5.
- [ ] Preserve integration ID and dependency floor.

---

## Task 9: Exact-head PR gate

- [ ] Run full repository tests.
- [ ] Verify no rowcount abstraction or ORM-specific core changes were introduced.
- [ ] Verify current `piccolo>=1.30,<2` remains unchanged unless separately approved from new evidence.
- [ ] Push exact provider head and require CI green.
- [ ] Squash merge P3.
- [ ] Start P4 Peewee from updated canonical `main`.

**Expected shipped result after P3:** `persistence.piccolo` truthfully advertises all five canonical persistence capabilities, with RETURNING and Cockroach joining-table constraints explicitly proven or fail-closed.
