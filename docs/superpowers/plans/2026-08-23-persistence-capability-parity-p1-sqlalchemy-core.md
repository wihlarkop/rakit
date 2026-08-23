# SQLAlchemy Core Persistence Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise `persistence.sqlalchemy-core` from read/write/root-UoW to truthful 5/5 by adding atomic optimistic concurrency and neutral relationship metadata/mutations over native SQLAlchemy `Table` objects.

**Architecture:** Keep Core schema-centric. Use SQL expressions, `Table`/FK/constraint metadata, `AsyncConnection`, and `SQLAlchemyCoreUnitOfWork`; never manufacture ORM mappings. Add adapter-local mapping-aware concurrency and relationship binding/mutation services. Preserve the compiler's existing datasource `validate_relationship(...)` seam and the existing neutral relationship mutation plans.

**Tech Stack:** SQLAlchemy `sqlalchemy[asyncio]>=2.0.16,<2.1`, asyncio, SQLite contract backend plus dialect/runtime proof as required, pytest/anyio, uv, ruff, ty.

**Spec:** `docs/superpowers/specs/2026-08-23-persistence-capability-parity-design.md`

## Global Constraints

- Work from canonical `main` after the planning branch is approved; recommended branch: `parity-p1-sqlalchemy-core`.
- Do not change SQLAlchemy ORM semantics while adding Core behavior.
- Do not add a fake mapped class for `Table`.
- Do not use `Table.info`, constraint names, or “first matching FK” as hidden Rakit relationship configuration.
- Atomic success uses sane rowcount; do not switch Core to RETURNING merely to imitate Piccolo.
- Capability profile update is the final source change after permanent proof.
- Follow source-first workflow: source -> non-test verification -> permanent tests.

---

## Task 1: Add mapping-aware concurrency primitives

**Files:**
- Create: `packages/rakit-sqlalchemy/src/rakit_sqlalchemy/core_concurrency.py`
- Modify: `packages/rakit-sqlalchemy/src/rakit_sqlalchemy/core_generated.py`

- [ ] Add an adapter-local `MappingVersionProvider` (or equivalently named focused helper) implementing `ConcurrencyVersionProvider` for Core mapping/dict records.
- [ ] Support the same narrow safe version strategies required by the neutral provider: version lookup, predicate values, and next values without importing SQLAlchemy types into core.
- [ ] Keep integer version-column advancement as the first implementation target. If a generic passed provider returns next values, translate them to SQL expression-safe values only when the provider contract can be honored atomically.
- [ ] Add a helper in `core_generated.py` that converts provider predicate keys to known Core columns and fails with `CONFIG_INVALID` for unknown/non-writable predicate fields rather than building arbitrary SQL.
- [ ] Preserve scalar identity validation from the current executor.

**Non-test verification:**

- [ ] Run `uv run python -m compileall packages/rakit-sqlalchemy/src/rakit_sqlalchemy`.
- [ ] Run `uv run ruff check packages/rakit-sqlalchemy/src/rakit_sqlalchemy/core_concurrency.py packages/rakit-sqlalchemy/src/rakit_sqlalchemy/core_generated.py`.
- [ ] Use a short plain-Python SQLite async smoke to construct a mapping row and confirm version/predicate/next-value extraction is deterministic.

---

## Task 2: Make generated Core UPDATE/DELETE genuinely atomic

**Files:**
- Modify: `packages/rakit-sqlalchemy/src/rakit_sqlalchemy/core_generated.py`

- [ ] Change `SQLAlchemyCoreGeneratedResourceExecutorProvider.build()` to accept a matched pair of `context.concurrency_provider` + `context.concurrency_tokens`; reject half-configured concurrency.
- [ ] Store the neutral provider/token service on the built executor when configured.
- [ ] Set `OperationExecutorCapabilities.atomic_concurrency=True` for an executor whose implementation contains the atomic path; keep `participates_in_uow=True`.
- [ ] On UPDATE, perform the existing scoped/current read only for initial not-found and token verification/conflict context. The final SQL UPDATE must include both identity predicates and `concurrency_provider.predicate_values_for(current)`.
- [ ] Merge user input with `next_values_for(current)` in one UPDATE; version advancement must not be a second statement.
- [ ] Before using `CursorResult.rowcount` as the success detector, require `result.supports_sane_rowcount()` (or the public equivalent available on the supported SQLAlchemy line). If sane rowcount cannot be guaranteed, fail closed with a configuration/runtime error rather than downgrade atomicity.
- [ ] Interpret exactly one matched row as success. Zero rows after successful initial validation is `RESOURCE_CONFLICT`, not `RESOURCE_NOT_FOUND`.
- [ ] On DELETE, apply the same identity + expected-state predicate in one DELETE and classify zero rows after initial validation as conflict.
- [ ] Reload the updated record through the same root connection before returning.
- [ ] Keep events deferred through the existing operation/UoW publisher.

**Non-test verification:**

- [ ] Run a throwaway SQLite async script: create row version=1, perform conditional update to version=2, then repeat with expected version=1 and verify the second mutation affects zero rows.
- [ ] In the same script, prove the stale delete leaves the current row intact.
- [ ] Inspect the emitted SQL or compiled statement to verify the final WHERE contains both identity and version predicate.

---

## Task 3: Add Core relationship physical binding and introspection

**Files:**
- Create: `packages/rakit-sqlalchemy/src/rakit_sqlalchemy/core_relationships.py`
- Modify: `packages/rakit-sqlalchemy/src/rakit_sqlalchemy/core_datasource.py`

- [ ] Model adapter-local physical relation facts without exposing SQLAlchemy objects through `rakit-core` types.
- [ ] Inspect `Table.foreign_keys`, `ForeignKeyConstraint`, PK/unique constraints, and association tables using public SQLAlchemy schema APIs.
- [ ] Map supported shapes to neutral `RelationshipMetadata`: many-to-one, one-to-many, one-to-one only when uniqueness is proven, many-to-many through an explicit bridge table, and association-object eligibility for an explicit registered association resource.
- [ ] Add an explicit Core physical-binding object/config seam for ambiguous paths. A unique compatible FK path may auto-bind; zero compatible paths fail; multiple compatible paths require explicit binding.
- [ ] Do not use constraint name or declaration order as the binding identity.
- [ ] Add `SQLAlchemyCoreDataSource.relationship_metadata` and `validate_relationship(...)` with the same observable compiler contract as ORM datasource, while requiring compatible Core datasource targets.
- [ ] Validate ordering only when `RelationshipDefinition.ordering.position_field` names an explicit writable scalar field on the child/association resource; schema default order is not writable ordering proof.
- [ ] Treat database cascade facts as metadata only; Rakit destructive policy remains authoritative.

**Non-test verification:**

- [ ] Construct native `Table` fixtures for: unique FK, reverse FK, unique FK O2O, bridge M2M, association table/resource, and two-FK ambiguity.
- [ ] Call `validate_relationship(...)` directly for each shape and confirm ambiguity fails until explicit binding is supplied.
- [ ] Confirm no ORM mapper/session import appears in the new Core relationship module.

---

## Task 4: Implement scoped Core relationship read/mutation service

**Files:**
- Create: `packages/rakit-sqlalchemy/src/rakit_sqlalchemy/core_relationship_mutations.py`
- Modify as needed: `packages/rakit-sqlalchemy/src/rakit_sqlalchemy/core_datasource.py`
- Modify as needed: `packages/rakit-sqlalchemy/src/rakit_sqlalchemy/core_uow.py`

- [ ] Implement a Core relationship resolver that resolves parent/target identities through datasource-owned scoped statements and the active `AsyncConnection` where mutation is in progress.
- [ ] Implement the neutral editor/read methods required by `RelationshipEditorStateProvider`: `editor_page`, `issue_concurrency_token`, and `reorder_identities` for supported shapes.
- [ ] Implement `RelationshipChangePlan` / `RelationshipMutationPlan` execution for SET/CLEAR/LINK/UNLINK, collection ADD/REMOVE/REPLACE where the neutral plan calls for them, association scalar updates, and reorder.
- [ ] Use explicit INSERT/UPDATE/DELETE against the FK or bridge/association table; do not synthesize ORM collection behavior.
- [ ] Resolve every target candidate against its target datasource scope before linking.
- [ ] For association objects, require an explicitly registered association resource with supported scalar identity; do not silently treat an unregistered bridge row as a Rakit association resource.
- [ ] Apply explicit position-field updates for reorder and keep ordering deterministic.
- [ ] Execute the entire graph mutation through the existing `SQLAlchemyCoreUnitOfWork` connection. No service method may call `engine.begin()` or independently commit.
- [ ] Apply parent concurrency before durable graph changes and classify stale parent/association state as conflict without partial durability.
- [ ] Enforce compiled destructive permissions; schema FK cascades never authorize child delete.

**Non-test verification:**

- [ ] Run direct service smoke for singular set/clear, M2M link/unlink, association scalar update, and reorder inside one Core UoW.
- [ ] Force a failure after an earlier graph step and verify transaction rollback restores all affected tables.
- [ ] Use a hidden/scoped-out target fixture and verify link resolution refuses it.

---

## Task 5: Add focused permanent atomic-concurrency regression coverage

**Files:**
- Create: `packages/rakit-sqlalchemy/tests/test_core_concurrency.py`
- Modify: `packages/rakit-sqlalchemy/tests/test_core_capability_conformance.py`
- Modify if needed: `packages/rakit-sqlalchemy/tests/test_core_table_write.py`

- [ ] Cover successful version-column UPDATE and version advancement.
- [ ] Cover stale UPDATE race -> `RESOURCE_CONFLICT`.
- [ ] Cover successful conditional DELETE and stale DELETE -> conflict.
- [ ] Cover initial missing identity -> `RESOURCE_NOT_FOUND`.
- [ ] Cover token bound to wrong identity/resource/version -> conflict.
- [ ] Cover rollback after a successful conditional UPDATE when later operation work raises.
- [ ] Cover fail-closed behavior when rowcount is not sane using a controlled result/dialect test seam; do not monkey-patch production semantics broadly.
- [ ] Extend the Core capability conformance harness's `assert_atomic_optimistic_semantics()` only after the focused source tests pass.

Run:

```bash
uv run pytest packages/rakit-sqlalchemy/tests/test_core_concurrency.py -q
uv run pytest packages/rakit-sqlalchemy/tests/test_core_capability_conformance.py -q
```

---

## Task 6: Add focused permanent relationship regression coverage

**Files:**
- Create: `packages/rakit-sqlalchemy/tests/test_core_relationship_introspection.py`
- Create: `packages/rakit-sqlalchemy/tests/test_core_relationship_mutations.py`
- Modify: `packages/rakit-sqlalchemy/tests/test_core_capability_conformance.py`

- [ ] Test metadata/validation for many-to-one, one-to-many, O2O unique proof, M2M bridge, association resource, self-reference if supported, ordering, and ambiguity.
- [ ] Test scoped candidate resolution.
- [ ] Test singular set/clear, collection link/unlink, bridge duplicate behavior, association scalar update, reorder, and allowed destructive path.
- [ ] Test forbidden destructive path even when FK cascade exists.
- [ ] Test graph commit and rollback.
- [ ] Test stale parent and stale association/child path produce conflict with no partial graph durability.
- [ ] Extend `assert_relationship_semantics()` in the Core capability conformance harness to exercise the neutral representative set, not every SQLAlchemy schema trick.

Run:

```bash
uv run pytest packages/rakit-sqlalchemy/tests/test_core_relationship_introspection.py -q
uv run pytest packages/rakit-sqlalchemy/tests/test_core_relationship_mutations.py -q
uv run pytest packages/rakit-sqlalchemy/tests/test_core_capability_conformance.py -q
```

---

## Task 7: Prove SQLAlchemy ORM coexistence and package stability

**Files:**
- Existing tests only unless a regression requires a focused assertion:
  - `packages/rakit-sqlalchemy/tests/test_orm_core_coexistence.py`
  - `packages/rakit-sqlalchemy/tests/test_concurrency.py`
  - `packages/rakit-sqlalchemy/tests/test_relationship_introspection.py`
  - `packages/rakit-sqlalchemy/tests/test_relationship_mutations.py`
  - `packages/rakit-sqlalchemy/tests/test_graph_mutations.py`

- [ ] Run the full `rakit-sqlalchemy` package suite.
- [ ] Confirm ORM provider remains 5/5 and Core changes did not alter ORM mapper/session paths.
- [ ] Run lowest-direct and latest-allowed dependency resolutions for SQLAlchemy package behavior.

```bash
uv run pytest packages/rakit-sqlalchemy/tests -q
uv sync --all-packages --dev --resolution lowest-direct
uv run --no-sync pytest packages/rakit-sqlalchemy/tests -q
uv sync --all-packages --dev --upgrade
uv run --no-sync pytest packages/rakit-sqlalchemy/tests -q
```

Restore the repository's normal locked environment before committing any lockfile generated only for a temporary compatibility check.

---

## Task 8: Promote Core capability profile last

**Files:**
- Modify: `packages/rakit-sqlalchemy/src/rakit_sqlalchemy/capabilities.py`
- Modify: `packages/rakit-sqlalchemy/tests/test_capability_profile.py`
- Modify: `packages/rakit-sqlalchemy/tests/test_plugin_capabilities.py` if it asserts exact Core names
- Modify: `.github/workflows/ci.yml` only if an artifact assertion names the Core capability set explicitly

- [ ] Add `PERSISTENCE_RELATIONSHIPS` and `CONCURRENCY_ATOMIC_OPTIMISTIC` to `SQLALCHEMY_CORE_CAPABILITIES` only after Tasks 1-7 are green.
- [ ] Update exact capability-profile expectations.
- [ ] Do not change ORM provider IDs/names or standard-extra behavior.

Run:

```bash
uv run pytest packages/rakit-sqlalchemy/tests/test_capability_profile.py packages/rakit-sqlalchemy/tests/test_plugin_capabilities.py -q
```

---

## Task 9: Final verification and PR gate

- [ ] Run `uv sync --all-packages --dev --locked`.
- [ ] Run `uv run ruff format --check .`.
- [ ] Run `uv run ruff check .`.
- [ ] Run `uv run ty check`.
- [ ] Run `uv run pytest packages/rakit-sqlalchemy/tests -q`.
- [ ] Run full `uv run pytest` before final PR approval.
- [ ] Verify `git diff` contains no ORM-to-core leakage, no release/version changes, and no unrelated refactor.
- [ ] Push provider branch and require exact-head CI green.
- [ ] Squash merge P1.
- [ ] Refresh P2 Tortoise work from canonical `main`.

**Expected shipped result after P1:** `persistence.sqlalchemy-core` truthfully advertises read, write, relationships, root-UoW, and atomic optimistic concurrency.
