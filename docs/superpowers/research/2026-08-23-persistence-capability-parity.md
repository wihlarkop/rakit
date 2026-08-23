# Persistence Capability Parity Research

**Status:** Active research

**Date:** 2026-08-23

**Branch:** `research/persistence-capability-parity`

**Purpose:** Record evidence-backed feasibility decisions for first-party persistence providers before any capability promotion or follow-on security/authentication work. This document is a research input, not an implementation plan and not proof that a capability is already shipped.

## Why this research exists

Rakit advertises persistence capabilities conservatively and only after behavioral proof. The shipped providers intentionally do not have forced parity.

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
- Use public, maintained backend APIs for new parity behavior.
- Preserve one Rakit root unit of work for mutations that claim `transactions.root-uow`.
- Fail closed on ambiguous or unsupported native shapes.
- Capability parity is allowed only when neutral Rakit semantics are actually satisfied; backend feature parity is not required.
- Composite resource identity remains outside this research unless a separate core contract change is explicitly approved.
- A feasibility PASS does not authorize capability promotion. Source implementation, source-first smoke, permanent conformance, dependency matrices, and exact-head CI remain mandatory later.

---

# SQLAlchemy Core / Table

**Research status:** Complete / locked

Provider: `persistence.sqlalchemy-core`

| Capability | Shipped now | Research verdict |
| --- | --- | --- |
| `persistence.read` | Yes | Existing |
| `persistence.write` | Yes | Existing |
| `transactions.root-uow` | Yes | Existing |
| `persistence.relationships` | No | **PASS with explicit binding for ambiguity** |
| `concurrency.atomic-optimistic` | No | **PASS** |

**Feasibility conclusion:** SQLAlchemy Core can plausibly reach a truthful **5/5** Rakit persistence capability profile without constructing ORM mapped classes or redesigning Rakit core.

## Atomic optimistic concurrency

The current Core generated mutation executor already executes through the `AsyncConnection` owned by `SQLAlchemyCoreUnitOfWork`; it only lacks the concurrency predicate/runtime wiring and currently advertises `atomic_concurrency=False`.

The required native shape is one conditional mutation inside the existing root UoW:

```sql
UPDATE article
SET title = :title,
    version = :next_version
WHERE id = :id
  AND version = :expected_version
```

- affected row count `1` → success;
- affected row count `0` → stale conflict;
- conditional delete follows the same rule;
- no read-check-write durability window;
- uncertain row-count semantics must fail closed;
- Core records are mappings, so Core needs mapping-aware concurrency field access rather than ORM-style `getattr` assumptions.

Decision records:

- **CORE-R1:** SQLAlchemy Core optimistic concurrency is feasible. **PASS**.
- **CORE-R2:** Concurrency must use one conditional SQL mutation; no read-check-write emulation.
- **CORE-R3:** Reliable affected/matched-row semantics are mandatory; uncertain dialect behavior fails closed.
- **CORE-R4:** Core requires mapping-aware concurrency version access rather than pretending row mappings are ORM instances.

## Relationships

`RelationshipDefinition` remains the semantic source of truth. SQLAlchemy Core only validates/binds that intent to native `Table`, column, foreign-key, unique-constraint, and association-table metadata.

Feasible neutral shapes:

- many-to-one;
- one-to-many;
- one-to-one;
- many-to-many;
- explicit association object;
- ordering/reordering through an explicit position field;
- explicit destructive policy;
- all relationship writes inside the existing Core root UoW.

Schema metadata is not always sufficient to infer intent. Multiple foreign keys to the same target or multiple bridge tables are genuine ambiguities. Therefore:

```text
exactly one compatible physical path -> inference may be allowed
zero compatible paths                -> configuration error
multiple compatible paths            -> explicit adapter binding required
```

A future adapter-only binding may conceptually identify the Rakit relationship id, source/target tables, and physical local/remote columns. This is not a final API and must not become a Rakit-wide persistence DSL.

A truthful neutral capability does not require SQLAlchemy ORM feature parity. Arbitrary mapper `primaryjoin`, custom operators, mapper lazy-loading behavior, mapper `viewonly`, and mapper cascade/delete-orphan authority may remain unsupported. Composite Rakit identities also remain outside this parity effort.

Decision records:

- **CORE-R5:** SQLAlchemy Core relationships are feasible without ORM mapping. **PASS**.
- **CORE-R6:** `RelationshipDefinition` remains the semantic source of truth.
- **CORE-R7:** A unique compatible FK path may be inferred for ergonomics.
- **CORE-R8:** Ambiguous paths require explicit adapter binding; Core must never guess.
- **CORE-R9:** SQLAlchemy ORM feature parity is not required for the neutral Rakit capability.
- **CORE-R10:** Relationship mutation must remain inside the existing Core root UoW.
- **CORE-R11:** Unsupported or ambiguous relationship shapes fail closed rather than silently degrade.
- **CORE-R12:** Composite identity remains outside this parity effort unless separately approved.

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

# Tortoise ORM

**Research status:** Complete / locked

Provider: `persistence.tortoise`

Rakit currently supports `tortoise-orm>=1.1.7,<2`. Upstream 1.1.8 was also inspected during this research. The current Rakit adapter advertises read, write, and root-UoW only.

| Capability | Shipped now | Research verdict |
| --- | --- | --- |
| `persistence.read` | Yes | Existing |
| `persistence.write` | Yes | Existing |
| `transactions.root-uow` | Yes | Existing |
| `persistence.relationships` | No | **PASS with explicit association-resource semantics** |
| `concurrency.atomic-optimistic` | No | **PASS with backend/conformance gate** |

**Feasibility conclusion:** Tortoise ORM can plausibly reach a truthful **5/5** Rakit persistence capability profile using its native model/query/relation APIs. No blocking architectural mismatch was found. The implementation must, however, avoid treating Tortoise's table-oriented M2M `through` option as a full association-object model and must prove affected-row behavior across the database/runtime matrix that Rakit intends to claim.

## Existing Rakit foundation

Relevant seams:

- `packages/rakit-tortoise/src/rakit_tortoise/capabilities.py`
- `packages/rakit-tortoise/src/rakit_tortoise/introspection.py`
- `packages/rakit-tortoise/src/rakit_tortoise/generated.py`
- `packages/rakit-tortoise/src/rakit_tortoise/uow.py`

The existing generated executor already routes CRUD through the `TransactionalDBClient` owned by `TortoiseUnitOfWork`:

- reads use `QuerySet.using_db(connection)`;
- create uses `Model.create(using_db=connection, ...)`;
- update uses `QuerySet.using_db(connection).update(...)`;
- delete uses `QuerySet.using_db(connection).delete()`.

The root UoW is already based on Tortoise `in_transaction()` and owns commit/rollback. Higher capabilities therefore do not require a second transaction architecture.

## Tortoise atomic optimistic concurrency

### Verdict

**PASS with an implementation-time backend/conformance gate.**

### Native strategy

Tortoise `QuerySet.update()` composes queryset filters into the UPDATE and returns an integer affected-row count. Tortoise also exposes `F` expressions specifically for database-side field updates. The version-column strategy can therefore remain one atomic statement:

```python
from tortoise.expressions import F

updated = await (
    Model.filter(pk=identity, version=expected_version)
    .using_db(root_connection)
    .update(
        name=proposed_name,
        version=F("version") + 1,
    )
)
```

Required interpretation:

```text
updated == 1 -> success
updated == 0 -> stale/conflict path
other count  -> fail closed
```

Conditional delete can use the same identity + concurrency predicate and the returned delete count.

The important property is that identity predicate, expected version predicate, user changes, and version advancement are executed by the database as one mutation. A preceding read may be used to validate the signed Rakit token and a later read may classify/reload state, but neither read may authorize a separate unconditional write.

### Version-provider compatibility

Unlike SQLAlchemy Core row mappings, Tortoise records are attribute-bearing model instances, so the existing neutral `AttributeVersionProvider` shape is naturally compatible.

An integer version field is the strongest first implementation target:

- `version=expected` participates in the WHERE predicate;
- `version=F("version") + 1` guarantees a physical change on a successful match;
- the current generated executor already reloads after UPDATE, which is appropriate because Tortoise documents that model values are stale after `F`-expression writes until refreshed/reloaded.

Datetime next-values can also be supplied as literal next values in the same conditional UPDATE, subject to the same canonical token/time-resolution rules already owned by Rakit core.

Snapshot concurrency is more subtle. `SnapshotVersionProvider.next_values_for()` is empty, so a user mutation that writes values identical to current values may be a no-op. Some DB drivers report changed rows rather than merely matched rows. Tortoise's MySQL client, for example, directly returns driver `cursor.rowcount`; SQLite derives its count from connection changes; asyncpg parses the server's command count. Consequently, implementation must not assume that every backend gives identical semantics for a snapshot/no-op UPDATE.

Initial parity implementation should therefore either:

1. prove snapshot/no-op behavior for every database backend included in the advertised support matrix; or
2. fail closed / restrict atomic concurrency to a version strategy whose successful match necessarily changes a concurrency-managed field until broader behavior is proven.

This does not block the capability feasibility result; it is an explicit implementation acceptance gate.

### Conflict classification

A zero-row conditional mutation can mean stale predicate or that the row disappeared. Rakit should preserve its neutral error behavior deliberately:

- initial scoped read absent → not found;
- signed token mismatch against the loaded record → conflict;
- conditional mutation returns zero after the initial record/token check → concurrency race/conflict unless a safe same-UoW classification step proves the row no longer exists and the neutral contract requires not-found classification.

The mutation itself must remain atomic regardless of how the final error is classified.

### Atomic concurrency decision records

- **TORTOISE-R1:** Tortoise can express optimistic compare-and-write as one native conditional UPDATE. **PASS**.
- **TORTOISE-R2:** Use `QuerySet.filter(...).using_db(root_connection).update(...)`; never read-check then issue an unconditional update.
- **TORTOISE-R3:** Prefer a version-column strategy for the first implementation; integer version plus `F("version") + 1` is the clearest cross-backend shape.
- **TORTOISE-R4:** Affected-row behavior is an implementation acceptance gate across the database matrix, especially for snapshot/no-op writes.
- **TORTOISE-R5:** Zero-row mutation maps to the neutral race/conflict path after initial existence/token validation; classification must not weaken atomicity.
- **TORTOISE-R6:** All concurrency reads and writes must explicitly use the existing root UoW connection.

## Tortoise relationships

### Verdict

**PASS with explicit association-resource semantics.**

Tortoise is relationship-native. Its public model description API exposes separate collections for:

- forward foreign keys;
- backward foreign keys;
- forward one-to-one;
- backward one-to-one;
- many-to-many.

This aligns well with Rakit's portable cardinalities. New parity introspection should prefer public `Model.describe()` metadata rather than deepening reliance on private `_meta` structures merely for convenience. Current scalar adapter code already uses `_meta`; this research does not require rewriting that existing code, but new relationship support should use the public seam wherever sufficient.

### Many-to-one

Native `ForeignKeyField` is a direct fit. Tortoise exposes both the relationship and its backing raw id field. Rakit can validate target/cardinality and perform link/unlink through an explicit conditional update inside the root connection.

### One-to-many

Tortoise exposes backward FK relations. Reverse relation querysets support ordinary filtering/ordering, and related child creation accepts `using_db`, so child creation can remain inside the root transaction.

### One-to-one

Tortoise has a dedicated `OneToOneField`; its implementation is FK-derived with uniqueness semantics. Both forward and backward O2O are represented separately in public model description metadata.

### Many-to-many

Tortoise's `ManyToManyRelation` provides native `add`, `remove`, and `clear`, and those mutation methods accept an explicit `using_db` connection. Upstream source shows that the supplied DB client is used for bridge-table SELECT/INSERT/DELETE operations. That lets Rakit preserve root-UoW ownership.

The relation APIs accept saved model instances. Rakit should resolve candidate identities through a scoped queryset on the same root connection before calling relation mutation methods; candidate resolution must remain subject to Rakit permissions/scope rather than accepting arbitrary model objects supplied by user code or transport input.

### Association object

This is the main Tortoise-specific design boundary.

Tortoise native `ManyToManyField(..., through=...)` currently treats `through` as a table name. In the inspected 1.1.8 relational source there is still an explicit upstream TODO to support `through` as a Model. Therefore Rakit must **not** pretend a native Tortoise M2M through table is a rich association-object model.

Rakit association-object semantics should instead use an explicit application-owned Tortoise model, for example conceptually:

```python
class Membership(Model):
    id = fields.IntField(primary_key=True)
    user = fields.ForeignKeyField("models.User")
    team = fields.ForeignKeyField("models.Team")
    role = fields.CharField(max_length=64)
    position = fields.IntField()
```

`RelationshipDefinition` already identifies the association resource, target resource, and exposed association scalars. The Tortoise adapter can validate that explicit association resource through normal model metadata and execute it using ordinary model/query CRUD. This avoids depending on unsupported richer semantics in native M2M `through`.

### Ordered relationships

Ordering remains a Rakit-declared behavior. It should require an explicit scalar position field on the child or association resource. Reads use an ordered queryset; reorder writes explicitly update that position field inside the root UoW. Tortoise default model ordering is not sufficient proof of writable Rakit ordering by itself.

### Destructive behavior

Tortoise relation fields expose `on_delete`, but this is database/ORM relationship behavior, not Rakit authorization. As with SQLAlchemy, `CASCADE` or another ORM delete rule must never silently grant destructive UI/API behavior. Rakit's explicit destructive policy remains authoritative.

### Ambiguity and explicit declaration

Unlike SQLAlchemy Core, Tortoise relationship fields already have application-level names, so multiple FKs to the same model are normally distinguishable by field name. Rakit should bind a `RelationshipDefinition` to that named native relationship and validate target/cardinality. It must still fail closed when:

- the declared relationship field does not exist;
- its native target does not match the declared target resource;
- cardinality does not match;
- a declared association resource is structurally incompatible;
- the ordered relationship lacks the declared position field;
- a relation shape requires unsupported custom/convention-only behavior.

### Relationship reads and root UoW

Relation reads must not accidentally escape to Tortoise's default connection. Use one of the public explicit-connection paths:

- relation queryset followed by `.using_db(root_connection)`;
- model/query methods that accept `using_db`;
- `fetch_related(..., using_db=root_connection)` where appropriate.

Likewise all writes must pass the root connection to M2M/reverse relation operations or use querysets explicitly bound with `using_db`.

### Relationship concurrency

Child/association records that participate in optimistic concurrency can use the same conditional-update mechanism as ordinary Tortoise resources. Parent graph changes that require a parent concurrency claim should use a versioned parent update in the same root transaction before/with relationship mutations, following the neutral Rakit graph-mutation contract rather than relying on Tortoise relation container state.

### Relationship decision records

- **TORTOISE-R7:** Native Tortoise FK/reverse-FK/O2O/M2M metadata is sufficient for Rakit relationship validation. **PASS**.
- **TORTOISE-R8:** Prefer public `Model.describe()` as the new relationship introspection seam; do not deepen private `_meta` coupling merely to chase parity.
- **TORTOISE-R9:** Relationship declarations bind by explicit Tortoise field/relation name and validate target/cardinality; no heuristic guessing is required for multiple named FKs.
- **TORTOISE-R10:** Native M2M `add/remove/clear` is usable only with the Rakit root connection explicitly supplied.
- **TORTOISE-R11:** Rakit association objects use an explicit Tortoise model with its own identity, two relationship edges, and scalar fields; native M2M `through` table metadata is not treated as an association model.
- **TORTOISE-R12:** Ordered relationships require an explicit position field; default ORM ordering alone does not grant writable ordering semantics.
- **TORTOISE-R13:** Tortoise `on_delete` behavior never grants Rakit destructive permission.
- **TORTOISE-R14:** Candidate/relationship resolution must remain scoped and must use the root UoW connection.
- **TORTOISE-R15:** Unsupported or structurally inconsistent relation declarations fail closed.

## Deliberately unsupported / fail-closed shapes

A neutral Tortoise 5/5 implementation does not need to promise every ORM convenience. The adapter may reject:

- convention-only relationships not represented by declared Tortoise relation fields or an explicit association resource;
- composite Rakit identities;
- native M2M through tables being used as if they were rich association models;
- relationship mutation that cannot be bound to the root UoW connection;
- ambiguous/incompatible declarations;
- destructive behavior inferred only from ORM/database cascade configuration;
- concurrency modes whose affected-row behavior has not been proven for the advertised database matrix.

## Tortoise implementation acceptance matrix — research output

Before capability promotion, implementation must prove at least:

| Area | Required proof |
| --- | --- |
| FK / many-to-one | read, link, nullable unlink, target validation |
| reverse FK / one-to-many | read, scoped child create/update/unlink where allowed |
| one-to-one | forward/backward read and writable supported direction |
| many-to-many | read, add, duplicate-safe add behavior, remove, clear/policy behavior, same root UoW |
| association object | explicit association model, scalar edits, target resolution, delete/unlink policy |
| ordering | deterministic read + reorder through explicit position field |
| transaction | all graph writes roll back together and commit together |
| parent/child concurrency | stale parent/child graph changes reject without partial durability |
| atomic update | identity + version/snapshot predicates and write in one statement |
| atomic delete | identity + concurrency predicate in one delete |
| affected rows | supported DB matrix proves reliable semantics or unsupported mode fails closed |
| introspection | public metadata validates relation kind/target without hidden heuristic coupling |

## Tortoise final research verdict

```text
Atomic optimistic concurrency   PASS**
Relationships                  PASS*
Potential capability profile   5/5
Core redesign required         NO
New transaction model required NO
Native relationship APIs       YES
Explicit association model     YES for association-object semantics
Public introspection seam      Model.describe()
Fail-closed semantics          REQUIRED
Capability promotion now       NO
```

`*` Relationship PASS is for the neutral Rakit contract. A native Tortoise M2M `through` table is not considered a rich association object; explicit application-owned association models are required for that Rakit relationship kind.

`**` Atomic concurrency PASS is subject to an implementation-time affected-row/backend matrix. Version-column compare-and-write is the recommended first target. Snapshot/no-op behavior must be proven or rejected fail-closed for backends whose row-count semantics are not suitable.

---

# Peewee 4 Async ORM

**Research status:** Complete / locked

Provider: `persistence.peewee`

Rakit currently ships `peewee>=4.0.2,<5` and advertises read, write, and root-UoW. This research inspected the current Rakit adapter, the async implementation at Peewee 4.0.2, the relevant fixes in 4.0.7, and the first upstream release that explicitly marks the asyncio extension stable, Peewee 4.0.8.

| Capability | Shipped now | Research verdict |
| --- | --- | --- |
| `persistence.read` | Yes | Existing |
| `persistence.write` | Yes | Existing |
| `transactions.root-uow` | Yes | Existing |
| `persistence.relationships` | No | **PASS** |
| `concurrency.atomic-optimistic` | No | **PASS with required parity floor bump** |

**Feasibility conclusion:** Peewee async can plausibly reach a truthful **5/5** Rakit persistence profile, but **not while the parity implementation claims the current lower bound `peewee>=4.0.2`**. The recommended implementation floor for the 5/5 workstream is `peewee>=4.0.8,<5` because 4.0.7 fixes asyncpg UPDATE/DELETE row counts and 4.0.8 is the first release whose upstream changelog declares the asyncio APIs stable.

This is a research recommendation only. The package dependency remains unchanged until a later implementation plan explicitly approves and verifies the floor change.

## Existing Rakit foundation

Relevant seams:

- `packages/rakit-peewee/src/rakit_peewee/capabilities.py`
- `packages/rakit-peewee/src/rakit_peewee/introspection.py`
- `packages/rakit-peewee/src/rakit_peewee/datasource.py`
- `packages/rakit-peewee/src/rakit_peewee/generated.py`
- `packages/rakit-peewee/src/rakit_peewee/uow.py`

The current generated executor already performs mutation through the configured `playhouse.pwasyncio.AsyncDatabaseMixin` database with `database.aexecute(...)` and checks that UPDATE/DELETE return exactly one affected row. The provider merely rejects concurrency configuration today and advertises `atomic_concurrency=False`.

`PeeweeUnitOfWork` already enters the async database context and a single `database.atomic()` boundary. The async database keeps connection state per asyncio task. Therefore the additional relationship and concurrency behavior can reuse the existing root transaction rather than adding a second UoW design.

## Dependency-floor finding

### Current floor is sufficient for shipped 3/5 behavior, not sufficient for global atomic parity

Rakit deliberately moved its original Peewee floor to 4.0.2 because Peewee 4.0.0–4.0.1 did not preserve the async SQLite affected-row behavior required by generated UPDATE/DELETE not-found semantics.

However, inspecting Peewee 4.0.2 exposes a separate PostgreSQL issue relevant to `concurrency.atomic-optimistic`:

- async SQLite obtains `cursor.rowcount`;
- async MySQL obtains `cursor.rowcount`;
- async PostgreSQL/asyncpg in 4.0.2 executes through `conn.fetch(...)` and constructs a cursor adapter without an explicit DML rowcount;
- for an ordinary UPDATE/DELETE without returned rows, the cursor adapter therefore cannot report a truthful affected-row count for Rakit's stale-write decision.

Peewee 4.0.7 explicitly fixes `playhouse.pwasyncio` asyncpg UPDATE/DELETE row counts by parsing the asyncpg command status. Peewee 4.0.8 then adds the polished query-level `BaseQuery.aexecute()` API, async model helpers, `afetch()`, and explicitly states that the asyncio extension is no longer preliminary.

### Research recommendation

For the parity implementation:

```text
current shipped floor:   peewee>=4.0.2,<5
recommended parity floor peewee>=4.0.8,<5
```

Why not stop at 4.0.7?

- 4.0.7 contains the necessary rowcount fix;
- 4.0.8 is the first release where upstream marks the documented asyncio API stable;
- choosing 4.0.8 gives Rakit a maintained, explicit async contract instead of building new 5/5 semantics on the last "preliminary" async release.

Rakit should not advertise `concurrency.atomic-optimistic` conditionally based on the database backend merely to preserve the 4.0.2 floor unless a separate dynamic-capability design is explicitly approved. A single provider capability should mean the behavior is honestly supported across the database/runtime matrix Rakit claims for that provider.

## Peewee atomic optimistic concurrency

### Verdict

**PASS, conditional on raising the parity dependency floor and proving the database matrix.**

### Native strategy

Peewee supports database-side expressions in UPDATE statements and UPDATE execution returns the affected-row count. The Rakit executor can therefore compose identity and version predicates into the same statement that performs the user change and advances the version:

```python
updated = await database.aexecute(
    Model.update(
        name=proposed_name,
        version=Model.version + 1,
    ).where(
        (Model.id == identity)
        & (Model.version == expected_version)
    )
)
```

Required interpretation:

```text
updated == 1 -> success
updated == 0 -> stale/race conflict
other count  -> fail closed
```

Conditional delete follows the same shape:

```python
deleted = await database.aexecute(
    Model.delete().where(
        (Model.id == identity)
        & (Model.version == expected_version)
    )
)
```

The mutation is atomic because the expected-version predicate and data change are one database statement. A prior read may validate the Rakit token/existence and a later read may reload state; neither may be used to authorize a separate unconditional UPDATE.

### Version-provider compatibility

Peewee model records expose fields as attributes, so the existing neutral attribute-based version-provider shape is naturally compatible.

The strongest first target is an integer version column:

```text
WHERE version = expected
SET version = version + 1
```

A successful match necessarily changes the concurrency field, which avoids ambiguity on databases/drivers that distinguish changed rows from matched rows.

Snapshot-style concurrency needs the same caution identified during Tortoise research. When `next_values_for()` is empty and the requested data is already equal to the stored data, the UPDATE can become a no-op. Peewee's async drivers ultimately expose backend-specific row-count semantics, so snapshot/no-op behavior must be proven for SQLite, PostgreSQL/asyncpg, and MySQL/aiomysql before that mode is advertised. Until then it should fail closed or remain unsupported for this provider.

### Conflict classification

Recommended neutral behavior:

- initial scoped record absent → `RESOURCE_NOT_FOUND`;
- signed token does not match the loaded record → `RESOURCE_CONFLICT`;
- conditional mutation returns zero after existence/token validation → race/stale `RESOURCE_CONFLICT`;
- no read-check-unconditional-write fallback.

### Atomic concurrency decision records

- **PEEWEE-R1:** Peewee can express optimistic compare-and-write as one conditional UPDATE/DELETE executed through the async database. **PASS**.
- **PEEWEE-R2:** The current `>=4.0.2` lower bound is insufficient for global atomic capability because pre-4.0.7 asyncpg UPDATE/DELETE rowcounts are not reliable enough for Rakit's stale-write decision.
- **PEEWEE-R3:** The parity implementation should raise the Peewee floor to `>=4.0.8,<5`; 4.0.7 contains the rowcount fix and 4.0.8 is the first upstream-stable asyncio API line.
- **PEEWEE-R4:** Prefer integer version-column concurrency first, with `version = version + 1` in the same statement; snapshot/no-op mode requires explicit backend proof or fails closed.
- **PEEWEE-R5:** All optimistic reads/writes must remain in the same `PeeweeUnitOfWork` task/database/`atomic()` boundary.
- **PEEWEE-R6:** A zero-row conditional mutation maps to the neutral race/conflict path after initial existence/token validation.

## Peewee relationships

### Verdict

**PASS.**

Peewee has enough documented relationship metadata and query primitives to satisfy the neutral Rakit contract without inventing another ORM layer. Its native relationship model differs from Tortoise but maps cleanly when Rakit remains explicit about semantics.

### Introspection seam

Unlike the Tortoise case, Peewee documents `Model._meta` as the model metadata surface and exposes metadata helpers such as model graph/reference information. The existing Rakit adapter already uses `model._meta` for scalar identity and fields.

For relationship parity, the adapter can extend this documented metadata seam to inspect:

- named `ForeignKeyField` instances;
- target model (`rel_model`);
- nullability;
- uniqueness;
- backref names;
- model references/backreferences;
- many-to-many through models where the application uses `ManyToManyField`.

The presence of an underscore in `_meta` should not automatically be treated as an unsupported private hack here: Peewee's public documentation intentionally exposes it as the model metadata object. Rakit should still avoid depending on undocumented implementation internals beneath that metadata surface when a documented field/helper is available.

### Many-to-one

A named `ForeignKeyField` maps directly to Rakit `MANY_TO_ONE`.

Rakit can validate:

- native field exists;
- `rel_model` matches the declared target resource;
- nullable semantics match the declaration.

Link/unlink should use explicit asynchronous UPDATE through the bound database instead of relying on an implicit lazy save. A nullable unlink sets the FK column to `NULL` only when Rakit edit policy permits it.

### One-to-many

Peewee creates a back-reference for foreign keys and allows an explicit `backref=` name. That maps to `ONE_TO_MANY` when bound to the corresponding FK edge.

Reads should use explicit joined/prefetched/query execution through the async bridge rather than triggering accidental synchronous lazy access. Child create/update/unlink can use ordinary Peewee INSERT/UPDATE queries with the parent FK bound explicitly.

### One-to-one

Peewee does not need a separate OneToOne field class. Rakit can treat an FK edge as `ONE_TO_ONE` only when the physical/model metadata proves singularity, for example a `ForeignKeyField(unique=True)` (or equivalent unique constraint that the adapter can verify without guessing).

A plain FK must never be promoted to one-to-one based only on a Rakit declaration.

### Many-to-many

Peewee supports `ManyToManyField` and exposes a through model. For simple native M2M declarations, Rakit may validate the relation using that public through-model surface.

For mutation, the preferred Rakit implementation is **explicit asynchronous DML against the through model** rather than relying first on synchronous-looking descriptor methods such as `.add()`/`.remove()`:

```text
link   -> INSERT through-model row
unlink -> DELETE through-model row
clear  -> policy-authorized DELETE for this parent
```

This keeps root-UoW participation and affected-row behavior visible through the same `database.aexecute(...)` path already used by the adapter.

If a native relation helper is used later, it must be executed through the supported async bridge and proven to stay on the root UoW connection/task. No convenience API is allowed to create an independent commit boundary.

### Association object

Peewee's recommended modeling style for more complex many-to-many relations is an explicit intermediary model. This fits Rakit association-object semantics very well.

Conceptually:

```python
class Membership(BaseModel):
    id = AutoField()
    user = ForeignKeyField(User, backref="memberships")
    team = ForeignKeyField(Team, backref="memberships")
    role = TextField()
    position = IntegerField()
```

Rakit can then treat `Membership` as the association resource, expose selected scalar association fields, and use normal async query mutation for link/update/unlink/reorder operations.

The current Rakit identity contract still requires one scalar int/str/UUID primary key. A junction model using only a composite primary key must therefore fail closed for association-resource behavior until composite resource identity is separately designed and approved.

### Ambiguous multiple FKs

Peewee explicitly documents that when multiple FKs point to the same model, join intent must be made explicit. Rakit already has named `RelationshipDefinition` declarations, so it should bind to the named FK/backref/through edge and validate it.

No heuristic "first matching FK" behavior is acceptable.

### Ordered relationships

Ordering is a Rakit semantic, not a Peewee default ordering shortcut. A writable ordered relation requires an explicit position field on the child or association model. Reorder mutations update that field inside the root UoW.

### Destructive behavior

Peewee FK `on_delete`/`on_update` configuration describes database relationship behavior. It does not authorize destructive Rakit API/UI actions. Rakit's explicit destructive policy remains authoritative.

### Async relationship reads

Peewee's async extension has a sharp boundary around lazy ORM access: ordinary synchronous lazy relationship loading cannot be allowed to escape the greenlet/async bridge.

Rakit relationship code should therefore use explicit async-safe paths such as:

- joined `Model.select()` executed by `database.list/get` or query `aexecute()` on the stable async line;
- `database.aprefetch(...)` / explicit prefetch for collections;
- `database.run(...)` only for documented synchronous Peewee operations that require the bridge;
- explicit through-model queries for M2M/association relationships.

The runtime must not depend on a transport/UI caller touching a model attribute that silently issues a synchronous query outside the bridge.

### Relationship concurrency

Child and association resources can reuse the same conditional-update concurrency primitive as ordinary Peewee resources. Graph mutations that claim parent concurrency must claim/advance the parent version in the same root transaction before or as part of the relationship graph write sequence, preserving Rakit's all-or-nothing graph semantics.

### Relationship decision records

- **PEEWEE-R7:** Named `ForeignKeyField` plus documented back-reference/model metadata is sufficient for neutral many-to-one/one-to-many validation. **PASS**.
- **PEEWEE-R8:** Use Peewee's documented `Model._meta`/metadata graph seam for relationship introspection; do not infer that `_meta` is unusable merely because of its name.
- **PEEWEE-R9:** `ONE_TO_ONE` requires proven uniqueness on the FK edge; a plain FK is never promoted by declaration alone.
- **PEEWEE-R10:** Native `ManyToManyField` may be recognized through its public through-model surface, but Rakit should prefer explicit async DML against the through model for mutations.
- **PEEWEE-R11:** Rich association-object behavior uses an explicit intermediary Peewee model with its own supported scalar identity and exposed association fields.
- **PEEWEE-R12:** Writable ordering requires an explicit position field; model default ordering alone is insufficient.
- **PEEWEE-R13:** Peewee `on_delete`/`on_update` behavior never grants Rakit destructive permission.
- **PEEWEE-R14:** Relationship reads/writes must remain on async-safe bridge/query paths inside the root-UoW task; unbridged lazy loads are not an acceptable implementation strategy.
- **PEEWEE-R15:** Multiple FK paths, incompatible declarations, composite identities, or unsupported relation shapes fail closed.
- **PEEWEE-R16:** Native M2M shapes with inheritance or other upstream-documented caveats must be rejected unless explicit through-model binding proves the neutral semantics.

## Deliberately unsupported / fail-closed shapes

A neutral Peewee 5/5 implementation may reject:

- relationships represented only by arbitrary ad-hoc join expressions rather than a declared FK/through/association resource;
- ambiguous multiple FK/through paths without explicit binding;
- composite Rakit resource identities;
- synchronous lazy relation I/O outside the async bridge;
- native M2M inheritance shapes whose semantics are not proven;
- destructive behavior inferred only from FK cascade configuration;
- snapshot/no-op concurrency whose affected-row semantics are not proven on the claimed backend matrix;
- Peewee versions below the accepted parity floor for the atomic capability.

## Peewee implementation acceptance matrix — research output

Before capability promotion, implementation must prove at least:

| Area | Required proof |
| --- | --- |
| FK / many-to-one | introspection, read, scoped link, nullable unlink, target validation |
| backref / one-to-many | read, scoped child create/update/unlink where policy permits |
| one-to-one | unique-FK proof, forward/backward read, writable supported direction |
| many-to-many | native through discovery, explicit async link/unlink/clear-policy behavior |
| association object | explicit intermediary model, scalar edits, target resolution, delete/unlink policy |
| ordering | deterministic read + reorder through explicit position field |
| async I/O | no accidental unbridged lazy relation query |
| transaction | all graph mutations commit/rollback together inside existing `PeeweeUnitOfWork` |
| parent/child concurrency | stale graph writers reject without partial durability |
| atomic update | identity + expected version + write + version advancement in one UPDATE |
| atomic delete | identity + expected version in one DELETE |
| affected rows | SQLite + PostgreSQL/asyncpg + MySQL/aiomysql behavior proven at accepted lower bound and latest allowed 4.x |
| dependency | proposed `peewee>=4.0.8,<5` passes Python/lowest/latest/artifact matrices before promotion |
| metadata | documented `_meta`/field/through-model seams only; unsupported shapes fail closed |

The current Rakit permanent Peewee conformance suite is SQLite-based. A future 5/5 implementation should add database-specific proof where atomic rowcount behavior is part of the advertised guarantee rather than assuming the SQLite result generalizes to asyncpg/aiomysql.

## Peewee final research verdict

```text
Atomic optimistic concurrency   PASS**
Relationships                  PASS*
Potential capability profile   5/5
Current 4.0.2 floor sufficient NO for global atomic parity
Recommended parity floor       peewee>=4.0.8,<5
Core redesign required         NO
New transaction model required NO
Explicit through/association   YES for rich graph semantics
Async bridge discipline        REQUIRED
Fail-closed semantics          REQUIRED
Capability promotion now       NO
```

`*` Relationship PASS means conformance with Rakit's neutral relationship contract, not support for every arbitrary Peewee join/query shape.

`**` Atomic concurrency PASS assumes the parity implementation raises the dependency floor to a line with fixed asyncpg DML rowcounts and stable upstream async APIs, and then proves affected-row behavior across the database matrix. If the dependency floor remains `>=4.0.2`, Rakit must **not** advertise the global atomic capability merely on SQLite evidence.

---

# Remaining providers

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

# Cross-provider observations so far

After SQLAlchemy Core, Tortoise, and Peewee, several design principles are consistent:

1. **Capability equality does not imply implementation equality.** Core derives physical relation paths from schema plus explicit binding when needed; Tortoise uses named ORM relation metadata; Peewee uses named FK/backref/through metadata. All can still satisfy the same neutral Rakit behavior.
2. **Atomic optimistic concurrency is one conditional database mutation, not a specific ORM feature.** SQLAlchemy Core uses SQL expressions, Tortoise uses filtered `QuerySet.update()`/`delete()`, and Peewee uses conditional model UPDATE/DELETE executed through the async database.
3. **Version-column concurrency is the strongest cross-provider first target.** Advancing a dedicated version field in the same mutation avoids much of the changed-row vs matched-row ambiguity that affects snapshot/no-op updates.
4. **Affected-row semantics are part of the dependency/runtime contract.** Peewee proves that an otherwise-capable query API is insufficient when a supported async driver cannot report UPDATE/DELETE rowcounts correctly at the declared lower bound.
5. **Association objects should remain explicit resources.** Tortoise needs an explicit association model because its native M2M through option is table-oriented; Peewee naturally supports an explicit intermediary model and recommends that pattern for complex M2M. Core likewise can use an explicit association table/resource binding.
6. **No shared core redesign is justified yet.** Provider-local adapters can express the researched behavior with existing neutral contracts. Wait for Piccolo before deciding whether any shared helper/generalization is warranted.

The dependency-floor issue is provider-specific: capability promotion may legitimately require tightening one optional integration's upstream range when the old lower bound cannot satisfy the new behavioral guarantee. That should be treated as an explicit compatibility decision in the later implementation plan, never as an incidental version bump.

# Relationship to Plan 03

Plan 03 covers Authentication, Authorization, and Security. Existing built-in auth/session persistence is SQLAlchemy-backed. This parity research should inform future Plan 03 work in two ways:

1. Keep auth/security contracts neutral where the behavior is genuinely persistence-neutral.
2. Keep SQLAlchemy-specific storage/session implementation inside its adapter/package boundary rather than generalizing ORM assumptions into Rakit core.

This document does **not** authorize an auth backend rewrite and does not imply that every persistence provider must become an authentication storage provider. Authentication-provider parity must be evaluated separately from persistence capability parity.

# Research completion gate

This research workstream is ready to become implementation input only after:

- SQLAlchemy Core findings are recorded — **Complete**;
- Tortoise findings are recorded — **Complete**;
- Peewee findings are recorded — **Complete**;
- Piccolo findings are recorded — Pending;
- cross-provider comparison identifies any core-contract pressure;
- implementation order and acceptance matrix are written explicitly;
- no capability is promoted solely from research evidence.
