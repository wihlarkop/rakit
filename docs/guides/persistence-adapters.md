# Persistence adapters

Rakit keeps persistence behavior behind backend-neutral resource, generated-mutation, and unit-of-work contracts. Application models and tables remain native to their persistence library; Rakit does not introduce a universal ORM or persistence model DSL.

SQLAlchemy ORM remains the default persistence implementation. Additional adapters are optional and advertise only capabilities that pass Rakit's canonical behavioral conformance suites.

## Installation

Use one persistence extra for the backend your application owns:

| Backend | Rakit extra | Direct distribution | Integration id |
| --- | --- | --- | --- |
| SQLAlchemy ORM | `rakit[sqlalchemy]` | `rakit-sqlalchemy` | `persistence.sqlalchemy` |
| SQLAlchemy Core / `Table` | `rakit[sqlalchemy]` | `rakit-sqlalchemy` | `persistence.sqlalchemy-core` |
| Tortoise ORM | `rakit[tortoise]` | `rakit-tortoise` | `persistence.tortoise` |
| Peewee 4 async | `rakit[peewee]` | `rakit-peewee` | `persistence.peewee` |
| Piccolo ORM | `rakit[piccolo]` | `rakit-piccolo` | `persistence.piccolo` |

For example:

```bash
uv add "rakit[tortoise]"
```

The `standard` extra intentionally remains SQLAlchemy-oriented:

```bash
uv add "rakit[standard]"
```

It installs SQLAlchemy persistence, SQLAlchemy authentication, and local storage. It does **not** install every persistence adapter, select an alternative ORM, or own the application's database driver.

Multiple persistence extras may be installed together when an application or extension environment needs them. Installation never means activation and there is no "first installed wins" rule.

## Verified capability matrix

The five canonical persistence/transaction/concurrency capabilities are intentionally independent. `Yes` below means the provider advertises the capability and passes its version-1 behavioral conformance contract.

| Provider | Read | Write | Root UoW | Relationships | Atomic optimistic concurrency |
| --- | --- | --- | --- | --- | --- |
| `persistence.sqlalchemy` | Yes | Yes | Yes | Yes | Yes |
| `persistence.sqlalchemy-core` | Yes | Yes | Yes | Yes | Yes |
| `persistence.tortoise` | Yes | Yes | Yes | No | No |
| `persistence.peewee` | Yes | Yes | Yes | No | No |
| `persistence.piccolo` | Yes | Yes | Yes | No | No |

The canonical identifiers are:

- `persistence.read`
- `persistence.write`
- `transactions.root-uow`
- `persistence.relationships`
- `concurrency.atomic-optimistic`

Capability parity is not a requirement. A backend may expose native foreign keys or version fields without Rakit advertising the corresponding relationship or concurrency capability; those capabilities require the full neutral behavioral contract, not merely similar backend primitives.

## Supported dependency lines

All shipped persistence integrations participate in Rakit's Python 3.12, 3.13, and 3.14 CI matrix plus lowest-direct and latest-allowed dependency verification.

| Integration | Supported upstream range |
| --- | --- |
| SQLAlchemy ORM and Core | `sqlalchemy[asyncio]>=2.0.16,<2.1` |
| Tortoise ORM | `tortoise-orm>=1.1.7,<2` |
| Peewee | `peewee>=4.0.2,<5` |
| Piccolo | `piccolo>=1.30,<2` |

Peewee starts at 4.0.2 because 4.0.0-4.0.1 do not preserve the async SQLite affected-row semantics Rakit requires for correct generated update/delete not-found behavior. Piccolo starts at 1.30 because that is the supported 1.x floor used for Rakit's Python 3.14 matrix.

Database drivers remain application- or adapter-owned dependencies where appropriate. The `standard` extra is deliberately driver-neutral.

## Native subjects and adapter ownership

Each first-party provider claims only its native resource shape:

- SQLAlchemy ORM claims mapped declarative model classes.
- SQLAlchemy Core claims native `sqlalchemy.Table` objects and does not manufacture ORM classes.
- Tortoise claims native Tortoise model classes.
- Peewee claims native Peewee model classes bound to the configured async database layer.
- Piccolo claims native Piccolo `Table` classes owned by the configured engine.

SQLAlchemy Core relationship support stays table-native. Rakit derives unique foreign-key paths from public `Table` metadata and fails closed when no path exists. If several physical paths could satisfy one relationship, the application must provide an explicit adapter-local `SQLAlchemyCoreRelationshipBinding`; Rakit does not infer relationship identity from constraint names, `Table.info`, or a "first matching FK" rule. One-to-one requires uniqueness proof, writable ordering requires an explicit position field, and association-object semantics use an explicit association resource.

SQLAlchemy Core optimistic concurrency is likewise table-native. A mapping-aware concurrency provider supplies the expected predicate and next version. UPDATE and DELETE combine the record identity and expected state in one SQL mutation inside the root unit of work. Rakit requires sane matched-row semantics from the SQLAlchemy result and fails closed when rowcount cannot safely decide whether the optimistic claim succeeded; RETURNING is not used as the concurrency decision mechanism.

If two configured adapters claim the same resource subject, compilation fails closed with adapter ambiguity rather than choosing by registration or installation order.

## Discovery

Persistence packages publish lightweight descriptors in the `rakit.integrations` entry-point group. Inspect installed integrations without activating them:

```bash
rakit capabilities --installed
```

Installed and configured integrations are deliberately separate concepts. Installing `rakit[tortoise]`, for example, makes `persistence.tortoise` discoverable; it does not silently configure Tortoise for an `Admin`.

Use `rakit capabilities TARGET` or `rakit check TARGET` to inspect configured capability providers for an application target. Duplicate integration identifiers and invalid capability graphs fail closed.

## Transaction semantics

`transactions.root-uow` means one Rakit operation owns the durable commit/rollback boundary. Generated scalar mutations for every provider advertising this capability participate in that root unit of work instead of independently committing.

SQLAlchemy ORM and SQLAlchemy Core both prove relationship mutation and atomic optimistic concurrency. Their implementations intentionally differ: ORM uses mapper-native relationship state while Core uses explicit table/FK structure and adapter-local binding when physical metadata is ambiguous. Tortoise, Peewee, and Piccolo deliberately stop at the capabilities they currently prove.

## Deferred persistence directions

### Masonite ORM

Masonite ORM remains a **Research** item. Rakit does not currently ship `persistence.masonite`, a `rakit-masonite-orm` distribution, or a Masonite install extra. A future feasibility pass must first prove supported-Python runtime compatibility, non-blocking participation in Rakit's async operation model, and honest root-UoW semantics through maintained public APIs.

This research item does not block the completed D3 shipped-adapter ecosystem.

### Django ORM

Django ORM remains deliberately deferred because its async query support does not currently provide the async transaction semantics required by Rakit's root-UoW contract without synchronous wrapping.

### Non-relational and remote persistence

MongoDB / Beanie, Turso / libSQL, and CouchDB remain future D6 or contract-research directions. Rakit will not force their identity, query, relationship, or transaction semantics through the relational ORM v1 contract merely for provider-count parity.