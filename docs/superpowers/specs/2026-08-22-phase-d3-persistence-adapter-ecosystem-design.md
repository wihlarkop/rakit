# Phase D3 Persistence Adapter Ecosystem Design

**Status:** Approved for execution by maintainer delegation

## Context

D1 established versioned capability contracts and behavior-oriented conformance seams. D2 proved that schema adapters can be split into first-party packages and that capability advertisement must follow proven semantics rather than parity targets. D3 applies the same discipline to persistence.

The existing first-party persistence implementation is SQLAlchemy. It is mature, deeply integrated, and currently advertises five canonical capabilities:

- `persistence.read`
- `persistence.write`
- `persistence.relationships`
- `transactions.root-uow`
- `concurrency.atomic-optimistic`

The purpose of D3 is not to replace SQLAlchemy. It is to prove that Rakit's persistence contracts can support a materially different ORM without leaking SQLAlchemy assumptions into core or web layers.

## Decision summary

1. **SQLAlchemy remains the default persistence adapter.**
2. **Tortoise ORM is the second first-party persistence adapter.** It is intentionally chosen because its model, query, relationship, and transaction APIs differ materially from SQLAlchemy; SQLModel is rejected for D3 because it would not pressure-test the abstraction strongly enough.
3. The new package is **`rakit-tortoise`**, importing as `rakit_tortoise`.
4. D3 does **not** force Tortoise to advertise all five SQLAlchemy capabilities. Capability advertisement follows verified behavior.
5. Tortoise must support at least `persistence.read`; D3 also targets ordinary scalar CRUD and root transaction ownership where cleanly expressible. Relationships and optimistic concurrency are advertised only if their v1 semantics are proven without ORM-specific hacks.
6. Rakit core/web must not import Tortoise or SQLAlchemy concrete APIs for persistence behavior.
7. Native ORM models remain native. Rakit does not introduce a persistence model DSL.
8. Adapter selection remains explicit through the existing adapter claim mechanism; no package-manager mutation CLI is added in D3.
9. The root `rakit` package gets a `tortoise` optional extra. `standard` continues to use SQLAlchemy.
10. D3 closes only after clean-installed artifact verification, lowest-direct/latest dependency CI, Python 3.12/3.13/3.14 CI, strict docs, and exact-head green CI. Merge method is squash.

## Why Tortoise ORM

Tortoise is async-first and built around its own model/query abstraction rather than SQLAlchemy's expression/session model. It has native relationship handling and explicit transaction contexts. This makes it a useful architectural adversary for Rakit: if Rakit's persistence surfaces can support SQLAlchemy and Tortoise without core branching on ORM identity, the adapter contract is substantially healthier.

The initial supported dependency line is `tortoise-orm>=1.1.7,<2`, subject to lowest-direct verification. SQLite is the canonical contract-test backend because it keeps adapter conformance deterministic and does not introduce external service dependencies.

## Capability semantics

### `persistence.read@v1`

A conforming adapter must provide Rakit-neutral:

- field and identity metadata;
- deterministic list ordering;
- detail lookup by `RecordIdentity`;
- page and limit/offset pagination when advertised by `DataSourceCapabilities`;
- supported filtering, sorting, and search for declared field policy;
- portable not-found and validation/configuration failures rather than leaking raw ORM exceptions.

D3 will strengthen the persistence harness so these semantics are tested using real adapter operations rather than capability-name presence alone.

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

This is deliberately separate. Tortoise may advertise it only after proving neutral relationship metadata and mutations across representative foreign-key and collection relationships. Merely being an ORM with relationships is insufficient.

### `transactions.root-uow@v1`

A conforming adapter must prove that one root operation context owns commit/rollback and nested mutation work does not create independent durable commits. For Tortoise this must be built on one explicit transaction context/connection and not on ambient auto-commit behavior.

### `concurrency.atomic-optimistic@v1`

This remains optional for Tortoise in D3. It may be advertised only if the compare-and-write operation is atomic inside the root transaction and stale tokens fail without committing the write. If the implementation would require brittle private APIs or application-specific version fields, D3 leaves the capability unadvertised.

## Package architecture

```text
rakit-core
   ^
   |-- rakit-sqlalchemy      (default, existing)
   `-- rakit-tortoise        (alternative, new)

rakit-web -> Rakit neutral DataSource / generated runtime contracts only
rakit     -> optional extras and install/discovery UX
```

`rakit-tortoise` owns:

- model introspection;
- field-policy validation;
- read data source;
- optional scalar write service;
- optional root UoW implementation;
- capability provider;
- integration descriptor;
- plugin/claim logic;
- conformance harness/tests.

## Native model policy

Tortoise resources are native subclasses of `tortoise.models.Model`. Rakit reads Tortoise metadata but does not require a Rakit model superclass or decorator.

Identity support in D3 is intentionally conservative: one scalar primary key whose runtime values can be represented by Rakit's existing `RecordIdentity` contract. Composite-key emulation is not introduced.

## Field policy

The adapter fails closed at claim time when a resource declares unsupported query behavior.

Initial portable field-policy support:

- search: text-like fields only;
- sort: scalar concrete fields;
- filters: equality/inequality/comparison where the underlying field semantics are safely coercible, string contains, membership, and null checks where supported;
- generated mutation fields: concrete writable non-PK scalar fields.

Unsupported JSON/binary/custom fields are readable but are not silently accepted as filter/search fields.

## Selection and discovery

The integration id is `persistence.tortoise`; provider id matches it exactly. The package registers through `rakit.integrations` and the normal plugin configured-integration inventory.

No first-installed-wins behavior is introduced. A resource is claimed by the adapter whose native model type matches. SQLAlchemy and Tortoise may be installed simultaneously because model ownership is unambiguous.

## Install UX

- `pip install rakit-tortoise` installs the adapter directly.
- `pip install "rakit[tortoise]"` is the umbrella convenience path.
- `pip install "rakit[standard]"` remains SQLAlchemy-based.
- `rakit capabilities` / aggregate checks must discover Tortoise when installed.

## D3 decomposition

### D3.1 — Persistence contract audit and conformance hardening

Strengthen shared persistence test semantics without changing SQLAlchemy's externally observable behavior. Add reusable neutral harness helpers where useful.

### D3.2 — Tortoise read adapter

Add `rakit-tortoise` with native model introspection, deterministic reads, pagination, field policy, plugin claim, discovery, and `persistence.read` capability.

### D3.3 — Scalar writes and transaction ownership

Implement ordinary scalar CRUD and a root operation UoW using Tortoise transaction primitives. Advertise `persistence.write` and `transactions.root-uow` only after conformance passes.

### D3.4 — Optional higher capabilities evaluation

Evaluate `persistence.relationships` and `concurrency.atomic-optimistic` against the actual v1 contracts. Implement and advertise only capabilities that remain clean, deterministic, and backend-neutral. Non-parity is acceptable and must be documented.

### D3.5 — Packaging, docs, roadmap, and closure

Wire workspace/facade extras, artifact inventory, capability discovery, guide/docs, lowest/latest dependency checks, and mark D3 Complete / D4 Next only after exact-head CI is green.

## Non-goals

- replacing SQLAlchemy as default;
- migration tooling integration (Aerich or Alembic abstraction);
- multi-database routing;
- composite primary keys;
- a Rakit persistence DSL;
- automatic dependency uninstall/switch CLI;
- forced capability parity;
- release, tag, or publication.

## Acceptance criteria

D3 is complete when:

1. `rakit-tortoise` is an official typed distribution in the workspace and artifact gate.
2. Native Tortoise models are claimable without SQLAlchemy-specific code in core/web.
3. Every advertised Tortoise canonical capability has a real behavior conformance proof.
4. SQLAlchemy retains its existing advertised capability profile and regression suite.
5. Tortoise discovery/configured-integration metadata is deterministic and actionable.
6. `rakit[tortoise]` clean-installs and smoke-imports outside the repository checkout.
7. The documented capability matrix explicitly records any intentional non-parity.
8. No temporary CI/helper files remain in the final PR.
9. `docs/roadmap.md` marks D3 Complete and D4 Next only after verification.
10. Canonical exact-head CI is green and the PR is squash-merged.
