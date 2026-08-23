# Persistence Capability Parity Research

**Status:** Active research

**Date:** 2026-08-23

**Branch:** `research/persistence-capability-parity`

**Purpose:** Record evidence-backed feasibility decisions for first-party persistence providers before any capability promotion or follow-on security/authentication work. This document is a research input, not an implementation plan and not proof that a capability is already shipped.

## Why this research exists

Rakit currently advertises persistence capabilities conservatively and only after behavioral proof. The shipped providers intentionally do not have forced parity.

The five canonical persistence capability identifiers are:

- `persistence.read`
- `persistence.write`
- `transactions.root-uow`
- `persistence.relationships`
- `concurrency.atomic-optimistic`

This research asks whether providers that currently expose only part of that profile could honestly support additional capabilities through their native public APIs, without adding a universal persistence DSL, fake ORM layer, backend-specific concerns in `rakit-core`, or semantic compromises.

The findings will also be used when revisiting Plan 03 — Authentication, Authorization, and Security — because the built-in authentication/session implementation is SQLAlchemy-backed and future work should distinguish genuinely generic persistence behavior from SQLAlchemy-ORM-only assumptions.

## Research rules

- Do not change advertised capabilities during research.
- Do not treat foreign-key metadata alone as proof of `persistence.relationships`.
- Do not emulate optimistic concurrency with a non-atomic read-check-write sequence.
- Use public, maintained backend APIs only.
- Preserve one Rakit root unit of work for mutations that claim `transactions.root-uow`.
- Fail closed on ambiguous or unsupported native shapes.
- Capability parity is allowed only when neutral Rakit semantics are actually satisfied; backend feature parity is not required.
- Composite resource identity remains outside this research unless a separate core contract change is explicitly approved.

---

# SQLAlchemy Core / Table

## Current shipped profile

Provider: `persistence.sqlalchemy-core`

| Capability | Shipped now | Research verdict |
| --- | --- | --- |
| `persistence.read` | Yes | Existing |
| `persistence.write` | Yes | Existing |
| `transactions.root-uow` | Yes | Existing |
| `persistence.relationships` | No | **PASS with explicit binding for ambiguity** |
| `concurrency.atomic-optimistic` | No | **PASS** |

**Feasibility conclusion:** SQLAlchemy Core can plausibly reach a truthful **5/5** Rakit persistence capability profile without constructing ORM mapped classes or redesigning Rakit core.

This is a feasibility result only. The provider remains at its currently shipped capability set until source implementation, manual verification, conformance coverage, and canonical CI prove the additional behavior.

## Existing architectural foundation

The current Core generated mutation executor already executes through the `AsyncConnection` owned by `SQLAlchemyCoreUnitOfWork`.

Relevant implementation seams:

- `packages/rakit-sqlalchemy/src/rakit_sqlalchemy/core_generated.py`
- `packages/rakit-sqlalchemy/src/rakit_sqlalchemy/core_uow.py`
- `packages/rakit-core/src/rakit_core/concurrency.py`
- `docs/guides/relationships.md`

The root Core UoW already owns one connection and transaction and is responsible for commit/rollback. Therefore neither relationship writes nor optimistic compare-and-write require a second transaction architecture.

## Atomic optimistic concurrency

### Verdict

**PASS**

### Native strategy

The required behavior can be represented as one conditional SQL mutation inside the existing root UoW:

```sql
UPDATE article
SET title = :title,
    version = :next_version
WHERE id = :id
  AND version = :expected_version
```

Interpretation:

- matched row count `1` → mutation succeeded;
- matched row count `0` → stale version / optimistic conflict;
- no separate read-check-write durability window is permitted.

The same principle applies to conditional delete.

### Existing gap

`SQLAlchemyCoreGeneratedResourceExecutorProvider` currently rejects configured concurrency and the executor advertises `atomic_concurrency=False`.

The generic concurrency providers in `rakit-core` currently obtain fields through attribute access. Core records are mappings (`dict(row)`), so a Core implementation needs mapping-aware version access rather than pretending Core rows are ORM objects.

Preferred implementation direction:

- add an adapter-owned mapping-aware concurrency provider first;
- avoid widening the neutral core record-access contract unless implementation pressure proves that generalization useful beyond SQLAlchemy Core.

### Required safety constraints

1. The version predicate must be part of the same SQL UPDATE/DELETE that performs the mutation.
2. A next version value, when required, must be written by that same mutation.
3. The mutation must use the connection from the Rakit root UoW.
4. Stale mutation must become the neutral `RESOURCE_CONFLICT` / HTTP 409 behavior.
5. Row-count semantics must be known to be usable for the active SQLAlchemy dialect/driver; uncertain row-count behavior must fail closed rather than silently treating a stale write as success.
6. Initial implementation should not depend on a `RETURNING` path whose affected-row semantics are not portable enough for the neutral contract.

### Atomic concurrency decision records

- **CORE-R1:** SQLAlchemy Core optimistic concurrency is feasible. **PASS**.
- **CORE-R2:** Concurrency must use one conditional SQL mutation; no read-check-write emulation.
- **CORE-R3:** Reliable matched-row semantics are mandatory; unsupported/uncertain dialect behavior fails closed.
- **CORE-R4:** Core requires mapping-aware concurrency version access rather than ORM-style `getattr` assumptions.

## Relationships

### Verdict

**PASS, with explicit physical binding required when schema paths are ambiguous.**

### Important distinction

`persistence.relationships` is a Rakit behavioral capability. It does not mean that a provider must reproduce every feature of SQLAlchemy ORM `relationship()`.

Rakit already declares portable relationship intent through `RelationshipDefinition`. SQLAlchemy Core only needs to validate and bind that semantic declaration to native `Table`, column, foreign-key, unique-constraint, and association-table metadata.

The source of truth remains:

```text
Rakit RelationshipDefinition = semantic intent
SQLAlchemy Core Table metadata = physical schema evidence
```

Core must not invent an ORM mapper or treat database metadata as complete application relationship intent.

### Shapes that are natively feasible

#### Many-to-one

A local foreign key can support a singular target relationship.

```text
orders.customer_id -> customers.id
```

#### One-to-many

The inverse collection can be implemented from the corresponding foreign-key path.

#### One-to-one

A foreign key combined with the necessary uniqueness semantics can provide physical evidence for one-to-one cardinality.

#### Many-to-many

A bridge table with foreign keys to source and target can implement link/unlink behavior through explicit Core INSERT/DELETE operations.

#### Association object

An association resource with its own identity and scalar fields can participate in the neutral association-object semantics, including editable association scalars and ordering when an explicit position field is declared.

### Why automatic FK discovery alone is insufficient

Schema metadata can identify physical foreign-key paths but cannot always know the relationship intent.

Example:

```text
customer.billing_address_id  -> address.id
customer.shipping_address_id -> address.id
```

There are two valid physical paths between the same tables. Core cannot safely guess which one a portable relationship declaration means.

The same ambiguity can occur with multiple bridge tables between the same source and target.

Therefore relationship support must be fail-closed:

```text
exactly one compatible physical path
    -> may infer automatically

zero compatible paths
    -> configuration error

more than one compatible path
    -> explicit binding required
```

### Explicit binding direction

A future adapter-owned binding may conceptually contain information such as:

```python
SQLAlchemyCoreRelationshipBinding(
    relationship_id="customer",
    source=orders,
    target=customers,
    local_columns=(orders.c.customer_id,),
    remote_columns=(customers.c.id,),
)
```

This example is intentionally non-final. The API must be designed separately before implementation.

The binding exists only to connect Rakit relationship intent to physical Core schema. It must not become a Rakit-wide persistence DSL.

### Relationship mutation strategy

All supported mutations can stay inside the existing Core root UoW and use explicit SQL expressions:

- many-to-one link → UPDATE local FK;
- nullable unlink → UPDATE local FK to NULL;
- one-to-many child creation → INSERT child with parent FK;
- many-to-many link → INSERT bridge row;
- many-to-many unlink → DELETE bridge row;
- reorder → UPDATE explicit position field;
- association scalar edit → UPDATE association resource;
- destructive operations → explicit Rakit relationship/destructive policy, never inferred from ORM cascade semantics.

### Deliberately unsupported / fail-closed shapes

A truthful 5/5 Rakit capability does **not** require SQLAlchemy ORM feature parity. The initial Core implementation should be allowed to reject shapes that cannot be represented honestly by the neutral relationship contract, including:

- arbitrary mapper-style `primaryjoin` expressions;
- custom relationship operators;
- convention-only relationships with no explicit physical binding/evidence;
- ambiguous multiple foreign-key paths without explicit binding;
- ambiguous multiple bridge tables without explicit binding;
- mapper-only lazy-loading semantics;
- mapper `viewonly` behavior as an implied Rakit relationship contract;
- mapper cascade / `delete-orphan` semantics as authorization for destructive behavior;
- composite Rakit resource identities until the global identity contract explicitly supports them.

### Relationship decision records

- **CORE-R5:** SQLAlchemy Core relationships are feasible without ORM mapping. **PASS**.
- **CORE-R6:** `RelationshipDefinition` remains the semantic source of truth.
- **CORE-R7:** A unique compatible FK path may be inferred for ergonomics.
- **CORE-R8:** Ambiguous paths require explicit adapter binding; Core must never guess.
- **CORE-R9:** SQLAlchemy ORM feature parity is not a requirement for the neutral Rakit capability.
- **CORE-R10:** Relationship mutation must remain inside the existing Core root UoW.
- **CORE-R11:** Unsupported or ambiguous relationship shapes fail closed rather than silently degrade.
- **CORE-R12:** Composite identity remains outside this parity effort unless separately approved.

## Proposed implementation shape — research only

```text
Rakit Core
    |
    | RelationshipDefinition
    v
rakit-sqlalchemy Core adapter
    |
    +-- unique compatible schema path --> infer binding
    |
    +-- ambiguous schema path ---------> require explicit binding
    |
    v
validate against Table / ForeignKeyConstraint metadata
    |
    v
Core relationship runtime
    |
    v
existing AsyncConnection
    |
    v
existing Rakit root UoW
```

Not required:

- fake SQLAlchemy mapper;
- generated ORM classes;
- universal persistence DSL;
- magic `Table.info` convention;
- treating constraint names as Rakit relationship identifiers.

## SQLAlchemy Core final research verdict

```text
Atomic optimistic concurrency   PASS
Relationships                  PASS*
Potential capability profile   5/5
Core redesign required         NO
Fake ORM required              NO
Explicit physical binding      YES when ambiguous
Fail-closed semantics          REQUIRED
Capability promotion now       NO
```

`*` PASS means conformance with the neutral Rakit relationship contract, not complete SQLAlchemy ORM relationship feature parity.

---

# Remaining providers

These sections will be filled by the same research process before implementation decisions are made.

## Tortoise ORM

**Status:** Pending research

Questions:

- Can relationships satisfy the neutral writable relationship contract through public APIs?
- Can optimistic compare-and-write be expressed atomically?
- Can both remain inside the already proven root transaction/UoW semantics?

## Peewee 4 Async ORM

**Status:** Pending research

Questions:

- Which relationship shapes are safely introspectable and writable through public Peewee metadata/query APIs?
- Can stale update/delete be rejected atomically through the official async execution layer?
- Are affected-row semantics reliable across the supported dependency floor?

## Piccolo ORM

**Status:** Pending research

Questions:

- Which native relation metadata maps cleanly to the Rakit contract?
- Can optimistic predicates be included in one mutation through public Piccolo APIs?
- Are transaction and affected-row semantics strong enough for honest capability advertisement?

## Masonite ORM

**Status:** Deferred research

Masonite remains outside the D3 closure gate and should not be mixed into this parity work unless the maintainer explicitly resumes its dedicated feasibility pass.

---

# Relationship to Plan 03

Plan 03 covers Authentication, Authorization, and Security. Existing built-in auth/session persistence is SQLAlchemy-backed. This parity research should inform future Plan 03 work in two ways:

1. Keep auth/security contracts neutral where the behavior is genuinely persistence-neutral.
2. Keep SQLAlchemy-specific storage/session implementation inside its adapter/package boundary rather than generalizing ORM assumptions into Rakit core.

This document does **not** authorize an auth backend rewrite and does not imply that every persistence provider must become an authentication storage provider. Authentication-provider parity must be evaluated separately from persistence capability parity.

# Research completion gate

This research workstream is ready to become implementation input only after:

- SQLAlchemy Core findings are recorded — **Complete**;
- Tortoise findings are recorded — Pending;
- Peewee findings are recorded — Pending;
- Piccolo findings are recorded — Pending;
- cross-provider comparison identifies any core-contract pressure;
- implementation order and acceptance matrix are written explicitly;
- no capability is promoted solely from research evidence.
