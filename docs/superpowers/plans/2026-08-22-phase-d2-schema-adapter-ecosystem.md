# Phase D2 Schema Adapter Ecosystem Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract Pydantic schema ownership from `rakit-web`, add msgspec as the first second schema adapter, and prove deterministic multi-adapter schema selection against D1 capability contracts.

**Architecture:** `rakit-core` remains the schema-neutral contract owner. Two peer packages, `rakit-schema-pydantic` and `rakit-schema-msgspec`, own concrete schema engines, integration descriptors, capability providers, and engine-specific error translation. `rakit-web` consumes only `SchemaAdapter`/`PartialInputSchemaAdapter`; installed integrations remain discoverable through C4 while configured schema selection is explicit and deterministic.

**Tech Stack:** Python 3.12+, Pydantic v2, msgspec, existing Rakit capability/integration contracts, uv workspace packaging, pytest/AnyIO for regression verification, Ruff, `ty`, MkDocs, canonical GitHub Actions CI.

**Spec:** `docs/superpowers/specs/2026-08-22-phase-d2-schema-adapter-ecosystem-design.md`

## Global Constraints

- Rakit is still pre-release; D2 intentionally performs a breaking cleanup with no compatibility shim for `rakit_web.schema.PydanticSchemaAdapter`.
- `rakit-core` and `rakit-web` must not depend on Pydantic- or msgspec-specific APIs.
- Pydantic remains the default schema developer experience, but default must not become an architectural dependency of `rakit-core` or `rakit-web`.
- Native schema classes remain native: Pydantic `BaseModel`, msgspec `Struct`; D2 introduces no Rakit schema DSL/base model.
- Pydantic must continue to advertise and pass all four canonical schema capabilities unless implementation proves an existing advertisement was dishonest and cannot be repaired cleanly.
- msgspec advertises only capabilities that pass the exact D1 v1 behavioral contracts.
- `schema.partial-update@1` is presence-aware: omitted required fields are not required, missing differs from explicit `None`, explicit `None` remains present when valid, and output contains only fields supplied by the caller.
- Adapter selection is deterministic: explicit configured selection wins; otherwise Pydantic is the only default when installed; otherwise fail with an actionable diagnostic. Never select based on entry-point/import order.
- Installed integrations remain visible through C4 regardless of which schema adapter is active.
- D2 does not implement automatic `rakit schema use ...`, dependency removal, or package switching commands.
- Follow the Rakit workflow: source/package migration first, manual/non-pytest verification second, permanent regression/conformance tests third, full CI fourth, docs/roadmap closure fifth, exact-head CI last.
- Do not release, tag, bump package versions, upload to TestPyPI, or publish to PyPI.

---

## File Structure

### New packages

- `packages/rakit-schema-pydantic/pyproject.toml` — first-party Pydantic distribution metadata and `rakit.integrations` entry point.
- `packages/rakit-schema-pydantic/src/rakit_schema_pydantic/__init__.py` — public adapter exports.
- `packages/rakit-schema-pydantic/src/rakit_schema_pydantic/adapter.py` — `PydanticSchemaAdapter` and Pydantic-specific validation translation.
- `packages/rakit-schema-pydantic/src/rakit_schema_pydantic/capabilities.py` — `PYDANTIC_SCHEMA_CAPABILITIES`.
- `packages/rakit-schema-pydantic/src/rakit_schema_pydantic/discovery.py` — `PYDANTIC_INTEGRATION`.
- `packages/rakit-schema-pydantic/tests/` — package-local regression/conformance coverage.

- `packages/rakit-schema-msgspec/pyproject.toml` — first-party msgspec distribution metadata and `rakit.integrations` entry point.
- `packages/rakit-schema-msgspec/src/rakit_schema_msgspec/__init__.py` — public adapter exports.
- `packages/rakit-schema-msgspec/src/rakit_schema_msgspec/adapter.py` — `MsgspecSchemaAdapter` and msgspec-specific validation/error translation.
- `packages/rakit-schema-msgspec/src/rakit_schema_msgspec/capabilities.py` — honest msgspec capability provider derived from verified semantics.
- `packages/rakit-schema-msgspec/src/rakit_schema_msgspec/discovery.py` — `MSGSPEC_INTEGRATION`.
- `packages/rakit-schema-msgspec/tests/` — package-local regression/conformance coverage.

### Existing packages/files to modify

- `packages/rakit-web/src/rakit_web/schema.py` — remove concrete Pydantic ownership entirely; retain only web-owned schema-agnostic helpers if any remain, otherwise delete the module and update imports.
- `packages/rakit-web/src/rakit_web/capabilities.py` — remove `PYDANTIC_SCHEMA_CAPABILITIES`; retain Starlette web capabilities only.
- `packages/rakit-web/src/rakit_web/discovery.py` — remove `PYDANTIC_INTEGRATION`; retain Starlette integration only.
- `packages/rakit-web/pyproject.toml` — remove `schema.pydantic` entry point and any accidental concrete schema-engine dependency.
- `packages/rakit-web/tests/` — migrate schema-adapter tests to their owning packages; retain web tests only for schema-neutral behavior.
- `packages/rakit-core/src/rakit_core/schema.py` — preserve neutral protocols; make only narrowly necessary semantic clarifications for presence-aware partial update.
- `packages/rakit-core/src/rakit_core/conformance.py` and/or `rakit_core.testing` schema conformance helpers — adjust only if D2 exposes a real contract gap; no Pydantic/msgspec imports.
- schema selection/configuration owner discovered during implementation — add explicit configured-schema resolution and default-Pydantic fallback without discovery-order dependence.
- `packages/rakit/pyproject.toml` — make default Rakit installation include `rakit-schema-pydantic`; add explicit msgspec convenience extra only if it fits the existing C3 extras vocabulary cleanly.
- root `pyproject.toml` — add new package modules to coverage source and any dev/package wiring needed by workspace verification.
- `scripts/check_artifacts.py`, release/package tests, and lockfile — include both new distributions.
- `docs/roadmap.md` — correct C4/D1 status, restructure D1-D6 and D4.0-D4.6, mark D2 active during implementation and Complete only after closure gate.
- installation/architecture/extending docs — document schema package boundaries and deterministic selection semantics.

---

### Task 1: Extract Pydantic Into `rakit-schema-pydantic`

**Files:**
- Create: `packages/rakit-schema-pydantic/pyproject.toml`
- Create: `packages/rakit-schema-pydantic/src/rakit_schema_pydantic/__init__.py`
- Create: `packages/rakit-schema-pydantic/src/rakit_schema_pydantic/adapter.py`
- Create: `packages/rakit-schema-pydantic/src/rakit_schema_pydantic/capabilities.py`
- Create: `packages/rakit-schema-pydantic/src/rakit_schema_pydantic/discovery.py`
- Modify/Delete: `packages/rakit-web/src/rakit_web/schema.py`
- Modify: `packages/rakit-web/src/rakit_web/capabilities.py`
- Modify: `packages/rakit-web/src/rakit_web/discovery.py`
- Modify: `packages/rakit-web/pyproject.toml`
- Tests deferred to Task 7.

**Interfaces:**
- Consumes: `SchemaAdapter`, `PartialInputSchemaAdapter`, `SchemaField`, `SchemaValidationError`, `SchemaValidationIssue`, canonical schema capabilities, `IntegrationDescriptor`.
- Produces: `PydanticSchemaAdapter`, `PYDANTIC_SCHEMA_CAPABILITIES`, `PYDANTIC_INTEGRATION` from `rakit_schema_pydantic`.

- [ ] **Step 1: Create package metadata**

Use the same hatchling/version/Python conventions as other first-party packages. Required runtime dependencies:

```toml
[project]
name = "rakit-schema-pydantic"
version = "0.1.0a1"
requires-python = ">=3.12"
dependencies = [
  "rakit-core==0.1.0a1",
  "pydantic>=2",
]

[project.entry-points."rakit.integrations"]
"schema.pydantic" = "rakit_schema_pydantic.discovery:PYDANTIC_INTEGRATION"
```

Add workspace source mapping for `rakit-core` and wheel package path.

- [ ] **Step 2: Move capability provider and descriptor ownership**

Create:

```python
PYDANTIC_SCHEMA_CAPABILITIES = CapabilityProvider(
    provider_id="schema.pydantic",
    capabilities=CapabilitySet.of(
        SCHEMA_FIELD_INTROSPECTION,
        SCHEMA_INPUT_VALIDATION,
        SCHEMA_OUTPUT_SERIALIZATION,
        SCHEMA_PARTIAL_UPDATE,
    ),
)

PYDANTIC_INTEGRATION = IntegrationDescriptor(
    integration_id="schema.pydantic",
    category="schema",
    display_name="Pydantic",
    advertised_capabilities=PYDANTIC_SCHEMA_CAPABILITIES.capabilities,
)
```

- [ ] **Step 3: Move `PydanticSchemaAdapter` into the new package**

Preserve field introspection, full input validation, output serialization, and error translation semantics. Do not import from `rakit-web`.

- [ ] **Step 4: Fix Pydantic partial-update semantics at the adapter boundary**

Do not validate a partial mapping by pretending it is a complete instance of the full model. Build presence-aware validation from public Pydantic APIs only. Required observable examples:

```python
{} -> {}
{"name": "Edo"} -> {"name": "Edo"}
{"age": None} -> {"age": None}
```

A supplied invalid value must still raise `SchemaValidationError`.

- [ ] **Step 5: Remove Pydantic ownership from `rakit-web`**

Remove:

```text
PYDANTIC_SCHEMA_CAPABILITIES
PYDANTIC_INTEGRATION
schema.pydantic entry point
PydanticSchemaAdapter implementation
```

No compatibility re-export or shim is allowed.

- [ ] **Step 6: Update internal imports across the repository**

Search for:

```text
rakit_web.schema
PydanticSchemaAdapter
PYDANTIC_SCHEMA_CAPABILITIES
PYDANTIC_INTEGRATION
```

and move legitimate schema-engine consumers to `rakit_schema_pydantic`. Web/runtime consumers that only need a protocol must import from `rakit_core.schema` instead.

- [ ] **Step 7: Run source-only verification**

```bash
uv lock
uv sync --all-packages --dev --locked
uv run ruff format --check packages/rakit-schema-pydantic packages/rakit-web
uv run ruff check packages/rakit-schema-pydantic packages/rakit-web
uv run ty check
```

Expected: PASS; no regression pytest yet.

- [ ] **Step 8: Commit D2.1 source migration**

```bash
git add packages/rakit-schema-pydantic packages/rakit-web pyproject.toml uv.lock
git commit -m "refactor(schema): extract pydantic adapter package"
```

---

### Task 2: Add `rakit-schema-msgspec`

**Files:**
- Create: `packages/rakit-schema-msgspec/pyproject.toml`
- Create: `packages/rakit-schema-msgspec/src/rakit_schema_msgspec/__init__.py`
- Create: `packages/rakit-schema-msgspec/src/rakit_schema_msgspec/adapter.py`
- Create: `packages/rakit-schema-msgspec/src/rakit_schema_msgspec/capabilities.py`
- Create: `packages/rakit-schema-msgspec/src/rakit_schema_msgspec/discovery.py`
- Tests deferred to Task 7.

**Interfaces:**
- Consumes: neutral schema contracts and D1 canonical schema capabilities.
- Produces: `MsgspecSchemaAdapter`, `MSGSPEC_SCHEMA_CAPABILITIES`, `MSGSPEC_INTEGRATION`.

- [ ] **Step 1: Create msgspec package metadata**

```toml
[project]
name = "rakit-schema-msgspec"
version = "0.1.0a1"
requires-python = ">=3.12"
dependencies = [
  "rakit-core==0.1.0a1",
  "msgspec>=0.19",
]

[project.entry-points."rakit.integrations"]
"schema.msgspec" = "rakit_schema_msgspec.discovery:MSGSPEC_INTEGRATION"
```

Use the workspace/hatch conventions of the Pydantic package.

- [ ] **Step 2: Implement native schema-type validation**

The adapter must accept only `type[msgspec.Struct]` schemas and reject unrelated types deterministically:

```python
if not isinstance(schema, type) or not issubclass(schema, msgspec.Struct):
    raise TypeError("MsgspecSchemaAdapter requires a msgspec.Struct schema")
```

- [ ] **Step 3: Implement declaration-order field introspection**

Expose `SchemaField` objects using public msgspec struct field metadata. Preserve field names/order and do not invent unavailable title/description metadata.

- [ ] **Step 4: Implement full input validation and error translation**

Validate mappings through public msgspec conversion/decoding APIs and translate native validation failures into deterministic `SchemaValidationError`/`SchemaValidationIssue` values.

- [ ] **Step 5: Implement output serialization**

Return JSON-compatible Python transport values, not `msgspec.Struct` objects or engine-private nodes.

- [ ] **Step 6: Investigate and implement partial-update only if cleanly supportable**

A valid implementation must satisfy exactly:

```text
omitted required fields need not be supplied
missing != explicit None
only supplied keys are returned
supplied keys retain native validation
{} is valid
```

Use public msgspec APIs only. If this cannot be satisfied without fragile/private behavior, omit `SCHEMA_PARTIAL_UPDATE` from the provider.

- [ ] **Step 7: Advertise only implemented/proven capabilities**

Construct `MSGSPEC_SCHEMA_CAPABILITIES` from the capability subset supported by the source implementation. Do not copy Pydantic's provider mechanically.

- [ ] **Step 8: Run source-only verification**

```bash
uv lock
uv sync --all-packages --dev --locked
uv run ruff format --check packages/rakit-schema-msgspec
uv run ruff check packages/rakit-schema-msgspec
uv run ty check
```

Expected: PASS.

- [ ] **Step 9: Commit D2.2 source**

```bash
git add packages/rakit-schema-msgspec pyproject.toml uv.lock
git commit -m "feat(schema): add msgspec adapter package"
```

---

### Task 3: Deterministic Schema Selection and Default Pydantic UX

**Files:**
- Inspect/modify the existing configured-integration ownership in `rakit-core`/facade discovered from C4.
- Modify: `packages/rakit/pyproject.toml`
- Modify: install-vocabulary module(s) introduced in C3.
- Modify: scaffold/template dependency generation if schema dependency is currently implicit.
- Tests deferred to Task 8.

**Interfaces:**
- Consumes: installed integration inventory and `IntegrationDescriptor` identifiers `schema.pydantic` / `schema.msgspec`.
- Produces: deterministic schema-integration resolution used by runtime composition/scaffolding.

- [ ] **Step 1: Locate the existing configured-integration inventory and selection boundary**

Do not create a second configuration system. Reuse C4's distinction between installed and configured integrations.

- [ ] **Step 2: Add explicit schema adapter selection**

The resolver behavior must be:

```text
explicit configured schema integration -> use it if installed/valid
no explicit selection + schema.pydantic installed -> schema.pydantic
no explicit selection + no schema.pydantic -> actionable failure
```

`schema.msgspec` must never become active merely because it appears first in entry-point discovery.

- [ ] **Step 3: Define invalid-selection diagnostics**

An explicit unknown/uninstalled schema adapter must report the requested integration id and available installed schema integrations. Do not silently fall back to Pydantic after an explicit invalid request.

- [ ] **Step 4: Make the root distribution preserve Pydantic as ordinary default UX**

Add `rakit-schema-pydantic==0.1.0a1` at the root/facade distribution layer, not in `rakit-core` or `rakit-web`.

- [ ] **Step 5: Add a msgspec convenience extra only through the C3 install vocabulary**

If root extras are the established user-facing vocabulary, add:

```toml
msgspec = ["rakit-schema-msgspec==0.1.0a1"]
```

and update the single source of truth used by install guidance/scaffolding. Do not add a duplicate hard-coded map.

- [ ] **Step 6: Keep modular installations possible**

Verify that `rakit-core` + `rakit-web` + `rakit-schema-msgspec` can resolve without `rakit-schema-pydantic` being required by either core or web.

- [ ] **Step 7: Run manual selection smoke without pytest**

Use a temporary plain-Python runner (not committed) to prove:

```text
Pydantic installed only -> selects Pydantic
Pydantic + msgspec installed, no explicit selection -> selects Pydantic
Pydantic + msgspec installed, explicit msgspec -> selects msgspec
explicit unavailable adapter -> fails clearly
msgspec-only modular install, explicit msgspec -> selects msgspec
msgspec-only modular install, no explicit selection -> fails rather than guessing
```

Delete the temporary runner after use.

- [ ] **Step 8: Commit D2.3 source/configuration changes**

Commit only after the non-pytest selection smoke passes.

---

### Task 4: Cross-Adapter D1 Conformance Manual Gate

**Files:**
- Modify only if a real generic contract gap is found: `packages/rakit-core/src/rakit_core/conformance.py`, `packages/rakit-core/src/rakit_core/schema.py`, or existing schema conformance helpers.
- No permanent tests yet.

**Interfaces:**
- Consumes: D1 `schema.*@1` conformance specs plus both concrete adapters.
- Produces: source-first evidence of the honest capability matrix.

- [ ] **Step 1: Build temporary real Pydantic and msgspec harnesses**

Use representative native schemas containing:

```text
required string
optional/nullable field
field with invalid-type case
partial-update cases
```

- [ ] **Step 2: Run Pydantic against all four v1 contracts**

Expected: 4/4 pass. A failure blocks progression and should be fixed at the adapter or genuinely generic contract boundary.

- [ ] **Step 3: Run msgspec against every advertised v1 contract**

Expected: every advertised capability passes; unadvertised capability is visible as unsupported rather than skipped as supported.

- [ ] **Step 4: Record the honest matrix for later docs/tests**

Example shape only; do not hard-code expected msgspec count before execution:

```text
schema.pydantic  field-introspection  v1 PASS
schema.pydantic  input-validation     v1 PASS
schema.pydantic  output-serialization v1 PASS
schema.pydantic  partial-update       v1 PASS
schema.msgspec   ...                   v1 PASS/unsupported
```

- [ ] **Step 5: Delete temporary runners and rerun source static gates**

```bash
uv run ruff format --check .
uv run ruff check .
uv run ty check
```

Expected: PASS.

---

### Task 5: C4 Discovery and Package/Artifact Wiring

**Files:**
- Modify: root `pyproject.toml`
- Modify: `scripts/check_artifacts.py`
- Modify: release/package verification tests under `tests/release/`
- Modify: clean-installed smoke fixtures/scripts where official distribution lists are enumerated.
- Modify: `uv.lock`

**Interfaces:**
- Consumes: two new packages and their entry points.
- Produces: workspace/release validation that treats both schema adapters as official first-party distributions.

- [ ] **Step 1: Add both schema packages to coverage accounting**

Extend root coverage sources with:

```text
rakit_schema_pydantic
rakit_schema_msgspec
```

- [ ] **Step 2: Update official distribution inventories**

Every release/artifact list that enumerates `packages/*` expectations must include both new distributions.

- [ ] **Step 3: Verify entry-point discovery from installed package metadata**

C4 inventory must expose `schema.pydantic` when the Pydantic distribution is installed and `schema.msgspec` when the msgspec distribution is installed.

- [ ] **Step 4: Preserve C4 installed-vs-configured semantics**

With both installed, C4 should report both as installed while the configured schema integration reflects explicit/default selection rules from Task 3.

- [ ] **Step 5: Run artifact/package source gate**

```bash
uv run python scripts/check_artifacts.py
uv run pytest tests/release -q
```

This is allowed here because artifact verification is its own repository gate; schema regression tests remain deferred to Tasks 7-8.

- [ ] **Step 6: Commit package/artifact wiring**

```bash
git add pyproject.toml uv.lock scripts/check_artifacts.py tests/release packages/rakit packages/rakit-schema-pydantic packages/rakit-schema-msgspec
git commit -m "build(schema): wire schema adapter distributions"
```

---

### Task 6: Roadmap Structural Update (Active D2, Not Complete Yet)

**Files:**
- Modify: `docs/roadmap.md`

**Interfaces:**
- Produces: correct canonical history/status before D2 closure.

- [ ] **Step 1: Mark Phase C and C4 Complete**

Replace stale `Phase C: Next` / `C4: Next` entries with `Complete` and summarize actual C4 discovery capabilities that landed in PR #49.

- [ ] **Step 2: Replace monolithic Phase D with D1-D6**

Record:

```text
D1 Adapter Contract Hardening — Complete
D2 Schema Adapter Ecosystem — Next / active
D3 Persistence Adapter Ecosystem — Planned
D4 Web Framework Integrations — Planned
D5 Adapter Authoring DX / SDK — Planned
D6 Additional First-party Adapters — Planned
```

- [ ] **Step 3: Preserve D4.0-D4.6**

```text
D4.0 Web Integration Contract
D4.1 Litestar
D4.2 FastAPI
D4.3 Starlette
D4.4 Flask
D4.5 Sanic
D4.6 Integration DX & Compatibility Matrix
```

- [ ] **Step 4: Do not mark D2 Complete yet**

D2 remains active until Tasks 7-10 and exact-head CI are green.

- [ ] **Step 5: Commit roadmap structure**

```bash
git add docs/roadmap.md
git commit -m "docs: restructure adapter ecosystem roadmap"
```

---

### Task 7: Permanent Pydantic and msgspec Adapter Regression Tests

**Files:**
- Create: `packages/rakit-schema-pydantic/tests/test_adapter.py`
- Create: `packages/rakit-schema-pydantic/tests/test_conformance.py`
- Create: `packages/rakit-schema-msgspec/tests/test_adapter.py`
- Create: `packages/rakit-schema-msgspec/tests/test_conformance.py`

**Interfaces:**
- Consumes: Tasks 1-4 implementations.
- Produces: permanent behavioral proof for every advertised schema capability.

- [ ] **Step 1: Add Pydantic native-type rejection tests**

Assert unrelated schema classes raise the deterministic Pydantic adapter `TypeError`.

- [ ] **Step 2: Add Pydantic complete-validation/error translation tests**

Cover valid complete input and a deterministic `SchemaValidationError` issue shape for invalid input.

- [ ] **Step 3: Add Pydantic presence-aware partial-update tests**

Required regression cases:

```python
assert adapter.validate_partial_input(Model, {}) == {}
assert adapter.validate_partial_input(Model, {"name": "Edo"}) == {"name": "Edo"}
assert adapter.validate_partial_input(Model, {"age": None}) == {"age": None}
```

Also prove an invalid supplied field fails even when unrelated required fields are omitted.

- [ ] **Step 4: Run Pydantic through D1 4/4 conformance**

The descriptor's advertised capability set must exactly match the capabilities proven by the test harness.

- [ ] **Step 5: Add msgspec native-type rejection, full validation, output serialization, and error translation tests**

Use native `msgspec.Struct` schemas only.

- [ ] **Step 6: Add msgspec partial-update tests only if capability is advertised**

If `SCHEMA_PARTIAL_UPDATE` is not advertised, add a regression proving it is absent from the capability provider and no code path claims it implicitly.

- [ ] **Step 7: Run msgspec through every advertised D1 v1 conformance spec**

Missing harness/spec or any behavior failure must fail the suite.

- [ ] **Step 8: Run focused adapter tests**

```bash
uv run pytest packages/rakit-schema-pydantic/tests packages/rakit-schema-msgspec/tests -q
```

Expected: PASS.

- [ ] **Step 9: Commit adapter regression tests**

```bash
git add packages/rakit-schema-pydantic/tests packages/rakit-schema-msgspec/tests
git commit -m "test(schema): prove pydantic and msgspec conformance"
```

---

### Task 8: Selection, Discovery, and Breaking-Cleanup Regression Tests

**Files:**
- Add focused tests in the package owning schema selection/configuration.
- Modify: C4 capability/integration discovery tests.
- Modify: `packages/rakit-web/tests/` to remove stale Pydantic-owned tests/imports.
- Add packaging tests ensuring `rakit-web` contains no Pydantic/msgspec dependency or schema entry point.

**Interfaces:**
- Consumes: Tasks 1-5.
- Produces: permanent proof of deterministic selection and the new package boundary.

- [ ] **Step 1: Prove old public path is gone**

Tests must not import or re-export:

```text
rakit_web.schema.PydanticSchemaAdapter
rakit_web.capabilities.PYDANTIC_SCHEMA_CAPABILITIES
rakit_web.discovery.PYDANTIC_INTEGRATION
```

Because D2 is a deliberate breaking cleanup, no compatibility assertion is required.

- [ ] **Step 2: Prove `rakit-web` metadata is schema-engine-neutral**

Assert it has no `schema.pydantic` entry point and no direct Pydantic/msgspec runtime dependency.

- [ ] **Step 3: Add deterministic default/explicit selection tests**

Cover all six source-smoke cases from Task 3 permanently, including dual-installed order independence.

- [ ] **Step 4: Add C4 discovery tests for both schema integrations**

Installed integrations must both appear when installed. Active/configured selection must remain distinct.

- [ ] **Step 5: Add missing/invalid selection diagnostic tests**

Assert requested id + available integrations are included in actionable diagnostics.

- [ ] **Step 6: Run focused cross-package tests**

```bash
uv run pytest packages/rakit-core/tests packages/rakit-web/tests packages/rakit-schema-pydantic/tests packages/rakit-schema-msgspec/tests -q
```

Expected: PASS.

- [ ] **Step 7: Commit selection/discovery regressions**

Commit package-local tests and only necessary source fixes discovered by them.

---

### Task 9: Documentation and Examples

**Files:**
- Modify: installation docs.
- Modify: architecture/package-boundary docs.
- Modify: adapter/extending docs.
- Modify: reference app/scaffold docs if they name Pydantic ownership/import paths.
- Modify: `CHANGELOG.md` if current project convention records unreleased breaking cleanup there.

**Interfaces:**
- Consumes: final package/import/selection behavior.
- Produces: accurate maintainer/user guidance without promising out-of-scope switching CLI.

- [ ] **Step 1: Document Pydantic default vs architecture neutrality**

State clearly: ordinary `rakit` UX uses Pydantic by default, while core/web remain schema-engine-neutral.

- [ ] **Step 2: Document dedicated package imports**

Use:

```python
from rakit_schema_pydantic import PydanticSchemaAdapter
from rakit_schema_msgspec import MsgspecSchemaAdapter
```

Do not show the removed `rakit_web.schema` path.

- [ ] **Step 3: Document explicit schema selection and dual-installed behavior**

Explain that installed != active and that msgspec never becomes active by entry-point order.

- [ ] **Step 4: Document honest capability differences**

Publish the actual D1 conformance matrix measured in Task 4/7; do not claim msgspec partial-update support unless it passed.

- [ ] **Step 5: Explicitly defer automatic switching CLI**

Mention that D2 does not add `rakit schema use` or package uninstall behavior.

- [ ] **Step 6: Run strict docs build**

```bash
uv run mkdocs build --strict
```

Expected: PASS.

- [ ] **Step 7: Commit docs**

```bash
git add docs CHANGELOG.md

git commit -m "docs: document schema adapter ecosystem"
```

Include `CHANGELOG.md` only if changed.

---

### Task 10: Full Verification and D2 Closure

**Files:**
- Modify only root-cause fixes discovered by verification.
- Final modify: `docs/roadmap.md` to mark D2 Complete and D3 Next.

**Interfaces:**
- Consumes: complete D2 branch.
- Produces: merge-ready D2 with fresh exact-head evidence.

- [ ] **Step 1: Run static gates**

```bash
uv run ruff format --check .
uv run ruff check .
uv run ty check
```

Expected: PASS.

- [ ] **Step 2: Run full pytest suite**

```bash
uv run pytest -q
```

Expected: PASS.

- [ ] **Step 3: Run canonical repository gates locally where available**

```bash
uv run pytest --cov
uv run mkdocs build --strict
uv run python scripts/check_artifacts.py
uv run pytest tests/release -v
```

Build all official distributions using the same loop as canonical CI and verify generated web assets remain reproducible.

- [ ] **Step 4: Open/update the D2 draft PR**

The PR must summarize:

```text
breaking Pydantic package extraction
new msgspec adapter
actual msgspec capability matrix
deterministic selection/default behavior
C4/D1 roadmap closure
no switching CLI
no release action
```

- [ ] **Step 5: Require full canonical CI green**

Require Python 3.12/3.13/3.14, Ruff, `ty`, full pytest, lowest-direct/latest dependency matrices, coverage, strict MkDocs, artifact dry run, and web asset reproducibility.

- [ ] **Step 6: Update roadmap closure only after the first full green D2 gate**

Set:

```text
D2 Schema Adapter Ecosystem — Complete
D3 Persistence Adapter Ecosystem — Next
```

Summarize the final measured msgspec capability set and package boundary outcome.

- [ ] **Step 7: Commit closure**

```bash
git add docs/roadmap.md
git commit -m "docs: close D2 schema adapter ecosystem"
```

- [ ] **Step 8: Require fresh exact-head canonical CI after closure commit**

The commit that marks D2 Complete must itself have the full canonical CI matrix green.

- [ ] **Step 9: Perform final diff review**

Confirm:

```text
no Pydantic/msgspec import in rakit-core
no concrete schema dependency or schema.pydantic entry point in rakit-web
no compatibility shim for old rakit_web.schema Pydantic API
Pydantic 4/4 conformance
msgspec advertises only proven capabilities
selection does not depend on discovery order
no schema switching CLI
both new packages included in artifact/release checks
no release/tag/version bump/publication
```

- [ ] **Step 10: Mark PR ready and merge only on explicit maintainer request**

Do not auto-merge before the maintainer asks after exact-head CI is verified green.

---

## Self-Review Against the Approved Spec

- Dedicated Pydantic package + breaking cleanup: Tasks 1, 7, 8.
- Dedicated msgspec package: Tasks 2, 7.
- Native schema classes/no DSL: Tasks 1-2 and Global Constraints.
- Presence-aware partial update: Tasks 1, 2, 4, 7.
- Honest msgspec capability set: Tasks 2, 4, 7, 9.
- Pydantic 4/4 re-proof: Tasks 4 and 7.
- Deterministic explicit/default selection: Tasks 3 and 8.
- Pydantic ordinary default without core/web coupling: Tasks 3 and 8.
- Installed-vs-configured discovery semantics: Tasks 3, 5, 8.
- C4 compatibility: Tasks 5 and 8.
- Packaging/artifact inclusion: Task 5 and Task 10.
- No automatic schema switching CLI: Global Constraints, Tasks 3, 9, 10.
- C4/D1 roadmap closure and D1-D6/D4.0-D4.6 structure: Task 6.
- D2 closure/D3 Next only after green CI: Task 10.
- Source-first/manual-before-regression workflow: Tasks 1-6 precede Tasks 7-8.
- No release/publication: Global Constraints and Task 10.

No approved D2 requirement is intentionally left without an implementation or verification task.
