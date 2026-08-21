# Phase D3 Persistence Adapter Ecosystem Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prove Rakit's persistence ecosystem with a materially different first-party Tortoise ORM adapter while preserving SQLAlchemy as the default and advertising only behaviorally proven capabilities.

**Architecture:** Add `rakit-tortoise` as an independent package on `rakit-core`. Native Tortoise models are claimed through the existing adapter registry. Reads, scalar writes, and transaction ownership use neutral Rakit contracts; relationship and optimistic capabilities are implemented only if the v1 contracts can be proven cleanly.

**Tech Stack:** Python 3.12+, uv workspace, Tortoise ORM 1.1.x, SQLite/aiosqlite for contract verification, pytest, Ruff, ty, MkDocs, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-22-phase-d3-persistence-adapter-ecosystem-design.md`

## Global Constraints

- SQLAlchemy remains the default persistence adapter.
- Tortoise integration id/provider id is exactly `persistence.tortoise`.
- Use native `tortoise.models.Model`; no Rakit persistence DSL.
- Do not force capability parity.
- Core/web must not import concrete SQLAlchemy or Tortoise persistence APIs.
- Source-first workflow: implement source/package wiring, run non-pytest/manual checks, then add permanent regression/conformance tests.
- No release, tag, or publication.
- Final merge method: squash.

---

### Task 1: Create the Tortoise package and discovery surface

**Files:**
- Create: `packages/rakit-tortoise/pyproject.toml`
- Create: `packages/rakit-tortoise/src/rakit_tortoise/__init__.py`
- Create: `packages/rakit-tortoise/src/rakit_tortoise/capabilities.py`
- Create: `packages/rakit-tortoise/src/rakit_tortoise/discovery.py`
- Create: `packages/rakit-tortoise/src/rakit_tortoise/py.typed`

**Produces:** `TORTOISE_CAPABILITIES`, `TORTOISE_INTEGRATION`, typed package metadata, `rakit.integrations` entry point.

- [ ] Add package metadata with `rakit-core==0.1.0a1` and `tortoise-orm>=1.1.7,<2`.
- [ ] Start capability advertisement conservatively with `persistence.read` only.
- [ ] Add deterministic discovery descriptor `persistence.tortoise`.
- [ ] Verify source imports/metadata manually before adding tests.

### Task 2: Implement native model introspection and read datasource

**Files:**
- Create: `packages/rakit-tortoise/src/rakit_tortoise/introspection.py`
- Create: `packages/rakit-tortoise/src/rakit_tortoise/datasource.py`

**Consumes:** `ResourceFieldPolicy`, `FieldDefinition`, `RecordIdentity`, `ResourceQuery`, Rakit pagination result types.

**Produces:** `TortoiseDataSource` implementing the neutral `DataSource` protocol.

- [ ] Detect only real Tortoise model subclasses; reject unsupported/no scalar PK models at claim time.
- [ ] Build ordered concrete-field metadata and neutral `FieldDefinition` values.
- [ ] Implement deterministic detail lookup and translate not-found to `RakitError`.
- [ ] Implement page and limit/offset list pagination.
- [ ] Implement declared search/filter/sort with fail-closed field-policy validation.
- [ ] Keep unsupported custom/JSON/binary query semantics out of advertised field policy.
- [ ] Run source import/manual SQLite smoke before permanent tests.

### Task 3: Add plugin claim and configured integration

**Files:**
- Create: `packages/rakit-tortoise/src/rakit_tortoise/plugin.py`
- Modify: `packages/rakit-tortoise/src/rakit_tortoise/__init__.py`

**Produces:** `TortoisePlugin` registering capability provider, configured integration, and adapter claim.

- [ ] Claim only native Tortoise model classes.
- [ ] Return `ResourceAdapterRuntime(data_source=...)` for read-capable resources.
- [ ] Ensure SQLAlchemy models are not claimed and Tortoise/SQLAlchemy may coexist.
- [ ] Verify `ApplicationBuilder.configured_integrations` manually.

### Task 4: Implement scalar write service and root UoW if cleanly conforming

**Files:**
- Create: `packages/rakit-tortoise/src/rakit_tortoise/uow.py`
- Create: `packages/rakit-tortoise/src/rakit_tortoise/mutations.py`
- Create: `packages/rakit-tortoise/src/rakit_tortoise/write_provider.py`
- Modify: `packages/rakit-tortoise/src/rakit_tortoise/plugin.py`
- Modify: `packages/rakit-tortoise/src/rakit_tortoise/capabilities.py`

**Produces:** ordinary scalar create/update/delete and one-root transaction ownership.

- [ ] Implement an operation UoW over one explicit Tortoise transaction connection/context.
- [ ] Ensure rollback on exception and no nested independent commit.
- [ ] Implement scalar create/update/delete against writable field metadata.
- [ ] Build write service through `ResourceWriteServiceProvider` only if it satisfies the neutral web/generated write expectations.
- [ ] Manually prove durability/rollback before advertising `persistence.write` or `transactions.root-uow`.
- [ ] If the existing write-service interface is SQLAlchemy-shaped in a way that requires hacks, stop at read capability and record the pressure-test finding instead of faking parity.

### Task 5: Evaluate relationship and optimistic capabilities

**Files:**
- Modify only if implemented: `packages/rakit-tortoise/src/rakit_tortoise/relationships.py`
- Modify only if implemented: `packages/rakit-tortoise/src/rakit_tortoise/concurrency.py`
- Modify: `packages/rakit-tortoise/src/rakit_tortoise/capabilities.py`

- [ ] Evaluate foreign-key and collection semantics against `persistence.relationships@v1`.
- [ ] Evaluate atomic conditional compare-and-write against `concurrency.atomic-optimistic@v1`.
- [ ] Advertise a capability only when the real adapter passes the canonical behavior seam without private/brittle APIs.
- [ ] Document intentional non-parity rather than adding compatibility hacks.

### Task 6: Wire install UX, workspace, and artifact inventory

**Files:**
- Modify: `packages/rakit/pyproject.toml`
- Modify: `packages/rakit/src/rakit/_install.py`
- Modify: `pyproject.toml`
- Modify: `scripts/check_artifacts.py`
- Modify relevant install/discovery tests after source verification.
- Update: `uv.lock`

- [ ] Add `rakit[tortoise]` convenience extra and workspace source.
- [ ] Keep `standard` SQLAlchemy-based.
- [ ] Add Tortoise distribution to official artifact inventory and coverage source.
- [ ] Update clean-install/extras inventory expectations.
- [ ] Regenerate lockfile.

### Task 7: Add permanent regression and conformance proof

**Files:**
- Create: `packages/rakit-tortoise/tests/test_capability_profile.py`
- Create: `packages/rakit-tortoise/tests/test_datasource.py`
- Create: `packages/rakit-tortoise/tests/test_conformance.py`
- Add write/UoW tests only for capabilities actually advertised.
- Modify SQLAlchemy capability/conformance tests only where D3 strengthens shared semantics.

- [ ] Prove every advertised capability through `run_integration_conformance` using a real SQLite-backed Tortoise harness.
- [ ] Test deterministic read ordering, detail/not-found, page and limit/offset behavior, filters/search/sort.
- [ ] Test native-model rejection boundaries and configured integration discovery.
- [ ] If write/root-UoW is advertised, prove durable CRUD and rollback behavior.
- [ ] Ensure no tests implicitly require Trio unless Trio is explicitly part of the supported test contract.

### Task 8: Documentation and roadmap closure

**Files:**
- Create: `docs/guides/persistence-adapters.md`
- Modify: `mkdocs.yml`
- Modify: `docs/roadmap.md`

- [ ] Document SQLAlchemy default vs Tortoise alternative.
- [ ] Publish a capability matrix with explicit Tortoise non-parity where applicable.
- [ ] Document direct and umbrella install paths.
- [ ] Mark D3 `Complete` and D4 `Next` only after implementation gates pass.

### Task 9: Verification and squash merge

- [ ] Run Ruff format/check over all D3 source.
- [ ] Run `ty check`.
- [ ] Run focused Tortoise manual/plain-Python SQLite smoke.
- [ ] Run focused permanent tests.
- [ ] Run full pytest/coverage, strict MkDocs, artifact checks, and clean-installed extra smoke.
- [ ] Verify lowest-direct and latest dependency jobs.
- [ ] Verify Python 3.12/3.13/3.14 jobs.
- [ ] Audit PR changed files for temporary workflow/helper files.
- [ ] Require exact-head canonical CI success.
- [ ] Squash merge to `main` with expected head SHA.
