# Peewee Async ORM Persistence Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise `persistence.peewee` from 3/5 to truthful 5/5 while explicitly tightening the optional Peewee floor to the first stable async line that can prove global atomic stale-write behavior.

**Architecture:** Keep Peewee query/model construction native and execute database I/O only through the supported async database/bridge APIs. Use one conditional UPDATE/DELETE with affected-row observation for optimistic concurrency, documented `Model._meta`/FK/backref/through-model metadata for relationships, explicit intermediary models for association objects, and the existing `PeeweeUnitOfWork` as the sole atomic boundary.

**Tech Stack:** proposed `peewee>=4.0.8,<5`, `playhouse.pwasyncio`, SQLite/aiosqlite, PostgreSQL/asyncpg, MySQL/aiomysql, Python 3.12-3.14, pytest/anyio, uv, ruff, ty.

**Spec:** `docs/superpowers/specs/2026-08-23-persistence-capability-parity-design.md`

## Global Constraints

- Start after P3 is squash-merged; branch from canonical `main`, recommended `parity-p4-peewee`.
- The floor change from 4.0.2 to 4.0.8 is an explicit parity compatibility decision, not cleanup.
- Do not advertise atomic concurrency on evidence from SQLite alone.
- Avoid accidental synchronous lazy relationship I/O outside Peewee's supported async bridge.
- Prefer explicit async through-model DML for M2M writes.
- Rich association objects require explicit intermediary models with supported scalar identity.
- Source-first workflow; permanent tests after source/runtime verification; capability profile last.

---

## Task 1: Tighten the Peewee dependency floor explicitly

**Files:**
- Modify: `packages/rakit-peewee/pyproject.toml`
- Modify: `uv.lock`
- Modify docs only where the supported Peewee range is stated, likely `docs/guides/persistence-adapters.md` during P4 or P5 depending existing ownership.

- [ ] Change runtime dependency from `peewee>=4.0.2,<5` to `peewee>=4.0.8,<5`.
- [ ] Add `asyncpg` and `aiomysql` only to the appropriate development/test dependency group if the backend proof jobs require direct installation and they are not already available transitively. Do not add them to end-user runtime requirements unless Peewee's actual adapter install contract requires them.
- [ ] Refresh `uv.lock` with the normal repository command and inspect the lock diff to ensure the floor change is the intended cause.
- [ ] Do not change Rakit package versions.

Verification:

```bash
uv lock
uv sync --all-packages --dev --locked
uv run python - <<'PY'
from importlib.metadata import version
print(version("peewee"))
PY
```

- [ ] Confirm lowest-direct resolution chooses Peewee >=4.0.8.

---

## Task 2: Enable one-statement optimistic concurrency in generated CRUD

**Files:**
- Modify: `packages/rakit-peewee/src/rakit_peewee/generated.py`
- Create if useful: `packages/rakit-peewee/src/rakit_peewee/concurrency.py`

- [ ] Accept either no concurrency configuration or a complete neutral provider/token pair; reject partial configuration.
- [ ] Store provider/token service on the executor and set `atomic_concurrency=True` only once the final path is conditional.
- [ ] Load the current scoped row through the async database for initial not-found and token verification.
- [ ] Translate expected predicate fields to known Peewee fields and fail closed for unknown fields.
- [ ] Build one `Model.update(...)` whose WHERE contains identity + expected state.
- [ ] For integer version-column concurrency, write `Model.version + 1` in the same UPDATE.
- [ ] Execute with the supported async database/query path (`database.aexecute(...)` or the stable query-level async API chosen consistently for the package).
- [ ] Interpret affected rows `1` as success and `0` after successful initial validation as `RESOURCE_CONFLICT`.
- [ ] Reload the updated record through the async database.
- [ ] Build conditional DELETE with identity + expected state and classify stale zero-row delete as conflict.
- [ ] Keep non-concurrency generated CRUD behavior unchanged for resources without a provider.

**Non-test verification:**

- [ ] Run compileall and ruff for touched source.
- [ ] Run throwaway async SQLite conditional update/delete smoke under Peewee 4.0.8+.
- [ ] Confirm no model attribute access in the smoke triggers database I/O outside the supported async path.

---

## Task 3: Add documented Peewee relationship introspection/validation

**Files:**
- Create: `packages/rakit-peewee/src/rakit_peewee/relationships.py`
- Modify: `packages/rakit-peewee/src/rakit_peewee/datasource.py`
- Modify only if useful for shared model metadata: `packages/rakit-peewee/src/rakit_peewee/introspection.py`

- [ ] Use documented `Model._meta` and field metadata; do not descend into undocumented implementation internals merely because `_meta` begins with an underscore.
- [ ] Map `ForeignKeyField` to many-to-one and documented backrefs to one-to-many.
- [ ] Treat a relation as O2O only when native uniqueness is proven (`ForeignKeyField(unique=True)` or an equivalent verifiable unique constraint).
- [ ] Recognize native M2M through its public through/intermediary model surface.
- [ ] For rich association object, require an explicit intermediary model with supported scalar primary key and explicit scalar fields.
- [ ] Validate named FK/backref edge to handle multiple FKs to the same target without first-match guessing.
- [ ] Validate explicit position field for writable ordering.
- [ ] Add datasource `relationship_metadata` and `validate_relationship(...)` using the existing compiler seam.
- [ ] Reject incompatible datasource/target types, composite-only association identities, or unsupported inherited M2M shapes.
- [ ] Keep Peewee `on_delete`/`on_update` independent from Rakit destructive permission.

**Non-test verification:**

- [ ] Define throwaway models for FK/backref, unique FK, M2M, explicit Membership association, ordering, multiple FKs, and a composite-PK junction rejection case.
- [ ] Call `validate_relationship(...)` directly and verify named-edge disambiguation.

---

## Task 4: Implement async-safe relationship state/mutations

**Files:**
- Create: `packages/rakit-peewee/src/rakit_peewee/relationship_mutations.py`
- Modify as needed: `packages/rakit-peewee/src/rakit_peewee/datasource.py`

- [ ] Implement scoped parent/target resolution through explicit async database queries; never rely on implicit lazy relationship access from the UI/transport layer.
- [ ] Implement neutral `editor_page`, `issue_concurrency_token`, and `reorder_identities` output.
- [ ] Implement singular FK SET/CLEAR through explicit conditional UPDATE.
- [ ] Implement reverse collection link/unlink by updating the child FK.
- [ ] Implement M2M link/unlink/clear using explicit async INSERT/DELETE against the through model. Do not make synchronous-looking `.add()`/`.remove()` the initial correctness path.
- [ ] Implement association-object create/update/delete using the explicit intermediary model and scalar allow-list.
- [ ] Implement reorder with explicit position-field UPDATEs.
- [ ] For reads requiring related data, use joined queries, `database.aprefetch(...)`, stable query async execution, or the documented bridge rather than unbridged lazy access.
- [ ] Resolve every target through its scoped datasource before linking.
- [ ] Keep all graph writes in the same asyncio task / database atomic UoW; no independent `atomic()` block may commit outside `PeeweeUnitOfWork`.
- [ ] Apply parent/child/association concurrency so stale state rolls back the whole graph mutation.
- [ ] Enforce Rakit destructive policy independently from Peewee cascade configuration.

**Non-test verification:**

- [ ] Run direct async smoke for FK set/clear, backref link/unlink, M2M link/unlink, association scalar update, and reorder.
- [ ] Exercise the smoke with Python warnings/error handling that makes accidental `MissingGreenletBridge`/sync I/O failures visible.
- [ ] Force a graph failure and verify root atomic rollback.

---

## Task 5: Add focused permanent atomic-concurrency tests

**Files:**
- Create: `packages/rakit-peewee/tests/test_peewee_concurrency.py`
- Modify: `packages/rakit-peewee/tests/test_peewee_capability_conformance.py`

- [ ] Successful conditional update advances integer version.
- [ ] Stale update -> `RESOURCE_CONFLICT`.
- [ ] Initial missing row -> `RESOURCE_NOT_FOUND`.
- [ ] Wrong token resource/identity/version -> conflict.
- [ ] Conditional delete succeeds only for expected version; stale delete leaves current row.
- [ ] Later UoW failure rolls back an earlier successful conditional update.
- [ ] Extend `assert_atomic_optimistic_semantics()` only after focused tests pass.

```bash
uv run pytest packages/rakit-peewee/tests/test_peewee_concurrency.py -q
uv run pytest packages/rakit-peewee/tests/test_peewee_capability_conformance.py -q
```

---

## Task 6: Add focused permanent relationship tests

**Files:**
- Create: `packages/rakit-peewee/tests/test_peewee_relationships.py`
- Modify: `packages/rakit-peewee/tests/test_peewee_capability_conformance.py`

- [ ] Cover FK/backref, unique-FK O2O, native M2M through model, explicit association model, ordering, multiple FKs, and rejected composite/unsupported shapes.
- [ ] Cover scoped candidate rejection.
- [ ] Cover SET/CLEAR, reverse link/unlink, M2M link/unlink/clear, duplicate behavior, association scalar edit, reorder, and allowed destructive path.
- [ ] Cover destructive denial despite native cascade metadata.
- [ ] Cover graph rollback and stale parent/association conflict with no partial durability.
- [ ] Include a regression that relationship editor/read code performs no accidental lazy synchronous I/O.
- [ ] Extend `assert_relationship_semantics()` with the representative neutral behavior matrix.

```bash
uv run pytest packages/rakit-peewee/tests/test_peewee_relationships.py -q
uv run pytest packages/rakit-peewee/tests/test_peewee_capability_conformance.py -q
```

---

## Task 7: Prove affected-row behavior across the async DB matrix

**Files:**
- Add focused backend tests/fixtures under `packages/rakit-peewee/tests/` if useful, for example a clearly named DB-matrix module rather than mixing external service setup into unit tests.
- Modify: `.github/workflows/ci.yml` to add the smallest practical PostgreSQL + MySQL service job or matrix required for Peewee parity.

- [ ] SQLite/aiosqlite: prove matched update=1, stale update=0, matched delete=1, stale delete=0.
- [ ] PostgreSQL/asyncpg: prove the same cases on Peewee 4.0.8 minimum and latest allowed 4.x. This is the regression that justifies the floor bump.
- [ ] MySQL/aiomysql: prove the same cases, including the integer version advancement path so success does not depend on ambiguous no-op changed-row behavior.
- [ ] Keep test schemas minimal and disposable; do not introduce migration-framework coupling.
- [ ] If one backend cannot satisfy deterministic affected-row semantics at the approved floor, stop capability promotion and document the blocker rather than add dynamic per-database capability advertising as a shortcut.

CI secrets should not be required for local service containers. Use ephemeral GitHub Actions service databases or repository-standard test infrastructure; never embed production credentials.

---

## Task 8: Run lowest/latest compatibility with the new floor

- [ ] Run normal locked package suite.
- [ ] Run `uv sync --all-packages --dev --resolution lowest-direct` and verify installed Peewee is >=4.0.8.
- [ ] Run the Peewee tests at lowest-direct, including external DB matrix where the CI job supports it.
- [ ] Run `uv sync --all-packages --dev --upgrade` and repeat relevant tests.
- [ ] Run Python 3.12/3.13/3.14 in CI through the existing primary matrix.
- [ ] Restore normal `uv.lock`/environment after compatibility-only commands; commit only the intentional floor-driven lock change.
- [ ] Run ruff format/check and `ty check`.

---

## Task 9: Promote Peewee capability profile last

**Files:**
- Modify: `packages/rakit-peewee/src/rakit_peewee/capabilities.py`
- Modify: `packages/rakit-peewee/tests/test_peewee_capability_profile.py`
- Modify: `.github/workflows/ci.yml` clean-install Peewee capability assertion
- Modify persistence dependency documentation if not already changed in Task 1

- [ ] Add `PERSISTENCE_RELATIONSHIPS` and `CONCURRENCY_ATOMIC_OPTIMISTIC` only after SQLite + asyncpg + aiomysql gates and Tasks 1-8 are green.
- [ ] Update exact profile expectation to 5 capabilities.
- [ ] Update artifact clean-install assertion.
- [ ] Ensure docs explicitly state `peewee>=4.0.8,<5` as the supported parity line.

---

## Task 10: Exact-head PR gate

- [ ] Run `uv sync --all-packages --dev --locked`.
- [ ] Run full `packages/rakit-peewee/tests`.
- [ ] Run full repository `uv run pytest`.
- [ ] Run `uv run ruff format --check .`, `uv run ruff check .`, `uv run ty check`.
- [ ] Inspect `uv.lock` and dependency diff for only approved changes.
- [ ] Verify no lazy-sync workaround or thread wrapper leaked into core.
- [ ] Push exact provider head and require all CI jobs, including new backend proof, green.
- [ ] Squash merge P4.
- [ ] Begin P5 closure from updated canonical `main`.

**Expected shipped result after P4:** `persistence.peewee` truthfully advertises all five canonical persistence capabilities on the explicit `peewee>=4.0.8,<5` line with SQLite, asyncpg, and aiomysql stale-write behavior proven.
