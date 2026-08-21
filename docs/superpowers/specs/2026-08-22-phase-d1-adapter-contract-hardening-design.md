# Rakit Phase D1 Adapter Contract Hardening Design

Date: 2026-08-22
Status: Approved design direction; written for maintainer review before implementation planning

## 1. Goal

Phase D1 establishes an internal, versioned, per-capability conformance foundation for Rakit adapters before additional schema, persistence, and web-framework implementations are added in D2-D4.

D1 hardens contracts that already exist in Rakit. It does not create a public adapter SDK, a public conformance CLI, or a new runtime dependency. The purpose is to make an advertised capability trustworthy: if an adapter advertises a canonical Rakit capability, its implementation must satisfy that capability's behavioral contract.

## 2. Design Principles

D1 locks the following principles:

1. **Hard conformance.** An adapter must not advertise a capability unless it satisfies the complete contract for that capability. There is no hidden partial-support state.
2. **Per-capability contracts.** Capability is the smallest unit of conformance. An adapter may conform to one capability without being forced to claim unrelated capabilities.
3. **Canonical Rakit vocabulary.** Official Rakit capabilities are governed centrally by `rakit-core`. Third-party integrations may use their own vendor namespace, but they cannot redefine canonical Rakit capabilities or create framework-owned capability names arbitrarily.
4. **Versioned contracts.** Every canonical capability contract has an explicit contract version. D1 begins at version `1`; the version is metadata and does not change existing capability identifiers such as `persistence.read`.
5. **Explicit prerequisites.** Canonical capability metadata may declare universal semantic prerequisites. Missing advertised prerequisites are a hard conformance failure. Prerequisites must not encode incidental requirements of one first-party implementation.
6. **Behavior over implementation.** Conformance checks assert externally observable Rakit semantics, not adapter class names, private functions, or implementation-specific architecture.
7. **Real first-party proof.** Canonical capabilities currently advertised by first-party integrations must be demonstrated by real first-party implementations. Fakes may cover edge cases but cannot be the sole conformance proof.
8. **Internal before public.** D1 machinery remains internal. A public `rakit.testing` or adapter-authoring SDK is deferred to D5 after D2-D4 provide real pressure on the abstraction.

## 3. Architectural Boundary

Existing runtime capability primitives remain lightweight and compatible:

```text
Capability
CapabilitySet
CapabilityProvider
CapabilityRequirement
CapabilityReport
CapabilityAnalysis
```

D1 does not move governance metadata into `Capability`. Instead it adds a separate conformance/governance layer:

```text
runtime capability primitives
        |
        v
canonical capability contract registry
        |
        v
internal per-capability conformance registry
        |
        v
adapter fixture/harness
        |
        v
behavioral checks
        |
        v
structured conformance results
```

This keeps runtime capability negotiation independent from contract governance and testing policy.

## 4. Canonical Capability Contract Registry

A focused `rakit-core` module owns canonical capability contract metadata. The conceptual model is:

```python
@dataclass(frozen=True, slots=True)
class CapabilityContract:
    capability: Capability
    version: int
    category: str
    prerequisites: CapabilitySet
```

The registry is immutable and contains metadata for every canonical capability currently defined in `adapter_capabilities.py`.

D1 does not rename existing capability identifiers. Existing identifiers such as `persistence.read`, `schema.input-validation`, and `web.asgi` remain stable.

Registry validation is strict:

- capability identifiers are unique;
- contract versions are positive integers;
- categories are non-empty canonical metadata;
- prerequisites reference known canonical capabilities;
- self-dependencies are rejected;
- prerequisite cycles are rejected;
- every first-party canonical capability constant has contract metadata;
- canonical identifiers cannot be redefined by vendor integrations.

A lookup helper may expose canonical metadata internally without changing `CapabilitySet`, provider, requirement, or C4 analysis semantics.

## 5. Initial Canonical Contract Set

D1 covers the canonical adapter vocabulary already present in Rakit:

### Web

- `web.asgi`
- `web.http-routing`
- `web.streaming-response`

### Schema

- `schema.field-introspection`
- `schema.input-validation`
- `schema.output-serialization`
- `schema.partial-update`

### Persistence and transactions

- `persistence.read`
- `persistence.write`
- `persistence.relationships`
- `transactions.root-uow`
- `concurrency.atomic-optimistic`

All begin at contract version `1`.

Prerequisites are declared only where semantics are universal. Expected examples include `persistence.relationships` requiring `persistence.read`, and `concurrency.atomic-optimistic` requiring the write/transaction capabilities that are genuinely required by Rakit's concurrency semantics. Exact prerequisite edges must be validated against current semantics during implementation rather than copied from incidental SQLAlchemy behavior.

## 6. Internal Per-Capability Conformance Model

D1 introduces an internal conformance registry that maps a canonical capability contract version to behavioral checks. Conceptually:

```python
CapabilityConformanceSpec(
    capability=PERSISTENCE_READ,
    version=1,
    checks=(...),
)
```

Checks are grouped by capability rather than by adapter. This allows future adapters to advertise only the capabilities they actually satisfy.

The conformance pipeline is:

1. validate the canonical registry;
2. validate the adapter's advertised canonical capabilities;
3. validate advertised prerequisites;
4. resolve the conformance spec matching each capability contract version;
5. run behavioral checks through an adapter-specific fixture/harness;
6. return structured internal results.

An adapter that advertises a capability without all canonical prerequisites fails before behavioral checks run.

## 7. Structured Results and Failure Classes

D1 distinguishes three failure classes:

### 7.1 Registry/configuration failure

The canonical definition itself is invalid, for example duplicate identifiers, invalid versions, unknown prerequisites, self-dependency, or cycles.

### 7.2 Advertisement failure

An adapter advertises a canonical capability while omitting a required canonical prerequisite.

### 7.3 Behavioral conformance failure

The advertisement graph is valid, but the implementation violates one or more behavioral checks.

Results are structured internal data rather than unstructured assertion text. Conceptually:

```python
CapabilityConformanceResult(
    capability="persistence.read",
    contract_version=1,
    passed=True,
    failures=(),
)
```

D1 does not add a public exception hierarchy solely for conformance. Public error/API decisions remain deferred until D5 unless implementation reveals a genuine runtime requirement.

## 8. First-Party Proof Strategy

The existing first-party implementations are the initial proof targets:

```text
SQLAlchemy / persistence implementation
  persistence.read v1
  persistence.write v1
  persistence.relationships v1
  transactions.root-uow v1
  concurrency.atomic-optimistic v1

Pydantic / schema implementation
  schema.field-introspection v1
  schema.input-validation v1
  schema.output-serialization v1
  schema.partial-update v1

Current web runtime
  web.asgi v1
  web.http-routing v1
  web.streaming-response v1
```

The exact mapping must be derived from the capability descriptors actually advertised in the repository. D1 must not fabricate support to make a matrix green.

If an existing first-party descriptor advertises a capability whose semantics cannot be honestly specified, implementation must either clarify and codify the semantics or stop advertising that capability. A weak or implementation-specific contract is not acceptable.

Existing datasource/storage contract tests should be reused or refactored where their behavioral semantics are relevant. D1 must not create an unrelated parallel testing architecture.

## 9. Internal Conformance Matrix

D1 produces a human-readable internal conformance matrix derived from canonical metadata and first-party proof. Its purpose is maintainer review and preparation for D2-D4, not a public compatibility guarantee.

The matrix identifies:

- integration/adapter;
- advertised canonical capability;
- contract version;
- prerequisite validity;
- behavioral conformance status.

The matrix must not imply that D1 exposes a stable third-party testing API.

## 10. Compatibility Requirements

D1 is additive hardening. It must preserve existing semantics and compatibility for:

- `Capability`;
- `CapabilitySet`;
- `CapabilityProvider`;
- `CapabilityRequirement`;
- `CapabilityAnalysis`;
- `IntegrationDescriptor`;
- configured integration inventory;
- C4 `rakit capabilities` output and JSON schema v1;
- aggregate `rakit check` behavior;
- generated API/runtime behavior.

Capability contract versions are metadata and do not alter capability strings or the C4 wire schema in D1.

D1 adds no runtime dependency.

## 11. Public API Boundary

The following are explicitly out of scope for D1:

- public `rakit.testing`;
- public adapter contract decorators/helpers;
- `rakit conformance` CLI;
- automatic third-party package discovery for conformance;
- compatibility certification/badges;
- public vendor capability registration API.

These belong to D5 after msgspec (D2), a second persistence adapter such as Tortoise (D3), and the D4 web-framework integrations expose real extension-author requirements.

## 12. Development and Verification Workflow

D1 follows the established Rakit workflow:

```text
source / internal conformance implementation
  -> non-test/manual verification
  -> regression and conformance tests
  -> full CI
  -> docs/roadmap closure
  -> exact-head CI
```

Implementation planning must not force test-first ordering that conflicts with this project workflow. Existing failing regressions may of course be used as evidence when debugging.

## 13. Roadmap Restructure

The canonical roadmap must be updated as part of D1 work:

- Phase C4 Capability Discovery: `Complete`;
- Phase D becomes a structured adapter-ecosystem program:
  - **D1 — Adapter Contract Hardening**;
  - **D2 — Schema Adapter Ecosystem**, beginning with msgspec as the intended second implementation;
  - **D3 — Persistence Adapter Ecosystem**, beginning with Tortoise ORM as the intended second implementation;
  - **D4 — Web Framework Integrations**;
  - **D5 — Adapter Authoring DX / SDK**;
  - **D6 — Additional First-party Adapters**, demand-driven.

D4 is further planned as:

- **D4.0 — Web Integration Contract**;
- **D4.1 — Litestar**;
- **D4.2 — FastAPI**;
- **D4.3 — Starlette**;
- **D4.4 — Flask**;
- **D4.5 — Sanic**;
- **D4.6 — Integration DX & Compatibility Matrix**.

D1 is marked `Complete` only after all D1 acceptance gates pass. Until then it is the active/next phase.

## 14. Acceptance Criteria

D1 is complete only when all of the following are true:

1. Every canonical capability has versioned contract metadata at v1.
2. Canonical registry validation rejects duplicates, invalid versions, unknown prerequisites, self-dependencies, and cycles.
3. Conformance contracts are defined per capability.
4. Advertising a capability without its required advertised prerequisites is a hard failure.
5. Every canonical capability advertised by a first-party integration has real first-party behavioral proof.
6. Contract checks test observable Rakit behavior rather than implementation details.
7. Structured conformance results are available internally.
8. No public `rakit.testing`, conformance CLI, or third-party adapter SDK is introduced.
9. Existing C4 capability discovery/check output remains compatible.
10. Existing regression suite remains green.
11. Maintainer-facing docs explain the internal architecture and D5 boundary without promising an unstable public API.
12. `docs/roadmap.md` records C4 as Complete and the agreed D1-D6 / D4.0-D4.6 structure.
13. D1 introduces no new runtime dependency.
14. Full CI and exact-head closure CI pass before D1 is marked Complete.
15. No release, tag, or package publication occurs as part of D1.

## 15. Non-Goals

D1 does not implement msgspec, Tortoise ORM, Litestar, FastAPI integration packaging, Starlette integration packaging, Flask, Sanic, or any other second adapter. It builds the conformance foundation those phases will pressure-test.

D1 also does not claim that the internal conformance abstractions are the final public adapter-authoring API. D2-D4 are intentionally allowed to reshape internal machinery before D5 freezes a public extension surface.
