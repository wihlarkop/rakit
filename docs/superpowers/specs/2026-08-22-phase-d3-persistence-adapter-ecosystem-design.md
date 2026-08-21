# Phase D3 Persistence Adapter Ecosystem Design

**Status:** Approved for execution by maintainer delegation

## Context

D1 established versioned capability contracts and behavior-oriented conformance seams. D2 proved that first-party adapters can be split cleanly by implementation while Rakit core stays neutral. D3 applies the same discipline to persistence, but its scope is intentionally broader than a single second ORM: it establishes a real persistence ecosystem around multiple materially different persistence styles.

The existing first-party persistence implementation is SQLAlchemy ORM. It is mature, deeply integrated, and currently advertises five canonical capabilities:

- `persistence.read`
- `persistence.write`
- `persistence.relationships`
- `transactions.root-uow`
- `concurrency.atomic-optimistic`

The purpose of D3 is not to replace SQLAlchemy ORM. It is to prove that Rakit can support ORM models, schema-centric SQL tables, and independent async ORMs without leaking one backend's assumptions into core or web layers.

## Decision summary

1. **SQLAlchemy ORM remains Rakit's default persistence implementation.** `rakit[standard]` stays SQLAlchemy-based.
2. **SQLAlchemy Core/Table support is first-party D3 scope.** It lives in the existing `rakit-sqlalchemy` distribution because it shares the same upstream dependency and SQL expression/transaction stack, but it has a distinct integration/provider identity: `persistence.sqlalchemy-core`.
3. **Tortoise ORM is the primary independent ORM pressure-test** and lives in a new `rakit-tortoise` distribution with integration id `persistence.tortoise`.
4. **SQLModel is supported as a compatibility profile over the SQLAlchemy ORM adapter, not as a duplicate persistence adapter.** SQLModel models are SQLAlchemy models; creating a second claimant would add ambiguity without adding a new persistence semantic. D3 adds a real SQLModel compatibility/conformance proof and a convenience install extra.
5. **Piccolo ORM is the second independent async ORM target** and lives in `rakit-piccolo` with integration id `persistence.piccolo`. It is included after Tortoise so the neutral contracts are exercised against more than one non-SQLAlchemy model/query system.
6. **Django ORM is deliberately deferred from first-party D3 implementation.** Django 6.0 supports async ORM queries but still does not support transactions in async mode; transaction-bound work must be wrapped synchronously. That conflicts with Rakit's async root-UoW contract and would encourage a thread-wrapper compatibility layer instead of a clean adapter. It remains a D6/research candidate.
7. **Peewee is not a D3 first-party target.** Its 4.x line is active and increasingly async-capable, but the recent major-line transition creates unnecessary maintenance volatility while Tortoise and Piccolo already provide independent ORM pressure tests. It remains a later adapter candidate.
8. **Document databases/ODMs such as Beanie are not folded into the relational persistence contract in D3.** Their identity, relationship, query, and transaction semantics deserve a separate contract exercise rather than pretending they are relational ORM variants.
9. D3 does **not** force capability parity. Every provider advertises only capabilities proven by real behavioral conformance.
10. Native persistence models/schemas remain native. Rakit does not introduce a persistence DSL, base model, or fake wrapper merely to fit the current API.
11. D3 may be delivered as multiple squash-merged subphase PRs. D3 overall becomes Complete only after all accepted D3 subphases and the compatibility matrix are green on `main`.
12. No release, tag, or publication is part of D3.

## Why D3 is split

Supporting SQLAlchemy Core plus multiple ORMs in one monolithic PR would make review, regression attribution, and rollback unnecessarily risky. D3 therefore becomes an umbrella phase:

- **D3.0 — Persistence Integration Contract & Adapter Subject Generalization**
- **D3.1 — SQLAlchemy ORM Hardening + SQLAlchemy Core/Table**
- **D3.2 — Tortoise ORM**
- **D3.3 — SQLModel Compatibility Profile**
- **D3.4 — Piccolo ORM**
- **D3.5 — Persistence Integration DX, Compatibility Matrix & Closure**

Each subphase must be independently testable and may use its own PR. Every PR uses squash merge.

## D3.0 — Persistence Integration Contract & Adapter Subject Generalization

### Problem

The current adapter claim contract is effectively class-shaped:

```python
type AdapterClaim = Callable[
    [type, ResourceFieldPolicy], DataSource | ResourceAdapterRuntime | None
]
```

That works for SQLAlchemy declarative classes and Tortoise/Piccolo model classes, but SQLAlchemy Core's canonical resource representation is a `sqlalchemy.Table` object. Wrapping a `Table` in a fake class would preserve an accidental constraint rather than improve the abstraction.

### Decision

Generalize the adapter claim subject from `type` to a backend-neutral `object` (or an equivalent named neutral alias) throughout the compiler/registration path. Existing class-based callers remain valid because classes are objects. Core must not learn about `Table`, Tortoise, Piccolo, or any concrete backend type.

The generalization must preserve:

- deterministic adapter claim ordering;
- explicit ambiguity errors when multiple adapters claim the same subject;
- explicit adapter selection where already supported;
- existing SQLAlchemy ORM behavior;
- model/schema names in diagnostics via a neutral display helper rather than assuming `.__name__` always exists.

No user-facing persistence DSL is introduced.

## D3.1 — SQLAlchemy ORM Hardening + SQLAlchemy Core/Table

### Existing ORM path

`persistence.sqlalchemy` remains the existing SQLAlchemy ORM provider. D3 re-runs and, where useful, strengthens its real conformance proofs after D3.0 so the generalized subject contract does not regress ORM usage.

### SQLAlchemy Core path

The Core integration is schema-centric and accepts native `sqlalchemy.Table` objects. It lives in `rakit-sqlalchemy` and uses a distinct plugin/descriptor so ORM and Core behavior are not conflated.

Recommended public shape:

```python
SQLAlchemyPlugin(session_factory=...)
SQLAlchemyCorePlugin(engine=...)
```

The exact constructor may be refined during implementation, but Core must use SQLAlchemy's async engine/connection transaction APIs directly and must not manufacture ORM classes internally.

### SQLAlchemy Core capability policy

Target capabilities, subject to conformance:

- `persistence.read` — target required.
- `persistence.write` — target required for scalar insert/update/delete.
- `transactions.root-uow` — target required if one async connection/transaction can own the full operation boundary cleanly.
- `concurrency.atomic-optimistic` — target only when a conditional update/delete can prove compare-and-write atomicity inside the owning transaction.
- `persistence.relationships` — **not assumed**. Foreign-key metadata is not equivalent to ORM relationship graph semantics. Advertise only if Rakit's v1 relationship contract can be satisfied without inventing an ORM layer.

## D3.2 — Tortoise ORM

Tortoise is chosen because its model, query, relationship, and transaction APIs differ materially from SQLAlchemy. It is async-first and provides an explicit transaction context, making it a strong architectural adversary for Rakit.

The first-party package is `rakit-tortoise`, importing as `rakit_tortoise`, with provider/integration id `persistence.tortoise`.

The supported dependency line begins at `tortoise-orm>=1.1.7,<2`, subject to lowest-direct CI. SQLite is the canonical contract-test backend.

Target capability policy:

- `persistence.read` — required.
- `persistence.write` — implement if ordinary scalar CRUD maps cleanly to neutral mutation semantics.
- `transactions.root-uow` — implement only with one explicit transaction context/connection owning commit/rollback.
- `persistence.relationships` — optional, only after real FK and collection behavior proves the neutral contract.
- `concurrency.atomic-optimistic` — optional, only if compare-and-write is genuinely atomic and does not rely on private/brittle APIs.

Non-parity is an accepted outcome.

## D3.3 — SQLModel Compatibility Profile

SQLModel is both a Pydantic model system and a SQLAlchemy ORM model layer. D3 therefore does **not** create `rakit-sqlmodel` or a second adapter claim path.

Instead D3 adds:

- real SQLModel models exercised through `SQLAlchemyPlugin`;
- compatibility tests proving introspection, reads, generated writes, transactions, and concurrency continue to work where the underlying SQLAlchemy mapping supports them;
- a convenience `rakit[sqlmodel]` extra that installs the existing SQLAlchemy adapter plus a supported SQLModel version;
- documentation that the configured persistence provider remains `persistence.sqlalchemy`.

This avoids duplicate ownership and keeps capability reporting truthful.

The initial SQLModel compatibility floor targets the current supported 0.0.x line, with the exact lower bound fixed by lowest-direct verification rather than guessed from latest-only behavior.

## D3.4 — Piccolo ORM

Piccolo is an active typed ORM/query builder with native asyncio support and Python 3.12–3.14 compatibility. It provides a second independent async persistence model after Tortoise and therefore helps distinguish genuinely neutral Rakit semantics from one-off Tortoise accommodations.

The package is `rakit-piccolo`, importing as `rakit_piccolo`, with provider/integration id `persistence.piccolo`.

Target capability policy mirrors Tortoise:

- `persistence.read` — required.
- scalar `persistence.write` — targeted.
- `transactions.root-uow` — targeted only if Piccolo's public transaction API cleanly owns the root boundary.
- relationships and optimistic concurrency — advertised only after behavioral proof.

No Piccolo migration/admin/auth subsystem is adopted; Rakit integrates only persistence semantics required by its contracts.

## Shared canonical capability semantics

### `persistence.read@v1`

A conforming adapter must provide Rakit-neutral:

- field and identity metadata;
- deterministic list ordering;
- detail lookup by `RecordIdentity`;
- every pagination strategy it advertises in `DataSourceCapabilities`;
- supported filtering, sorting, and search for declared field policy;
- portable not-found and validation/configuration failures rather than leaking raw backend exceptions.

### `persistence.write@v1`

A conforming adapter must prove ordinary scalar:

- create;
- update of explicitly supplied writable fields;
- delete;
- durable results after successful completion;
- rollback/no partial durability on failed mutation;
- Rakit-neutral error translation.

This capability does not imply relationship graph mutation or optimistic concurrency.

### `persistence.relationships@v1`

A provider advertises this only after proving neutral relationship metadata and mutations across representative singular and collection relationships. Database foreign keys alone are insufficient.

### `transactions.root-uow@v1`

One root operation owns commit/rollback. Nested mutation work must participate in that root boundary rather than independently committing durable state.

### `concurrency.atomic-optimistic@v1`

The version/precondition check and write must be one atomic database operation or one transactionally protected compare-and-write sequence. A stale token/version must fail without committing the mutation.

## Package architecture

```text
rakit-core
   ^
   |-- rakit-sqlalchemy
   |     |-- persistence.sqlalchemy       (ORM, default)
   |     `-- persistence.sqlalchemy-core  (Table/Core)
   |
   |-- rakit-tortoise                     (independent ORM)
   `-- rakit-piccolo                      (independent ORM)

SQLModel -- compatibility proof --> rakit-sqlalchemy / persistence.sqlalchemy

rakit-web -> neutral DataSource / generated runtime / UoW contracts only
rakit     -> extras, install guidance, discovery inventory
```

## Adapter selection

No first-installed-wins behavior is introduced.

- SQLAlchemy declarative/SQLModel classes are owned by the SQLAlchemy ORM claimant.
- SQLAlchemy `Table` objects are owned by the SQLAlchemy Core claimant.
- Tortoise model classes are owned by Tortoise.
- Piccolo table/model classes are owned by Piccolo.
- Explicit adapter selection remains available where the existing registration API supports it.
- If two adapters claim one subject, compilation fails with the existing ambiguity semantics; D3 does not silently choose based on installation order.

## Identity policy

Initial first-party support remains conservative: one scalar primary key representable by Rakit's existing `RecordIdentity` (`int`, `str`, or `UUID`). Composite-key support is not introduced as a side effect of adding adapters. A future contract version may broaden identity semantics deliberately.

## Field policy

All adapters fail closed at claim/compile time when a resource declares query behavior the backend cannot safely honor.

Portable baseline:

- search: text-like fields only;
- sort: scalar concrete fields;
- filters: equality/inequality/comparison where coercion is safe, string contains, membership, and null checks where the backend supports them;
- generated mutation fields: concrete writable non-identity scalar fields;
- sensitive-field conventions continue to pass through `infer_field_security`.

Unsupported JSON/binary/custom fields may be readable but must not silently pretend to support portable search/filter/sort semantics.

## Install UX

- `pip install "rakit[sqlalchemy]"` — SQLAlchemy ORM and Core integration package.
- `pip install "rakit[tortoise]"` — Tortoise adapter.
- `pip install "rakit[sqlmodel]"` — SQLAlchemy adapter plus supported SQLModel dependency; provider remains `persistence.sqlalchemy`.
- `pip install "rakit[piccolo]"` — Piccolo adapter.
- `pip install "rakit[standard]"` — remains SQLAlchemy ORM-oriented; D3 does not turn `standard` into an install-everything bundle.

Direct distribution installation remains supported for first-party adapter packages.

## Delivery decomposition and merge policy

### D3.0 — Persistence Integration Contract & Adapter Subject Generalization

Generalize the claim subject to neutral `object`, add neutral diagnostic naming, strengthen shared persistence conformance seams, and prove existing SQLAlchemy ORM behavior remains unchanged.

### D3.1 — SQLAlchemy ORM Hardening + SQLAlchemy Core/Table

Implement native `Table` support in `rakit-sqlalchemy`, real Core read/write/UoW conformance, discovery metadata, and capability profile. Do not fake relationship parity.

### D3.2 — Tortoise ORM

Complete `rakit-tortoise` read support first, then add only write/UoW/higher capabilities proven by the shared contract.

### D3.3 — SQLModel Compatibility Profile

Add real SQLModel compatibility tests and install UX on top of the SQLAlchemy ORM adapter. No duplicate provider.

### D3.4 — Piccolo ORM

Add `rakit-piccolo` and prove its honest capability profile.

### D3.5 — Persistence Integration DX, Compatibility Matrix & Closure

Publish a provider/capability matrix, clean-install smoke coverage for extras, artifact inventory, lowest/latest dependency compatibility, docs, and canonical roadmap closure. Mark D4 Next only after the accepted D3 matrix is green on `main`.

Each subphase may be a separate PR. Every merge uses **squash**. If implementation reveals that a later adapter would require changing a canonical capability contract rather than merely implementing it, stop that adapter at the highest honest capability set and record the contract pressure point for a future version instead of widening v1 silently.

## Non-goals

- replacing SQLAlchemy ORM as default;
- migration-tool abstraction across Alembic/Aerich/Piccolo migrations;
- multi-database routing;
- composite primary keys;
- Rakit persistence model DSL/base classes;
- automatic dependency uninstall/switch CLI;
- forced capability parity;
- Django async transaction emulation through thread wrappers;
- document-database semantics under the relational v1 contract;
- release, tag, or publication.

## Acceptance criteria

D3 overall is complete when:

1. The adapter-claim subject no longer assumes every backend resource is a class, while existing class-based APIs remain source-compatible.
2. Existing SQLAlchemy ORM conformance remains green with no capability regression.
3. Native SQLAlchemy `Table` resources work through a first-party Core integration and every advertised Core capability has a real proof.
4. `rakit-tortoise` is an official typed distribution and every advertised Tortoise capability has a real proof.
5. Real SQLModel models pass the supported SQLAlchemy compatibility matrix without a duplicate persistence provider.
6. `rakit-piccolo` is an official typed distribution and every advertised Piccolo capability has a real proof.
7. Core/web contain no concrete SQLAlchemy, Tortoise, SQLModel, or Piccolo persistence imports.
8. Discovery/configured-integration metadata is deterministic and actionable.
9. Clean-installed extras and official artifacts are tested outside the repository checkout.
10. The public persistence compatibility matrix documents capability differences and intentional non-parity.
11. No temporary CI/helper files remain in final subphase PRs.
12. `docs/roadmap.md` exposes D3.0–D3.5 status and marks D3 overall Complete only after all accepted subphases pass canonical CI.
13. Every D3 PR is exact-head green and squash-merged.
