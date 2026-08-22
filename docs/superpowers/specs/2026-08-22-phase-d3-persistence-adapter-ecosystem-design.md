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
4. **Peewee 4 is a first-party D3 target** because its current 4.x line has official asyncio support and exercises a different query/model style. It lives in `rakit-peewee` with integration id `persistence.peewee`.
5. **Piccolo ORM is a first-party D3 target** and lives in `rakit-piccolo` with integration id `persistence.piccolo`. It provides another native async ORM/query model independent of SQLAlchemy and Tortoise.
6. **Masonite ORM is included as a D3 feasibility/implementation subphase.** The maintained upstream package is now `masonite-framework-orm` while imports remain `masoniteorm`. If its public runtime/transaction APIs satisfy Rakit's async contracts cleanly, Rakit adds `rakit-masonite-orm` / `persistence.masonite`; if not, D3 records the precise pressure point and defers first-party runtime support rather than adding blocking/thread-wrapper semantics merely for parity.
7. **Django ORM is deliberately deferred from first-party D3 implementation.** Django 6.0 supports async ORM queries but still does not support transactions in async mode; transaction-bound work must be wrapped synchronously. That conflicts with Rakit's async root-UoW contract.
8. **Document/remote persistence families such as MongoDB/Beanie, Turso/libSQL, and CouchDB remain accepted future ecosystem directions but are not forced through the relational ORM v1 contract.** They move to D6/contract research so identity, query, relationship, and transaction semantics can be modeled honestly.
9. D3 does **not** force capability parity. Every provider advertises only capabilities proven by real behavioral conformance.
10. Native persistence models/schemas remain native. Rakit does not introduce a persistence DSL, base model, or fake wrapper merely to fit the current API.
11. D3 is delivered as multiple squash-merged subphase PRs. D3 overall becomes Complete only after all accepted D3 subphases and the compatibility matrix are green on `main`.
12. No release, tag, or publication is part of D3.

## Why D3 is split

Supporting SQLAlchemy Core plus several independent ORMs in one monolithic PR would make review, regression attribution, and rollback unnecessarily risky. D3 therefore becomes an umbrella phase:

- **D3.0 — Persistence Integration Contract & Adapter Subject Generalization**
- **D3.1 — SQLAlchemy ORM Hardening + SQLAlchemy Core/Table**
- **D3.2 — Tortoise ORM**
- **D3.3 — Peewee 4 Async ORM**
- **D3.4 — Piccolo ORM**
- **D3.5 — Masonite ORM Feasibility / Adapter**
- **D3.6 — Persistence Integration DX, Compatibility Matrix & Closure**

Each subphase must be independently testable and may use its own PR. Every PR uses squash merge.

## D3.0 — Persistence Integration Contract & Adapter Subject Generalization

### Problem

The current adapter claim contract is class-shaped:

```python
type AdapterClaim = Callable[
    [type, ResourceFieldPolicy], DataSource | ResourceAdapterRuntime | None
]
```

That works for SQLAlchemy declarative classes and most ORM model classes, but SQLAlchemy Core's canonical resource representation is a `sqlalchemy.Table` object. Wrapping a `Table` in a fake class would preserve an accidental constraint rather than improve the abstraction.

### Decision

Generalize the adapter claim subject from `type` to a backend-neutral `object` (or an equivalent named neutral alias) throughout the compiler/registration path. Existing class-based callers remain valid because classes are objects. Core must not learn about `Table`, Tortoise, Peewee, Piccolo, Masonite, or any concrete backend type.

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

Core uses SQLAlchemy's public async engine/connection and SQL Expression Language directly. It must not manufacture ORM classes internally.

### SQLAlchemy Core capability policy

Target capabilities, subject to conformance:

- `persistence.read` — required.
- `persistence.write` — required for scalar insert/update/delete.
- `transactions.root-uow` — required if one async connection/transaction can own the full operation boundary cleanly.
- `concurrency.atomic-optimistic` — target only when a conditional update/delete can prove compare-and-write atomicity inside the owning transaction.
- `persistence.relationships` — **not assumed**. Foreign-key metadata is not equivalent to ORM relationship graph semantics.

## D3.2 — Tortoise ORM

Tortoise is chosen because its model, query, relationship, and transaction APIs differ materially from SQLAlchemy. It is async-first and provides explicit transaction contexts, making it a strong architectural adversary for Rakit.

The package is `rakit-tortoise`, importing as `rakit_tortoise`, with provider/integration id `persistence.tortoise`.

The supported dependency line begins at `tortoise-orm>=1.1.7,<2`, subject to lowest-direct CI. SQLite is the canonical contract-test backend.

Target capability policy:

- `persistence.read` — required.
- `persistence.write` — implement if ordinary scalar CRUD maps cleanly to neutral mutation semantics.
- `transactions.root-uow` — implement only with one explicit transaction context/connection owning commit/rollback.
- `persistence.relationships` — optional, only after real FK and collection behavior proves the neutral contract.
- `concurrency.atomic-optimistic` — optional, only if compare-and-write is genuinely atomic and public-API based.

Non-parity is an accepted outcome.

## D3.3 — Peewee 4 Async ORM

Peewee 4 is active and its official `playhouse.pwasyncio` layer provides asyncio-compatible SQLite, PostgreSQL, and MySQL backends. It intentionally retains Peewee's synchronous query/model construction while yielding database I/O through greenlet-backed async drivers. This makes it useful for testing whether Rakit's async contracts depend on the adapter implementation itself being natively async or only on the observable operation boundary being awaitable and non-blocking for database I/O.

The package is `rakit-peewee`, importing as `rakit_peewee`, with provider/integration id `persistence.peewee`.

Initial support targets Peewee 4.x and its official async database layer. SQLite is the contract backend.

Capability policy:

- `persistence.read` — required if field/query semantics can be mapped cleanly.
- `persistence.write` — targeted.
- `transactions.root-uow` — targeted only through public async transaction/database APIs.
- relationships and optimistic concurrency — optional and behaviorally proven only.

Rakit must not expose `greenlet` as a core requirement; it remains an adapter/upstream implementation detail.

## D3.4 — Piccolo ORM

Piccolo is an active typed ORM/query builder with native asyncio support and Python 3.12–3.14 compatibility. It provides another independent async persistence model and helps distinguish genuinely neutral Rakit semantics from one-off accommodations.

The package is `rakit-piccolo`, importing as `rakit_piccolo`, with provider/integration id `persistence.piccolo`.

Target capability policy:

- `persistence.read` — required.
- scalar `persistence.write` — targeted.
- `transactions.root-uow` — targeted only if Piccolo's public transaction API cleanly owns the root boundary.
- relationships and optimistic concurrency — advertised only after behavioral proof.

No Piccolo migration/admin/auth subsystem is adopted; Rakit integrates only persistence semantics required by its contracts.

## D3.5 — Masonite ORM Feasibility / Adapter

The former `masonite-orm` package is no longer maintained; maintained development continues under the PyPI package `masonite-framework-orm`, while Python imports remain under `masoniteorm`.

D3 includes this ecosystem direction, but implementation is gated by public API fit:

1. verify Python 3.12+ compatibility and safe install surface;
2. verify database operations can participate in Rakit's async runtime without blocking the event loop or requiring Rakit core to own a generic thread-wrapper abstraction;
3. verify root transaction ownership semantics if write/UoW capabilities are to be advertised;
4. if those gates pass, create `rakit-masonite-orm` with integration id `persistence.masonite`;
5. if they do not pass, publish the compatibility finding and leave it unadvertised/unshipped rather than weakening Rakit's contracts.

A feasibility result is considered valid D3 work; capability parity is not required.

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

A conforming adapter must prove ordinary scalar create, update, and delete; durable results after success; rollback/no partial durability on failure; and portable errors. This capability does not imply relationship graph mutation or optimistic concurrency.

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
   |-- rakit-peewee                       (Peewee 4 async adapter)
   |-- rakit-piccolo                      (independent async ORM)
   `-- rakit-masonite-orm                 (only if D3.5 feasibility passes)


rakit-web -> neutral DataSource / generated runtime / UoW contracts only
rakit     -> extras, install guidance, discovery inventory
```

## Adapter selection

No first-installed-wins behavior is introduced.

- SQLAlchemy declarative classes are owned by the SQLAlchemy ORM claimant.
- SQLAlchemy `Table` objects are owned by the SQLAlchemy Core claimant.
- Tortoise model classes are owned by Tortoise.
- Peewee models are owned by Peewee.
- Piccolo table/model classes are owned by Piccolo.
- Masonite models are owned by Masonite only if the adapter ships.
- Explicit adapter selection remains available where the existing registration API supports it.
- If two adapters claim one subject, compilation fails with the existing ambiguity semantics.

## Identity policy

Initial first-party support remains conservative: one scalar primary key representable by Rakit's existing `RecordIdentity` (`int`, `str`, or `UUID`). Composite-key support is not introduced as a side effect of adding adapters.

## Field policy

All adapters fail closed at claim/compile time when a resource declares query behavior the backend cannot safely honor.

Portable baseline:

- search: text-like fields only;
- sort: scalar concrete fields;
- filters: equality/inequality/comparison where coercion is safe, string contains, membership, and null checks where supported;
- generated mutation fields: concrete writable non-identity scalar fields;
- sensitive-field conventions continue to pass through `infer_field_security`.

Unsupported JSON/binary/custom fields may be readable but must not silently pretend to support portable search/filter/sort semantics.

## Install UX

- `pip install "rakit[sqlalchemy]"` — SQLAlchemy ORM and Core integration package.
- `pip install "rakit[tortoise]"` — Tortoise adapter.
- `pip install "rakit[peewee]"` — Peewee adapter.
- `pip install "rakit[piccolo]"` — Piccolo adapter.
- `pip install "rakit[masonite-orm]"` — only added if D3.5 ships a conforming adapter.
- `pip install "rakit[standard]"` — remains SQLAlchemy ORM-oriented; D3 does not turn `standard` into an install-everything bundle.

Direct distribution installation remains supported for first-party adapter packages.

## Delivery decomposition and merge policy

### D3.0 — Persistence Integration Contract & Adapter Subject Generalization

Generalize the claim subject to neutral `object`, add neutral diagnostic naming, strengthen shared persistence conformance seams, and prove existing SQLAlchemy ORM behavior remains unchanged.

### D3.1 — SQLAlchemy ORM Hardening + SQLAlchemy Core/Table

Implement native `Table` support in `rakit-sqlalchemy`, real Core read/write/UoW conformance, discovery metadata, and capability profile. Do not fake relationship parity.

### D3.2 — Tortoise ORM

Complete `rakit-tortoise` read support first, then add only write/UoW/higher capabilities proven by the shared contract.

### D3.3 — Peewee 4 Async ORM

Add `rakit-peewee` over Peewee's official async database layer and prove its honest capability profile.

### D3.4 — Piccolo ORM

Add `rakit-piccolo` and prove its honest capability profile.

### D3.5 — Masonite ORM Feasibility / Adapter

Evaluate the maintained `masonite-framework-orm` line against Rakit async/UoW requirements; ship an adapter only if public APIs satisfy the contract cleanly.

### D3.6 — Persistence Integration DX, Compatibility Matrix & Closure

Publish a provider/capability matrix, clean-install smoke coverage for extras, artifact inventory, lowest/latest dependency compatibility, docs, and canonical roadmap closure. Mark D4 Next only after the accepted D3 matrix is green on `main`.

Each subphase may be a separate PR. Every merge uses **squash**. If implementation reveals that an adapter would require changing a canonical capability contract rather than merely implementing it, stop that adapter at the highest honest capability set and record the contract pressure point for a future version instead of widening v1 silently.

## Non-goals

- replacing SQLAlchemy ORM as default;
- migration-tool abstraction across Alembic/Aerich/Piccolo/Masonite migration systems;
- multi-database routing;
- composite primary keys;
- Rakit persistence model DSL/base classes;
- automatic dependency uninstall/switch CLI;
- forced capability parity;
- dedicated SQLModel compatibility phases, extras, or provider-specific maintenance; SQLModel follows the SQLAlchemy ORM integration upstream;
- Django async transaction emulation through thread wrappers;
- forcing MongoDB/Beanie, Turso/libSQL, or CouchDB through relational ORM v1 semantics;
- release, tag, or publication.

## Acceptance criteria

D3 overall is complete when:

1. The adapter-claim subject no longer assumes every backend resource is a class, while existing class-based APIs remain source-compatible.
2. Existing SQLAlchemy ORM conformance remains green with no capability regression.
3. Native SQLAlchemy `Table` resources work through a first-party Core integration and every advertised Core capability has a real proof.
4. `rakit-tortoise` is an official typed distribution and every advertised Tortoise capability has a real proof.
5. `rakit-peewee` is an official typed distribution and every advertised Peewee capability has a real proof.
6. `rakit-piccolo` is an official typed distribution and every advertised Piccolo capability has a real proof.
7. Masonite ORM has either a clean first-party adapter with proven capabilities or a documented feasibility rejection explaining why Rakit intentionally does not ship it yet.
8. Core/web contain no concrete backend persistence imports.
9. Discovery/configured-integration metadata is deterministic and actionable.
10. Clean-installed extras and official artifacts are tested outside the repository checkout.
11. The public persistence compatibility matrix documents capability differences and intentional non-parity.
12. No temporary CI/helper files remain in final subphase PRs.
13. `docs/roadmap.md` exposes D3.0–D3.6 status and marks D3 overall Complete only after all accepted subphases pass canonical CI.
14. Every D3 PR is exact-head green and squash-merged.
