# Tortoise ORM Persistence Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise `persistence.tortoise` from 3/5 to truthful 5/5 using Tortoise's public async query/transaction APIs, named relation metadata, and conditional mutation counts.

**Architecture:** Preserve `TortoiseUnitOfWork` as the sole transaction owner and keep every mutation on its `BaseDBAsyncClient`. Use public `Model.describe()` for new relationship introspection where sufficient, filtered QuerySet UPDATE/DELETE for compare-and-write, native named FK/backward/O2O/M2M metadata for relation binding, and explicit application-owned models for association-object semantics.

**Tech Stack:** `tortoise-orm>=1.1.7,<2`, Python 3.12-3.14, pytest/anyio, SQLite baseline plus the backend matrix required to prove affected-row semantics, uv, ruff, ty.

**Spec:** `docs/superpowers/specs/2026-08-23-persistence-capability-parity-design.md`

## Global Constraints

- Start after P1 is squash-merged; branch from canonical `main`, recommended `parity-p2-tortoise`.
- Do not add a second transaction/session abstraction.
- All mutation/query calls that participate in a graph write must use `.using_db(root_connection)` or the equivalent explicit root connection API.
- Integer version-column concurrency is first. Snapshot/no-op concurrency remains fail-closed until backend behavior is separately proven.
- Native M2M `through` metadata is not a rich association object. Rich associations require explicit Tortoise models.
- Use source-first workflow; permanent tests come after source/manual verification.
- Edit `capabilities.py` last.

---

## Task 1: Enable atomic concurrency in generated Tortoise CRUD

**Files:**
- Modify: `packages/rakit-tortoise/src/rakit_tortoise/generated.py`
- Create if useful for isolation: `packages/rakit-tortoise/src/rakit_tortoise/concurrency.py`

- [ ] Change `TortoiseGeneratedResourceExecutorProvider.build()` to accept either no concurrency configuration or a complete `concurrency_provider` + `concurrency_tokens` pair; reject partial configuration.
- [ ] Store the neutral concurrency provider/token service on the executor.
- [ ] Change executor capabilities to `atomic_concurrency=True` only after the final mutation path is conditional and root-UoW owned.
- [ ] On UPDATE, load current record through `.using_db(connection)` for initial scope/not-found and token verification.
- [ ] Translate `predicate_values_for(current)` to concrete Tortoise field predicates and fail closed for unknown fields.
- [ ] Build one filtered QuerySet containing identity + expected concurrency predicates.
- [ ] Merge request input with next-version values in the same UPDATE. For an integer version field, prefer database-side `F("version") + 1` (or the supported Tortoise expression equivalent) rather than computing and writing a second statement.
- [ ] Treat affected count `1` as success. If initial validation succeeded but final conditional UPDATE returns `0`, raise `RESOURCE_CONFLICT`.
- [ ] Reload the record after an expression update so returned state contains the real advanced version rather than an unresolved expression.
- [ ] On DELETE, include expected concurrency predicate in the same filtered delete; zero after initial validation is conflict.
- [ ] Preserve non-concurrency behavior for resources with no registered provider.

**Non-test verification:**

- [ ] Run `uv run python -m compileall packages/rakit-tortoise/src/rakit_tortoise`.
- [ ] Run `uv run ruff check packages/rakit-tortoise/src/rakit_tortoise/generated.py` plus any new module.
- [ ] Run a throwaway SQLite Tortoise script inside `TortoiseUnitOfWork`: version=1 -> conditional update -> version=2 -> stale expected=1 returns zero; repeat for delete.
- [ ] Verify every read/write in the smoke explicitly uses the root connection.

---

## Task 2: Add public relationship introspection and validation

**Files:**
- Create: `packages/rakit-tortoise/src/rakit_tortoise/relationships.py`
- Modify: `packages/rakit-tortoise/src/rakit_tortoise/datasource.py`
- Modify only if scalar metadata reuse is useful: `packages/rakit-tortoise/src/rakit_tortoise/introspection.py`

- [ ] Use `Model.describe()` as the preferred public seam for FK, backward FK, O2O, backward O2O, and M2M structural facts.
- [ ] Translate named native edges to `RelationshipMetadata` without returning Tortoise field objects through core APIs.
- [ ] Validate target model, kind, cardinality, nullable semantics, and self-reference.
- [ ] Treat O2O as O2O only when Tortoise metadata explicitly represents that singular relation; do not infer it from naming.
- [ ] For M2M, validate the named relation and target model; keep `through` table metadata as physical M2M evidence only.
- [ ] For `ASSOCIATION_OBJECT`, require `association_target_resource_id` to point to an explicit registered Tortoise model whose two named relations and allowed scalar fields can be proven.
- [ ] Validate writable ordering only through an explicit integer/safe scalar position field on the child/association model.
- [ ] Expose `relationship_metadata` and `validate_relationship(...)` on `TortoiseDataSource` following the existing compiler duck-typed seam.
- [ ] Reject incompatible target datasource types instead of trying cross-ORM relationship mutation.
- [ ] Keep `on_delete` facts informational; they never imply Rakit destructive permission.

**Non-test verification:**

- [ ] Define throwaway models covering FK, reverse FK, O2O, M2M, explicit Membership association model, ordering, self-reference, and multiple FKs to one target.
- [ ] Call datasource `validate_relationship(...)` directly for supported definitions.
- [ ] Verify multiple/named FK cases are resolved by declared relation name, not first-match target type.

---

## Task 3: Implement scoped Tortoise relationship state and mutation service

**Files:**
- Create: `packages/rakit-tortoise/src/rakit_tortoise/relationship_mutations.py`
- Modify as needed: `packages/rakit-tortoise/src/rakit_tortoise/datasource.py`

- [ ] Implement an adapter-local resolver that resolves parent and target records through datasource scope and accepts an explicit `BaseDBAsyncClient` for mutation-time reads.
- [ ] Implement neutral editor-state methods `editor_page`, `issue_concurrency_token`, and `reorder_identities` without exposing ORM objects to web/core.
- [ ] Execute singular FK SET/CLEAR by updating the FK field through the root connection.
- [ ] Execute one-to-many link/unlink through the child FK, validating parent/target scope before mutation.
- [ ] Execute native M2M link/unlink/clear using a Tortoise API only if `using_db` / root connection ownership is explicit and proven. Otherwise perform explicit through-table operations through supported public APIs.
- [ ] Execute rich association-object create/update/delete through the explicit association model, including association scalar allow-list and association identity.
- [ ] Implement reorder by writing the explicit position field deterministically.
- [ ] Revalidate all link targets against their scoped datasource before writing.
- [ ] Use parent concurrency token/state before graph durability; stale parent/child/association state raises conflict and causes root transaction rollback.
- [ ] No method may open `in_transaction()` independently while an operation UoW is active.
- [ ] Enforce compiled destructive permissions; Tortoise `on_delete` never grants delete authority.

**Non-test verification:**

- [ ] Directly exercise FK set/clear, reverse-FK link/unlink, M2M link/unlink, association scalar update, and reorder within one root UoW.
- [ ] Force an exception after a graph step and verify all writes roll back.
- [ ] Confirm a scoped-out target cannot be linked.

---

## Task 4: Add permanent atomic-concurrency coverage

**Files:**
- Create: `packages/rakit-tortoise/tests/test_tortoise_concurrency.py`
- Modify: `packages/rakit-tortoise/tests/test_tortoise_capability_conformance.py`

- [ ] Successful versioned update increments version in the same durable mutation.
- [ ] Stale update after a competing write -> `RESOURCE_CONFLICT`.
- [ ] Initial missing row -> `RESOURCE_NOT_FOUND`.
- [ ] Wrong token resource/identity/version -> conflict.
- [ ] Conditional delete succeeds only at expected version; stale delete leaves row intact.
- [ ] Later failure in the root UoW rolls back a successful conditional update.
- [ ] Verify reload after `F` expression returns concrete current values.
- [ ] Implement/extend `assert_atomic_optimistic_semantics()` only after focused tests pass.

```bash
uv run pytest packages/rakit-tortoise/tests/test_tortoise_concurrency.py -q
uv run pytest packages/rakit-tortoise/tests/test_tortoise_capability_conformance.py -q
```

---

## Task 5: Add permanent relationship coverage

**Files:**
- Create: `packages/rakit-tortoise/tests/test_tortoise_relationships.py`
- Modify: `packages/rakit-tortoise/tests/test_tortoise_capability_conformance.py`

- [ ] Cover relationship metadata/validation for FK, backward FK, O2O, M2M, explicit association model, ordering, and multiple FK names.
- [ ] Cover editor read/state output using only neutral `RelationshipEditorRow` / `RelationshipCandidate` values.
- [ ] Cover scoped candidate link rejection.
- [ ] Cover SET/CLEAR, collection link/unlink, M2M duplicate behavior, association scalar update, reorder, and allowed destructive path.
- [ ] Cover destructive denial despite ORM cascade metadata.
- [ ] Cover parent stale conflict and child/association stale conflict with no partial graph durability.
- [ ] Cover root transaction rollback across multiple graph steps.
- [ ] Extend `assert_relationship_semantics()` with the representative neutral matrix.

```bash
uv run pytest packages/rakit-tortoise/tests/test_tortoise_relationships.py -q
uv run pytest packages/rakit-tortoise/tests/test_tortoise_capability_conformance.py -q
```

---

## Task 6: Prove backend affected-row semantics before promotion

**Files:**
- Modify CI/test support only if needed after local provider behavior is green.
- Possible focused CI addition: `.github/workflows/ci.yml` if existing CI has no way to exercise required database backends.

- [ ] Keep SQLite as the canonical package contract backend.
- [ ] Add the smallest practical PostgreSQL and MySQL backend proof needed to establish filtered UPDATE/DELETE affected counts for the advertised atomic capability; do not build an unrelated exhaustive ORM matrix.
- [ ] Prove update count for matched version, stale version, and conditional delete.
- [ ] If a supported Tortoise backend cannot distinguish the required stale outcome reliably, fail closed/narrow advertised backend support rather than declaring global semantics accidentally.
- [ ] Leave snapshot/no-op concurrency disabled unless this matrix separately proves it.

Record exact commands/CI services in the implementation PR once the repository's available DB service mechanism is selected; do not invent credentials or production infrastructure in source.

---

## Task 7: Run package, lowest/latest, and static verification

- [ ] `uv sync --all-packages --dev --locked`.
- [ ] `uv run pytest packages/rakit-tortoise/tests -q`.
- [ ] `uv run ruff format --check .`.
- [ ] `uv run ruff check .`.
- [ ] `uv run ty check`.
- [ ] Run Tortoise package tests under `uv sync --all-packages --dev --resolution lowest-direct`.
- [ ] Run them under `uv sync --all-packages --dev --upgrade`.
- [ ] Restore normal lock/environment state after compatibility-only runs.

No dependency-floor change is planned for Tortoise from this research. If the lowest supported `1.1.7` contradicts implementation assumptions, stop and document the evidence before changing the range.

---

## Task 8: Promote Tortoise capability profile last

**Files:**
- Modify: `packages/rakit-tortoise/src/rakit_tortoise/capabilities.py`
- Modify: `packages/rakit-tortoise/tests/test_tortoise_capability_profile.py`
- Modify: `.github/workflows/ci.yml` artifact assertion for Tortoise exact capability names

- [ ] Add `PERSISTENCE_RELATIONSHIPS` and `CONCURRENCY_ATOMIC_OPTIMISTIC` only after Tasks 1-7 are green.
- [ ] Update capability-profile test exact tuple/set.
- [ ] Update clean-artifact Tortoise assertion from 3 capabilities to 5.
- [ ] Do not alter integration ID or standard-extra defaults.

---

## Task 9: Exact-head PR gate

- [ ] Run full repository tests once before final review.
- [ ] Inspect diff for accidental `rakit-core` ORM imports or new transaction ownership.
- [ ] Confirm no dependency/version/release change outside approved scope.
- [ ] Push exact provider head and require all CI jobs green.
- [ ] Squash merge P2.
- [ ] Start P3 Piccolo from updated canonical `main`.

**Expected shipped result after P2:** `persistence.tortoise` advertises read, write, relationships, root-UoW, and atomic optimistic concurrency, with backend-specific affected-row assumptions explicitly proven or fail-closed.
