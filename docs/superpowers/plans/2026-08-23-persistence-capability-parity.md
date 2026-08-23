# Persistence Capability Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise the four shipped 3/5 persistence providers to the highest truthfully proven capability profile, targeting 5/5 for SQLAlchemy Core, Tortoise ORM, Piccolo ORM, and Peewee Async ORM.

**Architecture:** Keep Rakit's existing neutral relationship, concurrency, identity, generated-operation, and root-UoW contracts unchanged unless implementation evidence proves a real gap. Implement each provider with its native metadata/query/transaction mechanisms, prove behavior through the existing capability conformance hooks, and advertise capabilities only after source behavior plus compatibility proof is green.

**Tech Stack:** Python 3.12-3.14, Rakit monorepo, SQLAlchemy 2.0.x async/Core, Tortoise ORM 1.x, Piccolo 1.x, Peewee 4.x async, pytest/anyio, ruff, ty, uv, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-23-persistence-capability-parity-design.md`

## Global Constraints

- D3 remains Complete. This is an additive parity workstream.
- SQLAlchemy ORM remains the default/reference provider and must not regress.
- Do not create a universal persistence DSL, fake ORM, shared rowcount abstraction, or speculative `ResourceAdapterRuntime` expansion.
- Keep backend classes, sessions/connections, query builders, metadata, and transaction objects inside adapter packages.
- Use the existing `RelationshipDefinition`, `RelationshipMetadata`, `RelationshipChangePlan`, `ConcurrencyVersionProvider`, `ConcurrencyTokenService`, and root-UoW contracts.
- Integer version-column concurrency is the first common implementation target. Snapshot/no-op support remains disabled or fail-closed until separately proven for the provider/runtime matrix.
- Association objects are explicit resources. Writable ordering requires an explicit position field. Native cascade metadata never grants destructive Rakit permission.
- Ambiguous or unsupported native relationship shapes fail closed.
- Source/feature work comes first; perform source/manual/non-test verification before adding permanent regression/conformance tests.
- Capability profile files are updated last for each provider.
- Every provider PR is independently reviewable and squash-merged. Refresh the next provider branch from canonical `main` after each merge where practical.
- No release, tag, TestPyPI, PyPI, or version bump is authorized.

---

## Workstream Map

- [ ] **P0 — Shared acceptance contract**: use this master plan and the locked spec as the acceptance source. Do not add runtime abstraction merely for P0.
- [ ] **P1 — SQLAlchemy Core**: execute `docs/superpowers/plans/2026-08-23-persistence-capability-parity-p1-sqlalchemy-core.md`.
- [ ] **P2 — Tortoise ORM**: execute `docs/superpowers/plans/2026-08-23-persistence-capability-parity-p2-tortoise.md`.
- [ ] **P3 — Piccolo ORM**: execute `docs/superpowers/plans/2026-08-23-persistence-capability-parity-p3-piccolo.md`.
- [ ] **P4 — Peewee Async ORM**: execute `docs/superpowers/plans/2026-08-23-persistence-capability-parity-p4-peewee.md`.
- [ ] **P5 — Cross-provider closure**: execute `docs/superpowers/plans/2026-08-23-persistence-capability-parity-p5-closure.md`.

Locked order:

```text
P0 -> P1 SQLAlchemy Core -> P2 Tortoise -> P3 Piccolo -> P4 Peewee -> P5 Closure
```

Do not reorder merely for convenience. Reordering is justified only when merged implementation evidence creates a dependency or blocker that the locked design did not anticipate; document that evidence before changing order.

---

## P0 — Shared Acceptance Contract

### Task 0.1: Reconfirm existing neutral seams before runtime work

**Read:**
- `packages/rakit-core/src/rakit_core/concurrency.py`
- `packages/rakit-core/src/rakit_core/relationships.py`
- `packages/rakit-core/src/rakit_core/relationship_mutations.py`
- `packages/rakit-core/src/rakit_core/operations.py`
- `packages/rakit-core/src/rakit_core/compiler.py`
- `packages/rakit-core/src/rakit_core/testing/capability_conformance.py`
- `packages/rakit-sqlalchemy/src/rakit_sqlalchemy/relationships.py`
- `packages/rakit-sqlalchemy/tests/test_concurrency.py`
- `packages/rakit-sqlalchemy/tests/test_relationship_introspection.py`
- `packages/rakit-sqlalchemy/tests/test_relationship_mutations.py`
- `packages/rakit-sqlalchemy/tests/test_graph_mutations.py`

- [ ] Confirm `ConcurrencyVersionProvider` still exposes `version_for`, `predicate_values_for`, and `next_values_for` with no provider types.
- [ ] Confirm compiler relationship validation still dispatches through adapter datasource `validate_relationship(...)` rather than importing concrete ORMs.
- [ ] Confirm the operation contract still requires `atomic_concurrency=True` only with root-UoW participation.
- [ ] Confirm capability conformance still exposes `assert_relationship_semantics()` and `assert_atomic_optimistic_semantics()`.
- [ ] Record any drift from the approved spec before starting P1. If no drift exists, do not change core.

### Task 0.2: Establish the common provider promotion checklist

For every P1-P4 provider, require all applicable items before editing `capabilities.py`:

- [ ] Initial scoped missing row maps to neutral not-found behavior.
- [ ] Invalid/stale concurrency token maps to `RESOURCE_CONFLICT` / 409.
- [ ] Atomic UPDATE includes identity + expected predicate + user values + next version in one native mutation.
- [ ] Atomic DELETE includes identity + expected predicate in one native mutation.
- [ ] A stale race after initial validation is conflict, not not-found and not silent success.
- [ ] Successful mutation participates in the existing root UoW and rolls back on later failure.
- [ ] Relationship native metadata validates target, kind, cardinality, nullable semantics, and writable constraints.
- [ ] Singular, collection, association-object, and ordering behavior are proven for the provider-supported v1 shapes.
- [ ] Candidate resolution observes the resource's scoped visibility path.
- [ ] Destructive policy is Rakit-owned; backend cascade does not authorize deletion.
- [ ] Ambiguous/unsupported physical relationships fail closed.
- [ ] Provider-specific lowest/latest/runtime matrix is green.
- [ ] Existing read/write/root-UoW conformance remains green.
- [ ] Capability profile and artifact assertions are changed only after all required proof is green.

### Task 0.3: Do not pre-abstract conformance helpers

- [ ] Start P1 with provider-local tests/harness changes.
- [ ] Extract a helper into `rakit_core.testing` only after at least two completed provider implementations demonstrate materially identical neutral assertions.
- [ ] Reject any proposed helper that knows an ORM type, rowcount API, RETURNING shape, query builder, connection/session, or mapper metadata.

No P0 runtime commit is required if the existing seams match the spec.

---

## Provider PR Workflow

For each P1-P4 provider:

1. [ ] Create provider branch from current canonical `main` using a focused name such as `parity-p1-sqlalchemy-core`.
2. [ ] Implement atomic source behavior.
3. [ ] Run formatting/import/type/static checks for touched source and a small direct runtime smoke without adding permanent tests yet.
4. [ ] Implement relationship introspection/read/mutation source behavior.
5. [ ] Run direct graph mutation/rollback smoke and inspect generated SQL/query behavior where relevant.
6. [ ] Add permanent focused regression tests plus the provider's canonical capability conformance implementation.
7. [ ] Run provider package tests.
8. [ ] Run `uv run ruff format --check .`, `uv run ruff check .`, and `uv run ty check`.
9. [ ] Run required lowest/latest/backend matrix for that provider.
10. [ ] Update the provider capability profile last.
11. [ ] Update any artifact capability assertion affected by that provider.
12. [ ] Run full CI on the exact PR head.
13. [ ] Review diff for accidental core/web/backend leakage.
14. [ ] Squash merge only when the exact head is green and review is clean.
15. [ ] Refresh the next provider work from new canonical `main`.

Suggested provider-local command baseline:

```bash
uv sync --all-packages --dev --locked
uv run pytest packages/<provider-package>/tests -q
uv run ruff format --check .
uv run ruff check .
uv run ty check
```

Use additional backend commands defined in the provider subplan. Do not treat a SQLite-only run as proof for a capability whose research gate explicitly names PostgreSQL/MySQL/Cockroach behavior.

---

## Cross-Provider Invariants During Implementation

- [ ] No provider may fall back from compare-and-write to `read -> check -> unconditional write`.
- [ ] A prior read may classify initial not-found/token mismatch, but final authorization to mutate always resides in the conditional database mutation.
- [ ] Relationship graph writes use the same root UoW as the parent mutation.
- [ ] Association-object scalar updates use explicit safe scalar allow-lists already carried by neutral Rakit plans.
- [ ] Reordering writes only the declared position field and remains deterministic.
- [ ] Provider-native convenience APIs are optional; explicit native queries are preferred when they make scope, transaction ownership, or concurrency behavior easier to prove.
- [ ] SQLAlchemy ORM tests serve as observable-behavior reference only. Do not copy `AsyncSession`, mapper, or relationship-loader assumptions into other providers or core.

---

## Merge and Stop Conditions

A provider can stop below 5/5 if implementation evidence contradicts research. If that happens:

- [ ] Leave its capability profile honest.
- [ ] Record the precise blocking backend/runtime/contract fact in the provider plan and compatibility docs.
- [ ] Do not widen the v1 neutral contract just to force parity.
- [ ] Continue to the next provider only if the blocker is provider-local.
- [ ] Stop the whole workstream only if a blocker demonstrates an actual shared-contract defect affecting subsequent providers.

P5 closure begins after P1-P4 are individually merged or have an explicitly documented honest lower ceiling.

---

## Final Definition of Done

- [ ] SQLAlchemy Core, Tortoise, Piccolo, and Peewee each advertise only capabilities proven by permanent behavioral conformance.
- [ ] The intended successful outcome is 5/5 for all four, but honest non-parity is acceptable if a provider gate fails.
- [ ] SQLAlchemy ORM remains 5/5 with no regression.
- [ ] `docs/guides/persistence-adapters.md`, capability matrices, artifact assertions, and discovery output match shipped truth.
- [ ] Python 3.12/3.13/3.14, lowest-direct, latest-allowed, release-gate, and artifact-dry-run CI are green on the closure PR exact head.
- [ ] D3 remains marked Complete; parity is recorded as additive completed work.
- [ ] No release/tag/publication has occurred.
