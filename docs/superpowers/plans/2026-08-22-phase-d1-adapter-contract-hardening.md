# Phase D1 Adapter Contract Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an internal, versioned, per-capability conformance foundation that makes every advertised canonical Rakit adapter capability trustworthy before D2-D4 add second implementations.

**Architecture:** Keep the existing runtime capability primitives unchanged and add a separate canonical contract registry plus internal conformance machinery. Conformance is hard, capability-scoped, versioned, prerequisite-aware, behavior-based, and proven against real first-party implementations; C4 discovery/wire behavior remains compatible.

**Tech Stack:** Python 3.12+, dataclasses, existing Rakit capability/integration primitives, pytest/AnyIO for regression verification, Ruff, `ty`, MkDocs, existing GitHub Actions CI.

**Spec:** `docs/superpowers/specs/2026-08-22-phase-d1-adapter-contract-hardening-design.md`

## Global Constraints

- D1 is internal conformance infrastructure; do not add a public conformance CLI or a new public adapter-authoring SDK.
- Do not rename existing capability identifiers or change C4 `rakit capabilities` JSON schema v1.
- Do not add a runtime dependency.
- Advertised canonical capabilities are hard promises; missing canonical prerequisites or failed behavioral checks are conformance failures.
- Capability contracts are versioned metadata beginning at version `1`.
- Prerequisites encode only universal Rakit semantics, never incidental requirements of SQLAlchemy/Pydantic/Starlette implementations.
- Preserve `Capability`, `CapabilitySet`, `CapabilityProvider`, `CapabilityRequirement`, `CapabilityAnalysis`, and `IntegrationDescriptor` runtime semantics.
- Follow the project workflow: implement source/internal machinery first, perform non-pytest/manual verification, then add/refactor regression and conformance tests, then full CI.
- Do not release, tag, bump the public package version, upload to TestPyPI, or publish to PyPI.

---

## File Structure

The implementation should use focused files rather than expanding `capabilities.py` into governance/testing policy:

- Create `packages/rakit-core/src/rakit_core/capability_contracts.py` — canonical contract metadata, registry validation, prerequisite graph validation, lookup.
- Create `packages/rakit-core/src/rakit_core/conformance.py` — internal advertisement validation, conformance specs/results/failures, runner orchestration.
- Keep `packages/rakit-core/src/rakit_core/capabilities.py` unchanged unless a narrowly necessary compatibility-neutral helper is discovered during implementation.
- Modify `packages/rakit-core/src/rakit_core/adapter_capabilities.py` only if a canonical ordered tuple/helper is needed to prove complete registry coverage; do not change capability names.
- Modify `packages/rakit-core/src/rakit_core/testing/` only to reuse existing behavioral contract logic. Existing `DataSourceContractSuite` and `StorageContractSuite` already exist; do not create a parallel testing architecture.
- Add focused D1 tests under `packages/rakit-core/tests/` for registry/conformance semantics.
- Add/adjust first-party proof tests in the owning adapter packages (`rakit-sqlalchemy`, schema/Pydantic-owning package, and `rakit-web`) only after source/manual gates pass.
- Modify `docs/roadmap.md` for C4 closure and D1-D6/D4.0-D4.6 restructuring.
- Create a maintainer-facing D1 conformance architecture document under `docs/` if the existing capability-discovery docs are not the right ownership boundary.

---

### Task 1: Canonical Capability Contract Registry

**Files:**
- Create: `packages/rakit-core/src/rakit_core/capability_contracts.py`
- Modify if needed: `packages/rakit-core/src/rakit_core/adapter_capabilities.py`
- Test later in Task 6: `packages/rakit-core/tests/test_capability_contracts.py`

**Interfaces:**
- Consumes: existing `Capability`, `CapabilitySet`, and constants from `rakit_core.adapter_capabilities`.
- Produces: `CapabilityContract`, `CANONICAL_CAPABILITY_CONTRACTS`, `get_capability_contract()`, `validate_capability_contracts()`.

- [ ] **Step 1: Inventory the exact canonical capability constants and current first-party advertisements**

Read `adapter_capabilities.py`, first-party `IntegrationDescriptor` definitions, and capability-profile tests. Record the twelve current identifiers without renaming them:

```text
web.asgi
web.http-routing
web.streaming-response
schema.field-introspection
schema.input-validation
schema.output-serialization
schema.partial-update
persistence.read
persistence.write
persistence.relationships
transactions.root-uow
concurrency.atomic-optimistic
```

- [ ] **Step 2: Implement immutable contract metadata**

Use a focused dataclass with validation at construction:

```python
@dataclass(frozen=True, slots=True)
class CapabilityContract:
    capability: Capability
    version: int
    category: str
    prerequisites: CapabilitySet = field(default_factory=CapabilitySet)

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("Capability contract version must be >= 1")
        if not self.category or self.category != self.category.strip():
            raise ValueError("Capability contract category must be a non-empty trimmed string")
```

- [ ] **Step 3: Define the v1 canonical registry without speculative prerequisite edges**

Create one `CapabilityContract` per canonical constant. Add only prerequisite edges that are demonstrably universal from current Rakit semantics. If an edge is uncertain, leave it absent and document the reason rather than encoding SQLAlchemy-specific behavior.

- [ ] **Step 4: Implement registry validation**

`validate_capability_contracts(contracts)` must reject:

```text
duplicate capability identifier
version < 1
unknown prerequisite
self prerequisite
prerequisite cycle
```

Use deterministic traversal/order so diagnostics are stable.

- [ ] **Step 5: Implement canonical lookup**

```python
def get_capability_contract(capability: Capability | str) -> CapabilityContract | None:
    ...
```

Lookup must not mutate global state and unknown vendor capabilities return `None` rather than being treated as canonical Rakit contracts.

- [ ] **Step 6: Run source-only verification**

Run:

```bash
uv run ruff format --check packages/rakit-core/src/rakit_core/capability_contracts.py packages/rakit-core/src/rakit_core/adapter_capabilities.py
uv run ruff check packages/rakit-core/src/rakit_core/capability_contracts.py packages/rakit-core/src/rakit_core/adapter_capabilities.py
uv run ty check
```

Expected: PASS; no pytest yet.

- [ ] **Step 7: Commit source registry**

```bash
git add packages/rakit-core/src/rakit_core/capability_contracts.py packages/rakit-core/src/rakit_core/adapter_capabilities.py
git commit -m "feat(core): add capability contract registry"
```

---

### Task 2: Internal Conformance Result and Advertisement Model

**Files:**
- Create: `packages/rakit-core/src/rakit_core/conformance.py`
- Test later in Task 6: `packages/rakit-core/tests/test_capability_conformance.py`

**Interfaces:**
- Consumes: `CapabilityContract`, canonical lookup/registry validation, `CapabilitySet`, `IntegrationDescriptor`.
- Produces: `ConformanceFailureKind`, `ConformanceFailure`, `CapabilityConformanceResult`, `IntegrationConformanceResult`, `validate_advertised_capabilities()`.

- [ ] **Step 1: Define internal structured failure kinds**

Represent the three approved classes explicitly:

```python
class ConformanceFailureKind(StrEnum):
    REGISTRY = "registry"
    ADVERTISEMENT = "advertisement"
    BEHAVIOR = "behavior"
```

Do not create a new public exception hierarchy.

- [ ] **Step 2: Define immutable structured results**

Use internal dataclasses that carry canonical capability name, contract version, pass/fail status, and deterministic failures. Provide aggregate validity as a property, not duplicated mutable state.

- [ ] **Step 3: Implement hard prerequisite advertisement validation**

Given an `IntegrationDescriptor`, validate each advertised canonical capability. For a canonical capability with prerequisites, every prerequisite must also be advertised by the descriptor. Unknown non-canonical/vendor capabilities are not assigned a Rakit contract and are not silently treated as canonical.

- [ ] **Step 4: Preserve existing runtime descriptor semantics**

Do not make `IntegrationDescriptor.__post_init__` invoke conformance automatically. D1 conformance remains an internal explicit verification layer so existing runtime/configuration behavior and C4 discovery stay unchanged.

- [ ] **Step 5: Run source-only verification**

```bash
uv run ruff format --check packages/rakit-core/src/rakit_core/conformance.py
uv run ruff check packages/rakit-core/src/rakit_core/conformance.py
uv run ty check
```

Expected: PASS.

- [ ] **Step 6: Commit structured conformance source**

```bash
git add packages/rakit-core/src/rakit_core/conformance.py
git commit -m "feat(core): add internal capability conformance model"
```

---

### Task 3: Per-Capability Behavioral Spec Registry

**Files:**
- Modify: `packages/rakit-core/src/rakit_core/conformance.py`
- Reuse: `packages/rakit-core/src/rakit_core/testing/datasource_contract.py`
- Reuse where relevant: `packages/rakit-core/src/rakit_core/testing/storage_contract.py`
- Test later in Task 6: `packages/rakit-core/tests/test_capability_conformance.py`

**Interfaces:**
- Consumes: Task 2 result model.
- Produces: `CapabilityConformanceSpec`, `CapabilityCheck`, `CONFORMANCE_SPECS`, `get_conformance_spec()`, `run_capability_conformance()`.

- [ ] **Step 1: Define a small internal check protocol**

Use an async-capable callable contract so persistence/web checks can exercise real async behavior without encoding pytest into runtime code:

```python
CapabilityCheck = Callable[[object], Awaitable[None]]
```

The harness object is adapter/category-specific and remains internal.

- [ ] **Step 2: Define version-matched specs**

```python
@dataclass(frozen=True, slots=True)
class CapabilityConformanceSpec:
    capability: Capability
    version: int
    checks: tuple[CapabilityCheck, ...]
```

A spec must correspond exactly to the canonical contract version. Missing spec for an advertised canonical capability is a hard internal conformance failure, not a skip.

- [ ] **Step 3: Implement deterministic runner orchestration**

`run_capability_conformance(...)` must:

```text
resolve canonical contract
validate advertised prerequisites
resolve exact version spec
run every behavioral check
capture structured behavior failures
return CapabilityConformanceResult
```

Do not swallow cancellation/system exceptions. Only convert expected contract-check failures into structured behavior diagnostics.

- [ ] **Step 4: Keep behavioral checks implementation-neutral**

Do not inspect SQLAlchemy model classes, Pydantic private APIs, Starlette internals, or concrete adapter class names in generic checks. Category-specific harnesses expose only the operations required to demonstrate Rakit semantics.

- [ ] **Step 5: Run non-pytest smoke against synthetic internal checks**

Create a temporary local script (do not commit it) that constructs one passing and one failing synthetic check and asserts the structured result shape. Run it with plain Python/`uv run python`, then delete it.

Expected: one deterministic pass result and one deterministic behavior failure.

- [ ] **Step 6: Commit conformance runner source**

```bash
git add packages/rakit-core/src/rakit_core/conformance.py
git commit -m "feat(core): add per-capability conformance runner"
```

---

### Task 4: First-Party Conformance Harnesses and Capability Mapping

**Files:**
- Inspect/modify as ownership requires: first-party integration descriptor modules in `packages/rakit-sqlalchemy`, `packages/rakit-web`, and schema/Pydantic integration code.
- Reuse: `packages/rakit-sqlalchemy/tests/contract/test_sqlalchemy_contract.py`
- Reuse: existing schema validation/serialization tests in the package that owns the Pydantic adapter.
- Reuse: existing ASGI/routing/streaming tests in `packages/rakit-web/tests/`.
- Test additions are deferred to Task 7.

**Interfaces:**
- Consumes: `CapabilityConformanceSpec` and runner from Task 3.
- Produces: internal harness factories/check implementations for the twelve canonical capabilities, mapped to actual first-party descriptors.

- [ ] **Step 1: Audit actual descriptor advertisements before writing checks**

For each first-party integration, list `integration_id` and `advertised_capabilities`. The source of truth is the descriptor in code, not the design's expected matrix.

- [ ] **Step 2: Reconcile datasource capability reality**

The current SQLAlchemy `DataSourceContractSuite` proof explicitly documents the datasource as read-only and skips writes/transactions/concurrency. Do not falsely use that read-only datasource as proof for capabilities owned by separate SQLAlchemy mutation/UoW/concurrency components. Map each capability to the real implementation that owns its semantics.

- [ ] **Step 3: Implement persistence/read checks by reusing existing datasource contract behavior**

Extract or wrap only the relevant observable assertions from `DataSourceContractSuite` for `persistence.read` instead of duplicating list/detail/filter/search/sort/pagination semantics.

- [ ] **Step 4: Implement write/relationship/transaction/concurrency checks against their real first-party services**

Reuse existing mutation, relationship, transaction, and concurrency semantics. Each capability gets only the checks necessary for its contract; avoid one monolithic SQLAlchemy suite masquerading as per-capability proof.

- [ ] **Step 5: Implement schema checks against the real Pydantic-backed adapter**

Prove field introspection, input validation, output serialization, and partial-update semantics through public/adapter-neutral operations. Avoid checks against Pydantic private implementation details.

- [ ] **Step 6: Implement web checks against the current web runtime**

Prove ASGI callability/lifecycle boundary as applicable, HTTP route composition, and streaming response behavior through ASGI-visible behavior. Do not make Starlette class identity the contract.

- [ ] **Step 7: Run manual/non-pytest first-party smoke**

Use a temporary source-first runner to instantiate the first-party harnesses and print/validate the conformance matrix. It must exercise real implementations but must not call pytest. Delete the runner after verification.

Expected: every capability actually advertised by a first-party descriptor has a v1 spec and a passing real proof; any mismatch blocks progression and must be corrected honestly.

- [ ] **Step 8: Commit first-party conformance source/harness changes**

Commit only source/internal harness changes after the manual gate is green.

---

### Task 5: Internal Conformance Matrix

**Files:**
- Modify: `packages/rakit-core/src/rakit_core/conformance.py`
- Create if useful for docs generation: `docs/architecture/adapter-conformance.md`
- Test later: `packages/rakit-core/tests/test_capability_conformance.py`

**Interfaces:**
- Consumes: first-party descriptors and conformance results.
- Produces: deterministic internal matrix rows containing integration, capability, contract version, prerequisite validity, and behavioral status.

- [ ] **Step 1: Define deterministic matrix row data**

Keep it internal and serializable without introducing a public wire schema. Sort for presentation by integration id then canonical capability name; do not mutate declaration order in runtime capability primitives.

- [ ] **Step 2: Generate the first-party matrix from real descriptors/results**

No hard-coded green table. Matrix status must derive from actual conformance execution.

- [ ] **Step 3: Document the matrix as maintainer evidence, not certification**

State explicitly that D1's matrix is internal and that public third-party authoring/certification is deferred to D5.

- [ ] **Step 4: Run manual matrix smoke**

```bash
uv run python <temporary-d1-matrix-runner.py>
```

Expected: deterministic rows; all advertised canonical first-party capabilities pass; temporary runner removed afterward.

- [ ] **Step 5: Commit matrix/docs source**

Commit the internal matrix implementation and maintainer architecture documentation.

---

### Task 6: Registry and Conformance Regression Tests

**Files:**
- Create: `packages/rakit-core/tests/test_capability_contracts.py`
- Create: `packages/rakit-core/tests/test_capability_conformance.py`
- Modify if necessary: `packages/rakit-core/tests/test_capabilities.py`
- Modify if necessary: `packages/rakit-core/tests/test_adapter_capability_negotiation.py`

**Interfaces:**
- Consumes: Tasks 1-3 source.
- Produces: regression coverage for D1 governance semantics without changing public C4 behavior.

- [ ] **Step 1: Add canonical coverage/version tests**

Assert the registry covers exactly the canonical constants and every contract is v1 with stable names.

- [ ] **Step 2: Add invalid registry graph tests**

Cover duplicate identifiers, version zero, unknown prerequisite, self-dependency, and a multi-node cycle. Assert deterministic actionable diagnostics.

- [ ] **Step 3: Add advertisement prerequisite tests**

Construct descriptors where a higher capability omits a prerequisite and assert a structured `ADVERTISEMENT` failure. Also prove a valid advertised prerequisite set passes preflight.

- [ ] **Step 4: Add behavioral runner tests**

Use tiny synthetic async checks to prove pass, multiple deterministic behavior failures, exact contract-version resolution, and missing-spec hard failure.

- [ ] **Step 5: Add compatibility regression assertions**

Assert existing `Capability`, `CapabilitySet`, analysis declaration order, and `IntegrationDescriptor` behavior remain unchanged by D1.

- [ ] **Step 6: Run focused core tests**

```bash
uv run pytest packages/rakit-core/tests/test_capability_contracts.py packages/rakit-core/tests/test_capability_conformance.py packages/rakit-core/tests/test_capabilities.py packages/rakit-core/tests/test_adapter_capability_negotiation.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit core regression tests**

```bash
git add packages/rakit-core/tests
git commit -m "test(core): cover capability conformance contracts"
```

---

### Task 7: First-Party Behavioral Proof Tests

**Files:**
- Modify/refactor: `packages/rakit-sqlalchemy/tests/contract/test_sqlalchemy_contract.py`
- Add focused conformance tests in `packages/rakit-sqlalchemy/tests/contract/` as needed.
- Add focused schema adapter conformance tests in the package that owns the Pydantic integration.
- Add focused web conformance tests under `packages/rakit-web/tests/`.

**Interfaces:**
- Consumes: Task 4 harnesses/specs and existing behavioral contract suites.
- Produces: real regression proof for every canonical capability actually advertised by first-party descriptors.

- [ ] **Step 1: Preserve the existing datasource contract proof**

Do not weaken `DataSourceContractSuite`. Its current read-only SQLAlchemy proof must remain valid and its skips must stay honest unless the underlying datasource capability itself changes for a separate reason.

- [ ] **Step 2: Add per-capability SQLAlchemy proof**

Drive D1 conformance for persistence/write/relationships/UoW/concurrency through the correct first-party components. A failure in one capability must identify that capability rather than collapsing into one adapter-wide boolean.

- [ ] **Step 3: Add per-capability schema proof**

Prove all schema capabilities currently advertised by the first-party Pydantic integration.

- [ ] **Step 4: Add per-capability web proof**

Prove all web capabilities currently advertised by the current first-party web integration.

- [ ] **Step 5: Run focused first-party conformance tests**

Run only the owning package suites first. Expected: every advertised canonical capability passes; unsupported/unadvertised capabilities are not silently skipped as though supported.

- [ ] **Step 6: Commit first-party regression proof**

Commit package-local tests after focused suites pass.

---

### Task 8: C4 Compatibility and No-New-Dependency Gate

**Files:**
- Inspect/modify only if a regression is found: C4 inspection/CLI modules and package metadata.
- Tests: existing C4 capability discovery/check tests and packaging tests.

**Interfaces:**
- Consumes: all D1 implementation.
- Produces: explicit evidence that D1 is additive and C4 wire/runtime behavior is unchanged.

- [ ] **Step 1: Run C4 focused regression suite**

Run the existing tests covering `rakit capabilities`, JSON schema v1, aggregate `rakit check`, configured integration inventory, duplicate identifiers, and lightweight server discovery.

Expected: PASS without updating snapshots/schema for D1.

- [ ] **Step 2: Compare package metadata/dependency graph**

Verify D1 did not add runtime dependencies to `rakit-core` or the root facade.

- [ ] **Step 3: Run CLI manual smoke**

```bash
uv run rakit capabilities
uv run rakit capabilities --json
uv run rakit check
```

Expected: existing C4 presentation/wire behavior remains compatible.

- [ ] **Step 4: Commit only genuine compatibility fixes if required**

Any fix must preserve D1 design boundaries; do not change C4 schema merely to make tests easier.

---

### Task 9: Roadmap and Maintainer Documentation

**Files:**
- Modify: `docs/roadmap.md`
- Modify/create: maintainer capability/conformance architecture documentation as established in Task 5.
- Modify if appropriate: `CHANGELOG.md`

**Interfaces:**
- Consumes: verified D1 implementation and agreed roadmap structure.
- Produces: canonical project status and future adapter sequence.

- [ ] **Step 1: Mark C4 Complete**

Replace stale C4 `Status: Next` text with `Status: Complete` and summarize the shipped capability discovery behavior from PR #49 without rewriting history.

- [ ] **Step 2: Replace monolithic Phase D with the agreed structure**

Document:

```text
D1 Adapter Contract Hardening
D2 Schema Adapter Ecosystem — msgspec intended first pressure test
D3 Persistence Adapter Ecosystem — Tortoise ORM intended first pressure test
D4 Web Framework Integrations
D5 Adapter Authoring DX / SDK
D6 Additional First-party Adapters
```

- [ ] **Step 3: Expand D4 roadmap**

Document:

```text
D4.0 Web Integration Contract
D4.1 Litestar
D4.2 FastAPI
D4.3 Starlette
D4.4 Flask
D4.5 Sanic
D4.6 Integration DX & Compatibility Matrix
```

- [ ] **Step 4: Mark D1 Complete only after Tasks 1-8 are green**

Before that point D1 remains active/next. Do not pre-mark completion in an implementation commit.

- [ ] **Step 5: Document the D5 boundary**

Explain that current conformance machinery is maintainer/internal and may be reshaped by D2-D4 before any stable public adapter-authoring/testing API is promised.

- [ ] **Step 6: Commit roadmap/docs closure**

```bash
git add docs/roadmap.md docs CHANGELOG.md
git commit -m "docs: close D1 adapter contract hardening"
```

Include only files actually changed.

---

### Task 10: Full Verification, Review Surface, and Exact-Head Closure

**Files:**
- No planned source changes; fixes discovered by verification go back to the owning task/file.

**Interfaces:**
- Consumes: complete D1 branch.
- Produces: merge-ready D1 with fresh exact-head evidence.

- [ ] **Step 1: Run formatting, lint, and typing**

```bash
uv run ruff format --check .
uv run ruff check .
uv run ty check
```

Expected: PASS.

- [ ] **Step 2: Run the full local regression suite**

```bash
uv run pytest -q
```

Expected: PASS.

- [ ] **Step 3: Run repository verification gates available locally**

Run the same release/quality commands used by current CI for coverage, strict MkDocs, artifact validation/dry-run, and generated web-asset reproducibility. Do not publish artifacts.

- [ ] **Step 4: Open or update a draft PR for D1**

The PR body must summarize the contract registry, hard advertisement validation, first-party proof matrix, compatibility guarantees, roadmap restructure, and explicitly state that public adapter SDK/CLI is deferred to D5.

- [ ] **Step 5: Let the full GitHub Actions matrix run**

Require green Python 3.12/3.13/3.14, dependency matrices, Ruff, `ty`, coverage, MkDocs strict, artifact checks, and web-asset reproducibility.

- [ ] **Step 6: Fix failures at their root cause and rerun focused verification first**

Do not weaken conformance contracts or remove advertised capabilities merely to make CI green unless the advertisement is proven dishonest by the D1 design criteria.

- [ ] **Step 7: Update roadmap D1 status to Complete only after the full gate is green**

If this changes the head, it invalidates the previous CI evidence and requires another exact-head CI run.

- [ ] **Step 8: Require fresh exact-head CI after the closure commit**

The commit that marks D1 Complete in `docs/roadmap.md` must itself have a green full CI matrix before merge readiness is claimed.

- [ ] **Step 9: Perform final diff review**

Confirm:

```text
no capability identifier rename
no C4 JSON schema change
no runtime dependency addition
no public conformance CLI
no premature stable public adapter SDK
no release/tag/publication action
```

- [ ] **Step 10: Mark PR ready only after verification evidence is fresh**

Do not merge automatically unless explicitly requested after the final review.

---

## Self-Review Against the Approved Spec

- Registry/versioning: Tasks 1 and 6.
- Canonical vocabulary/reserved ownership: Tasks 1, 2, and 6.
- Explicit prerequisites/cycle validation: Tasks 1, 2, and 6.
- Per-capability behavioral conformance: Tasks 3, 4, and 7.
- Real first-party proof: Tasks 4 and 7.
- Structured internal results/failure classes: Tasks 2, 3, and 6.
- Internal matrix: Task 5.
- C4/runtime compatibility: Task 8.
- No public SDK/CLI and no runtime dependency: Global Constraints, Tasks 8-10.
- C4 roadmap closure and D1-D6/D4.0-D4.6 restructure: Task 9.
- Source-first/manual-before-regression workflow: Tasks 1-5 precede Tasks 6-7.
- Full CI and exact-head closure: Task 10.
- No release: Global Constraints and Task 10.

No spec requirement is intentionally deferred inside D1 except the explicitly out-of-scope public adapter-authoring surface reserved for D5.
