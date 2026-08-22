# Phase D3 Persistence Adapter Ecosystem Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a real first-party persistence ecosystem around SQLAlchemy ORM, SQLAlchemy Core/Table, Tortoise ORM, Peewee 4 async, Piccolo ORM, Masonite ORM feasibility, and SQLModel compatibility while keeping Rakit core/web backend-neutral and advertising only behaviorally proven capabilities.

**Architecture:** D3 is an umbrella phase delivered in independently reviewable subphases. D3.0 generalizes the adapter subject so persistence resources are not forced to be classes. D3.1 adds SQLAlchemy Core/Table inside `rakit-sqlalchemy`; D3.2 adds Tortoise; D3.3 adds Peewee 4 async; D3.4 adds Piccolo; D3.5 evaluates/implements the maintained Masonite ORM line; D3.6 proves SQLModel compatibility through the existing SQLAlchemy ORM adapter; D3.7 closes packaging, docs, compatibility matrix, and roadmap. SQLAlchemy ORM remains the default throughout.

**Tech Stack:** Python 3.12+, uv workspace, SQLAlchemy 2.0.x, Tortoise ORM 1.1.x, Peewee 4.x official asyncio layer, Piccolo 1.x, maintained `masonite-framework-orm` 3.x line, SQLModel 0.0.x, SQLite/aiosqlite for deterministic contract verification, pytest, Ruff, ty, MkDocs, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-22-phase-d3-persistence-adapter-ecosystem-design.md`

## Global Constraints

- SQLAlchemy ORM remains the default persistence adapter and `rakit[standard]` remains SQLAlchemy-based.
- SQLAlchemy Core lives in the existing `rakit-sqlalchemy` distribution with integration id `persistence.sqlalchemy-core`.
- Tortoise integration id/provider id is exactly `persistence.tortoise`.
- Peewee integration id/provider id is exactly `persistence.peewee`.
- Piccolo integration id/provider id is exactly `persistence.piccolo`.
- Masonite integration id/provider id is `persistence.masonite` only if D3.5 feasibility passes; otherwise no provider is shipped.
- SQLModel uses the existing `persistence.sqlalchemy` provider; do not create a duplicate SQLModel persistence claimant.
- Native backend models/schemas remain native; no Rakit persistence DSL or fake wrapper classes.
- Do not force capability parity.
- Core/web must not import concrete persistence backend APIs.
- Source-first workflow: implement source/package wiring, run non-pytest/manual checks, then add permanent regression/conformance tests.
- If an adapter cannot satisfy a v1 capability without private/brittle APIs or semantic distortion, stop at the highest honest capability set and document the pressure point.
- No release, tag, or publication.
- Every PR merge method is squash.

---

## D3.0 — Persistence Integration Contract & Adapter Subject Generalization

### Task 1: Generalize the adapter claim subject

**Files:**
- Modify: `packages/rakit-core/src/rakit_core/compiler.py`
- Modify resource/admin registration declarations that type persistence subjects as classes.
- Modify focused compiler/registration tests after source verification.

**Produces:** a neutral adapter subject contract accepting `object` while preserving class-based callers.

- [ ] Replace the class-only `AdapterClaim` input with a neutral object-shaped subject contract.
- [ ] Trace every call site that passes a persistence model/subject and remove type assumptions that are not semantically required.
- [ ] Preserve existing explicit adapter selection and ambiguity behavior.
- [ ] Add neutral diagnostic naming that prefers `__name__`, then safe fallbacks; core must not special-case backend types.
- [ ] Manually verify an existing SQLAlchemy declarative model still claims exactly as before.
- [ ] Manually verify an arbitrary non-class object can reach registered claim functions without core rejecting it solely for not being a class.

### Task 2: Strengthen shared persistence conformance seams

**Files:**
- Modify: `packages/rakit-core/src/rakit_core/testing/capability_conformance.py`
- Modify/add focused D1 conformance tests.
- Modify SQLAlchemy conformance harness only where shared v1 semantics become more explicit.

- [ ] Keep the five canonical v1 capability identifiers unchanged.
- [ ] Strengthen behavior assertions only where needed to make SQLAlchemy Core/Tortoise/Peewee/Piccolo/Masonite proofs backend-neutral and comparable.
- [ ] Avoid testing implementation details such as session/connection/query object types.
- [ ] Re-run existing SQLAlchemy ORM conformance and ensure no capability regression.

### Task 3: Expose D3 subphase roadmap structure

**Files:**
- Modify: `docs/roadmap.md`

- [ ] Add D3.0–D3.7 entries under Phase D.
- [ ] Mark only completed landed subphases Complete; D3 overall remains Next/Active until D3.7 closure.
- [ ] Preserve D4.0–D4.6 structure already accepted.

### D3.0 verification and merge

- [ ] Ruff format/check, `ty check`, focused compiler tests, full canonical CI.
- [ ] Exact-head CI green.
- [ ] Squash merge D3.0 PR before later subphases depend on the generalized subject contract.

---

## D3.1 — SQLAlchemy ORM Hardening + SQLAlchemy Core/Table

### Task 4: Add SQLAlchemy Core integration metadata and plugin boundary

**Files:**
- Modify: `packages/rakit-sqlalchemy/src/rakit_sqlalchemy/capabilities.py`
- Modify: `packages/rakit-sqlalchemy/src/rakit_sqlalchemy/discovery.py`
- Create: `packages/rakit-sqlalchemy/src/rakit_sqlalchemy/core_plugin.py`
- Modify: `packages/rakit-sqlalchemy/src/rakit_sqlalchemy/__init__.py`
- Modify: `packages/rakit-sqlalchemy/pyproject.toml`

**Produces:** `SQLALCHEMY_CORE_CAPABILITIES`, `SQLALCHEMY_CORE_INTEGRATION`, `SQLAlchemyCorePlugin`.

- [ ] Keep existing `persistence.sqlalchemy` ORM provider unchanged.
- [ ] Add distinct provider/integration id `persistence.sqlalchemy-core`.
- [ ] Register a Core claim that accepts native `sqlalchemy.Table` objects and never claims ORM mapped classes.
- [ ] Allow SQLAlchemy ORM and Core plugins to coexist when their subjects are unambiguous.
- [ ] Start Core capability advertisement conservatively with only behavior already implemented and manually proven.

### Task 5: Implement SQLAlchemy Core introspection and read datasource

**Files:**
- Create: `packages/rakit-sqlalchemy/src/rakit_sqlalchemy/core_introspection.py`
- Create: `packages/rakit-sqlalchemy/src/rakit_sqlalchemy/core_datasource.py`

- [ ] Introspect native `Table` columns, one scalar PK, nullable/required/type metadata, and writable columns without constructing ORM classes.
- [ ] Reuse neutral `FieldDefinition`, `RecordIdentity`, query, pagination, and security contracts.
- [ ] Implement deterministic list/detail/count with `AsyncEngine`/`AsyncConnection` and SQL Expression Language.
- [ ] Implement page and limit/offset pagination.
- [ ] Implement declared search/filter/sort with fail-closed unsupported field-policy behavior.
- [ ] Translate missing identity and backend failures to portable `RakitError` contracts.
- [ ] Run plain-Python SQLite Core smoke with a real `MetaData`/`Table` before adding permanent tests.

### Task 6: Implement SQLAlchemy Core scalar write and root UoW

**Files:**
- Create: `packages/rakit-sqlalchemy/src/rakit_sqlalchemy/core_uow.py`
- Create: `packages/rakit-sqlalchemy/src/rakit_sqlalchemy/core_mutations.py`
- Create: `packages/rakit-sqlalchemy/src/rakit_sqlalchemy/core_write_provider.py`
- Modify: `packages/rakit-sqlalchemy/src/rakit_sqlalchemy/core_plugin.py`
- Modify: `packages/rakit-sqlalchemy/src/rakit_sqlalchemy/capabilities.py`

- [ ] Implement scalar insert/update/delete against native table columns.
- [ ] Ensure one async connection/transaction owns root commit/rollback.
- [ ] Do not auto-commit inside nested mutation helpers.
- [ ] Advertise `persistence.write` and `transactions.root-uow` only after manual durability/rollback proof.
- [ ] Evaluate atomic optimistic compare-and-write using conditional SQL predicates; advertise only if stale writes are rejected without durability.
- [ ] Do not advertise `persistence.relationships` merely because foreign keys exist.

### Task 7: Add permanent SQLAlchemy Core and ORM regression proof

**Files:**
- Create: `packages/rakit-sqlalchemy/tests/test_core_capability_profile.py`
- Create: `packages/rakit-sqlalchemy/tests/test_core_datasource.py`
- Create: `packages/rakit-sqlalchemy/tests/test_core_conformance.py`
- Add Core write/UoW/concurrency tests only for advertised capabilities.

- [ ] Prove every advertised Core capability through canonical conformance with a real SQLite database.
- [ ] Prove existing ORM provider still advertises and passes its existing five capabilities.
- [ ] Prove ORM and Core plugin claims are mutually unambiguous.

### D3.1 verification and merge

- [ ] Full canonical CI and artifact smoke.
- [ ] Exact-head green.
- [ ] Squash merge D3.1 PR.

---

## D3.2 — Tortoise ORM

### Task 8: Complete the `rakit-tortoise` package foundation

**Files:**
- Existing/new: `packages/rakit-tortoise/pyproject.toml`
- Existing/new: `packages/rakit-tortoise/src/rakit_tortoise/__init__.py`
- Existing: `packages/rakit-tortoise/src/rakit_tortoise/capabilities.py`
- Existing: `packages/rakit-tortoise/src/rakit_tortoise/discovery.py`
- Existing: `packages/rakit-tortoise/src/rakit_tortoise/plugin.py`
- Create/ensure: `packages/rakit-tortoise/src/rakit_tortoise/py.typed`

- [ ] Preserve dependency floor `tortoise-orm>=1.1.7,<2` unless lowest-direct proves a higher floor is genuinely required.
- [ ] Keep provider/integration id `persistence.tortoise`.
- [ ] Claim only native Tortoise model classes.
- [ ] Ensure other backend subjects are not claimed.

### Task 9: Complete Tortoise introspection and read datasource

**Files:**
- Existing: `packages/rakit-tortoise/src/rakit_tortoise/introspection.py`
- Existing: `packages/rakit-tortoise/src/rakit_tortoise/datasource.py`

- [ ] Support one scalar PK representable by `RecordIdentity`.
- [ ] Build neutral field definitions and security inference.
- [ ] Implement deterministic reads, page and limit/offset pagination, detail/not-found, count, declared filter/search/sort.
- [ ] Fail closed on unsupported query policies.
- [ ] Run plain-Python SQLite smoke before permanent tests.

### Task 10: Add Tortoise scalar writes and root UoW if cleanly conforming

**Files:**
- Create: `packages/rakit-tortoise/src/rakit_tortoise/uow.py`
- Create: `packages/rakit-tortoise/src/rakit_tortoise/mutations.py`
- Create: `packages/rakit-tortoise/src/rakit_tortoise/write_provider.py`
- Modify: `packages/rakit-tortoise/src/rakit_tortoise/plugin.py`
- Modify: `packages/rakit-tortoise/src/rakit_tortoise/capabilities.py`

- [ ] Implement one explicit Tortoise transaction context/connection as root UoW.
- [ ] Implement ordinary scalar create/update/delete without hidden independent commit boundaries.
- [ ] Advertise `persistence.write`/`transactions.root-uow` only after manual proof.
- [ ] Evaluate relationships and atomic optimistic concurrency separately; do not force parity.

### Task 11: Add Tortoise permanent conformance and packaging

**Files:**
- Create tests under `packages/rakit-tortoise/tests/`.
- Modify umbrella extras/install/artifact/coverage inventory.
- Update: `uv.lock`.

- [ ] Add `rakit[tortoise]` and official typed artifact inventory.
- [ ] Use real SQLite-backed Tortoise initialization/model schemas.
- [ ] Prove each advertised capability via canonical conformance.
- [ ] Avoid implicit Trio dependency.

### D3.2 verification and merge

- [ ] Full canonical CI including lowest/latest dependency matrices.
- [ ] Exact-head green.
- [ ] Squash merge D3.2 PR.

---

## D3.3 — Peewee 4 Async ORM

### Task 12: Create Peewee package/discovery/plugin

**Files:**
- Create: `packages/rakit-peewee/pyproject.toml`
- Create: `packages/rakit-peewee/src/rakit_peewee/__init__.py`
- Create: `packages/rakit-peewee/src/rakit_peewee/capabilities.py`
- Create: `packages/rakit-peewee/src/rakit_peewee/discovery.py`
- Create: `packages/rakit-peewee/src/rakit_peewee/plugin.py`
- Create: `packages/rakit-peewee/src/rakit_peewee/py.typed`

- [ ] Target Peewee 4.x and its official `playhouse.pwasyncio` async layer.
- [ ] Register `persistence.peewee`.
- [ ] Keep `greenlet` and async drivers adapter/upstream-owned, never core dependencies.
- [ ] Claim only Peewee model classes.

### Task 13: Implement Peewee read datasource

**Files:**
- Create: `packages/rakit-peewee/src/rakit_peewee/introspection.py`
- Create: `packages/rakit-peewee/src/rakit_peewee/datasource.py`

- [ ] Implement scalar identity/field metadata and fail-closed field policy.
- [ ] Execute queries through the official async database execution layer.
- [ ] Implement deterministic list/detail/count, page and limit/offset, filter/search/sort.
- [ ] Translate backend failures to Rakit-neutral errors.
- [ ] Manual SQLite async smoke before tests.

### Task 14: Evaluate Peewee writes/UoW/higher capabilities

**Files:**
- Create only when cleanly supported: `uow.py`, `mutations.py`, `write_provider.py`, `relationships.py`, `concurrency.py`.
- Modify capability profile accordingly.

- [ ] Implement scalar writes through public async database APIs.
- [ ] Prove root transaction ownership before advertising `transactions.root-uow`.
- [ ] Advertise relationships/concurrency only after real conformance.

### Task 15: Add Peewee permanent conformance and packaging

**Files:**
- Add tests under `packages/rakit-peewee/tests/`.
- Modify umbrella extras/install/artifact/coverage inventory.
- Update `uv.lock`.

- [ ] Add `rakit[peewee]`.
- [ ] Prove every advertised capability with real SQLite-backed tests.
- [ ] Add clean-installed smoke.

### D3.3 verification and merge

- [ ] Full canonical CI and exact-head green.
- [ ] Squash merge D3.3 PR.

---

## D3.4 — Piccolo ORM

### Task 16: Create Piccolo package/discovery/plugin

**Files:**
- Create: `packages/rakit-piccolo/pyproject.toml`
- Create: `packages/rakit-piccolo/src/rakit_piccolo/__init__.py`
- Create: `packages/rakit-piccolo/src/rakit_piccolo/capabilities.py`
- Create: `packages/rakit-piccolo/src/rakit_piccolo/discovery.py`
- Create: `packages/rakit-piccolo/src/rakit_piccolo/plugin.py`
- Create: `packages/rakit-piccolo/src/rakit_piccolo/py.typed`

- [ ] Use an explicit supported Piccolo 1.x floor fixed by lowest-direct testing.
- [ ] Register `persistence.piccolo`.
- [ ] Claim only native Piccolo table/model classes.
- [ ] Start capability advertisement conservatively.

### Task 17: Implement Piccolo read datasource

**Files:**
- Create: `packages/rakit-piccolo/src/rakit_piccolo/introspection.py`
- Create: `packages/rakit-piccolo/src/rakit_piccolo/datasource.py`

- [ ] Implement scalar identity/field metadata, deterministic reads, pagination, filter/search/sort, and portable errors.
- [ ] Fail closed on unsupported query behavior.
- [ ] Run real SQLite/manual smoke before tests.

### Task 18: Evaluate Piccolo writes/UoW/higher capabilities

**Files:**
- Create only when cleanly supported: `uow.py`, `mutations.py`, `write_provider.py`, `relationships.py`, `concurrency.py`.
- Modify capability profile accordingly.

- [ ] Implement/advertise only behavior proven against public Piccolo APIs.
- [ ] Avoid private transaction/query internals solely to chase parity.

### Task 19: Add Piccolo packaging and permanent conformance

**Files:**
- Add tests under `packages/rakit-piccolo/tests/`.
- Modify umbrella extras/install/artifact/coverage inventory.
- Update `uv.lock`.

- [ ] Add `rakit[piccolo]`.
- [ ] Add clean-installed artifact smoke.
- [ ] Prove every advertised capability through canonical conformance.

### D3.4 verification and merge

- [ ] Full canonical CI and exact-head green.
- [ ] Squash merge D3.4 PR.

---

## D3.5 — Masonite ORM Feasibility / Adapter

### Task 20: Run maintained Masonite ORM feasibility gate

**Files:**
- Add a design/compatibility note under `docs/superpowers/specs/` only if a significant contract pressure point requires durable documentation.
- No runtime package is created until the gate passes.

- [ ] Evaluate `masonite-framework-orm` current 3.x line; do not depend on legacy unmaintained `masonite-orm`.
- [ ] Verify Python 3.12+ import/runtime support.
- [ ] Verify read/write execution can participate in Rakit's async runtime without event-loop blocking introduced by Rakit.
- [ ] Verify public transaction APIs can support root-UoW semantics before claiming transaction capability.
- [ ] If the gate fails, document the exact reason and finish D3.5 without shipping a false adapter.

### Task 21: Implement Masonite adapter only if feasibility passes

**Files if gate passes:**
- Create `packages/rakit-masonite-orm/` distribution, `rakit_masonite_orm` package, capability/discovery/plugin/introspection/datasource modules, optional write/UoW modules, tests, install/artifact wiring.

- [ ] Register `persistence.masonite`.
- [ ] Add `rakit[masonite-orm]` only when the adapter actually ships.
- [ ] Prove every advertised capability with canonical conformance.

### D3.5 verification and merge

- [ ] Exact-head canonical CI green for either the implemented adapter or documented feasibility rejection.
- [ ] Squash merge D3.5 PR.

---

## D3.6 — SQLModel Compatibility Profile

### Task 22: Prove SQLModel through the SQLAlchemy ORM adapter

**Files:**
- Add: `packages/rakit-sqlalchemy/tests/test_sqlmodel_compatibility.py`
- Modify install/extras tests as needed.

- [ ] Define real SQLModel table models.
- [ ] Prove `SQLAlchemyPlugin` claims them without a second adapter path.
- [ ] Prove representative read, field metadata, generated scalar write, root UoW, and optimistic behavior supported by the underlying SQLAlchemy mapping.
- [ ] Assert configured integration remains `persistence.sqlalchemy`.
- [ ] Add no `rakit-sqlmodel` distribution and no `persistence.sqlmodel` provider.

### Task 23: Add SQLModel convenience install UX

**Files:**
- Modify: `packages/rakit/pyproject.toml`
- Modify: `packages/rakit/src/rakit/_install.py`
- Modify relevant artifact/install smoke scripts/tests.
- Update: `uv.lock`

- [ ] Add `rakit[sqlmodel]` containing `rakit-sqlalchemy` plus a supported SQLModel dependency floor determined by lowest-direct verification.
- [ ] Document that SQLModel uses the SQLAlchemy provider.

### D3.6 verification and merge

- [ ] Lowest-direct/latest SQLModel compatibility and full canonical CI green.
- [ ] Squash merge D3.6 PR.

---

## D3.7 — Persistence Integration DX, Compatibility Matrix & Closure

### Task 24: Publish persistence adapter guide and compatibility matrix

**Files:**
- Create/expand: `docs/guides/persistence-adapters.md`
- Modify: `mkdocs.yml`
- Modify: `docs/roadmap.md`

- [ ] Document SQLAlchemy ORM default and SQLAlchemy Core native `Table` support.
- [ ] Document Tortoise, Peewee, Piccolo, and Masonite outcome/install paths.
- [ ] Document SQLModel as a compatibility profile rather than a provider.
- [ ] Publish a matrix for all five persistence/transaction/concurrency canonical capabilities showing only verified claims.
- [ ] Record deferred non-relational directions: MongoDB/Beanie, Turso/libSQL, CouchDB; retain them for D6/contract research.
- [ ] Record Django ORM async transaction mismatch as a deliberate deferral.

### Task 25: Final artifact/install/discovery consistency

**Files:**
- Modify relevant `packages/rakit/tests/` install/discovery tests.
- Modify `scripts/check_artifacts.py` if needed.
- Modify root/package metadata only for consistency fixes.

- [ ] Verify all official distributions are counted correctly.
- [ ] Verify every shipped integration entry point resolves from clean-built wheels.
- [ ] Verify extras do not silently change the default provider.
- [ ] Verify simultaneous installation is deterministic and ambiguous subjects fail closed.

### Task 26: Close D3 and hand off D4

**Files:**
- Modify: `docs/roadmap.md`

- [ ] Mark D3.0–D3.7 Complete only for landed verified work; a documented Masonite feasibility rejection counts as completed D3.5 if no adapter can honestly ship.
- [ ] Mark Phase D3 overall Complete.
- [ ] Mark D4 / D4.0 Web Integration Contract Next.
- [ ] Run Ruff format/check, `ty check`, full pytest/coverage, strict MkDocs, artifact checks, clean-install smoke, lowest/latest dependency jobs, Python 3.12/3.13/3.14 jobs.
- [ ] Audit changed files for temporary helpers/workflows.
- [ ] Require exact-head canonical CI success.
- [ ] Squash merge the D3.7 closure PR.
