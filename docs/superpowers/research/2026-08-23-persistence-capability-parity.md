# Persistence Capability Parity Research

**Status:** Provider research complete; cross-provider implementation planning pending

**Date:** 2026-08-23

**Branch:** `research/persistence-capability-parity`

**Purpose:** Record evidence-backed feasibility decisions for first-party persistence providers before any capability promotion or follow-on security/authentication work. This document is research input, not an implementation plan and not proof that a capability is already shipped.

## Why this research exists

Rakit advertises persistence capabilities conservatively and only after behavioral proof. The shipped providers intentionally do not have forced parity.

The five canonical persistence capability identifiers are:

- `persistence.read`
- `persistence.write`
- `transactions.root-uow`
- `persistence.relationships`
- `concurrency.atomic-optimistic`

The SQLAlchemy ORM reference provider already proves all five. SQLAlchemy Core, Tortoise, Peewee, and Piccolo currently advertise only read, write, and root-UoW. This research asks whether those four providers can honestly satisfy the remaining neutral Rakit semantics through their native public APIs without introducing a universal persistence DSL, fake ORM layer, backend-specific concerns in `rakit-core`, or silent semantic degradation.

The findings are also intended to inform later work around Plan 03 — Authentication, Authorization, and Security — because built-in authentication/session persistence is currently SQLAlchemy-backed. Future work should distinguish genuinely persistence-neutral behavior from SQLAlchemy-ORM-only implementation assumptions.

## Research rules

- Do not change advertised capabilities during research.
- Do not treat foreign-key metadata alone as proof of `persistence.relationships`.
- Do not emulate optimistic concurrency with a non-atomic read-check-write sequence.
- Use maintained public or intentionally documented backend metadata/query APIs for new parity behavior.
- Preserve one Rakit root unit of work for mutations that claim `transactions.root-uow`.
- Fail closed on ambiguous, unsupported, or unproven native shapes.
- Capability parity means neutral Rakit behavioral parity, not full backend feature parity.
- Composite Rakit resource identity remains outside this research unless separately designed and approved.
- A feasibility PASS does not authorize capability promotion. Source implementation, source-first smoke, permanent conformance, dependency/runtime matrices, and exact-head CI remain mandatory later.

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

The current Core generated mutation executor already executes through the `AsyncConnection` owned by `SQLAlchemyCoreUnitOfWork`; it only lacks concurrency predicate/runtime wiring and currently advertises `atomic_concurrency=False`.

The required native shape is one conditional mutation inside the existing root UoW:

```sql
UPDATE article
SET title = :title,
    version = :next_version
WHERE id = :id
  AND version = :expected_version
```

Required behavior:

- one matched row → success;
- zero matched rows → stale/race conflict after initial existence/token validation;
- conditional delete follows the same atomic predicate rule;
- no read-check-unconditional-write fallback;
- uncertain affected/matched-row semantics fail closed;
- Core records are mappings, so Core needs mapping-aware concurrency field access rather than pretending row mappings are ORM instances.

### Atomic decision records

- **CORE-R1:** SQLAlchemy Core optimistic concurrency is feasible. **PASS**.
- **CORE-R2:** Concurrency must use one conditional SQL mutation; no read-check-write emulation.
- **CORE-R3:** Reliable affected/matched-row semantics are mandatory; uncertain dialect behavior fails closed.
- **CORE-R4:** Core requires mapping-aware concurrency version access rather than ORM-style attribute assumptions.

## Relationships

`RelationshipDefinition` remains the semantic source of truth. SQLAlchemy Core only validates and binds that intent to native `Table`, column, foreign-key, uniqueness, and association-table metadata.

Feasible neutral shapes include:

- many-to-one;
- one-to-many;
- one-to-one when uniqueness is proven;
- many-to-many;
- explicit association object;
- ordering through an explicit position field;
- explicit destructive policy;
- graph mutation inside the existing Core root UoW.

Schema metadata cannot always infer application intent. Multiple foreign keys to the same target or multiple possible bridge tables are genuine ambiguities:

```text
exactly one compatible physical path -> inference may be allowed
zero compatible paths                -> configuration error
multiple compatible paths            -> explicit adapter binding required
```

A future SQLAlchemy-Core-only binding may identify the Rakit relationship id, source/target tables, and physical local/remote columns. It must not become a Rakit-wide persistence DSL.

A neutral PASS does not require arbitrary SQLAlchemy ORM mapper behavior such as custom `primaryjoin`, mapper lazy-loading semantics, `viewonly`, or cascade/delete-orphan authority.

### Relationship decision records

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

`*` Relationship PASS means conformance with the neutral Rakit relationship contract, not complete SQLAlchemy ORM feature parity.

---

# Tortoise ORM

**Research status:** Complete / locked

Provider: `persistence.tortoise`

Rakit currently supports `tortoise-orm>=1.1.7,<2`. The research also inspected the maintained 1.1.8 line.

| Capability | Shipped now | Research verdict |
| --- | --- | --- |
| `persistence.read` | Yes | Existing |
| `persistence.write` | Yes | Existing |
| `transactions.root-uow` | Yes | Existing |
| `persistence.relationships` | No | **PASS with explicit association-resource semantics** |
| `concurrency.atomic-optimistic` | No | **PASS with backend/conformance gate** |

**Feasibility conclusion:** Tortoise can plausibly reach a truthful **5/5** profile using native model/query/relation APIs. No new transaction architecture or core redesign is required.

## Atomic optimistic concurrency

The existing adapter already routes CRUD through the `TransactionalDBClient` owned by `TortoiseUnitOfWork`. A version-column mutation can be one database statement:

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
updated == 0 -> stale/race conflict
other count  -> fail closed
```

A preceding scoped read may validate existence and the signed Rakit token, but it must never authorize a separate unconditional write.

Tortoise records are attribute-bearing model instances, so the neutral attribute version-provider shape is naturally compatible.

A dedicated integer version column is the strongest first target because a successful mutation necessarily changes that field. Snapshot/no-op concurrency is more subtle because backend drivers can differ in changed-row versus matched-row reporting. Snapshot behavior must therefore be proven across the claimed database matrix or fail closed.

### Atomic decision records

- **TORTOISE-R1:** Tortoise can express optimistic compare-and-write as one native conditional UPDATE. **PASS**.
- **TORTOISE-R2:** Use filtered `QuerySet.update()` bound to the root transaction; never read-check then update unconditionally.
- **TORTOISE-R3:** Prefer version-column concurrency first; integer version plus `F("version") + 1` is the clearest cross-backend shape.
- **TORTOISE-R4:** Affected-row behavior is an implementation acceptance gate, especially for snapshot/no-op writes.
- **TORTOISE-R5:** Zero-row conditional mutation maps to the neutral race/conflict path after initial existence/token validation.
- **TORTOISE-R6:** All concurrency reads and writes must use the existing root UoW connection.

## Relationships

Tortoise is relationship-native. Public model description metadata exposes forward FK, backward FK, forward O2O, backward O2O, and M2M collections. New parity introspection should prefer public `Model.describe()` where sufficient rather than deepening new private metadata coupling.

Neutral mapping:

- `ForeignKeyField` → many-to-one;
- backward FK relation → one-to-many;
- `OneToOneField` → one-to-one;
- native M2M relation → many-to-many;
- explicit application-owned model with two relationship edges and scalar fields → association object.

Native M2M `add`, `remove`, and `clear` accept an explicit database client, so they can remain inside the Rakit root transaction. Candidate identities must still be resolved through scoped Rakit queries rather than accepting arbitrary transport-supplied objects.

### Association object boundary

Tortoise native `ManyToManyField(..., through=...)` treats `through` as a table-oriented construct; the inspected upstream line still notes that richer through-as-Model support is not the model being provided by that API. Rakit must therefore use an explicit Tortoise model for `ASSOCIATION_OBJECT` semantics:

```python
class Membership(Model):
    id = fields.IntField(primary_key=True)
    user = fields.ForeignKeyField("models.User")
    team = fields.ForeignKeyField("models.Team")
    role = fields.CharField(max_length=64)
    position = fields.IntField()
```

Ordering requires an explicit position field. ORM/database `on_delete` behavior never grants Rakit destructive permission.

### Relationship decision records

- **TORTOISE-R7:** Native FK/reverse-FK/O2O/M2M metadata is sufficient for neutral relationship validation. **PASS**.
- **TORTOISE-R8:** Prefer public `Model.describe()` for new relationship introspection where sufficient.
- **TORTOISE-R9:** Bind declarations by explicit Tortoise relationship name and validate target/cardinality; no heuristic first-match behavior.
- **TORTOISE-R10:** Native M2M operations are usable only when bound to the Rakit root transaction.
- **TORTOISE-R11:** Association objects use an explicit Tortoise model; a native M2M through table is not treated as a rich association model.
- **TORTOISE-R12:** Writable ordering requires an explicit position field.
- **TORTOISE-R13:** Tortoise `on_delete` semantics never grant Rakit destructive permission.
- **TORTOISE-R14:** Candidate/relationship resolution remains scoped and inside the root UoW.
- **TORTOISE-R15:** Unsupported or structurally inconsistent declarations fail closed.

## Tortoise implementation acceptance matrix

| Area | Required proof |
| --- | --- |
| FK / many-to-one | read, link, nullable unlink, target validation |
| reverse FK / one-to-many | read, scoped child create/update/unlink where allowed |
| one-to-one | forward/backward read and writable supported direction |
| many-to-many | read, add, duplicate-safe behavior, remove, clear/policy behavior, same root UoW |
| association object | explicit association model, scalar edits, target resolution, delete/unlink policy |
| ordering | deterministic read + reorder through explicit position field |
| graph transaction | all graph writes commit/rollback together |
| parent/child concurrency | stale graph changes reject without partial durability |
| atomic update/delete | identity + expected token predicate and mutation in one statement |
| affected rows | claimed DB matrix proves suitable semantics or unsupported mode fails closed |
| introspection | native metadata validates kind/target without heuristic guessing |

## Tortoise final research verdict

```text
Atomic optimistic concurrency   PASS**
Relationships                  PASS*
Potential capability profile   5/5
Core redesign required         NO
New transaction model required NO
Native relationship APIs       YES
Explicit association model     YES for association-object semantics
Fail-closed semantics          REQUIRED
Capability promotion now       NO
```

`*` Relationship PASS is for the neutral Rakit contract.

`**` Atomic PASS is subject to an implementation-time affected-row/backend matrix. Version-column compare-and-write is the recommended first target; snapshot/no-op behavior must be proven or rejected fail closed.

---

# Peewee 4 Async ORM

**Research status:** Complete / locked

Provider: `persistence.peewee`

Rakit currently ships `peewee>=4.0.2,<5`. Research inspected 4.0.2 behavior, the asyncpg row-count fix in 4.0.7, and the first upstream release which explicitly declares the asyncio API stable, 4.0.8.

| Capability | Shipped now | Research verdict |
| --- | --- | --- |
| `persistence.read` | Yes | Existing |
| `persistence.write` | Yes | Existing |
| `transactions.root-uow` | Yes | Existing |
| `persistence.relationships` | No | **PASS** |
| `concurrency.atomic-optimistic` | No | **PASS with required parity floor bump** |

**Feasibility conclusion:** Peewee async can plausibly reach a truthful **5/5** profile, but the atomic capability must not be promoted while claiming the current `peewee>=4.0.2` floor across all supported async backends.

## Dependency-floor finding

At 4.0.2:

- async SQLite obtains DML `cursor.rowcount`;
- async MySQL obtains DML `cursor.rowcount`;
- async PostgreSQL/asyncpg does not provide the reliable UPDATE/DELETE affected count Rakit needs for stale-write detection.

Peewee 4.0.7 explicitly fixes asyncpg UPDATE/DELETE row counts. Peewee 4.0.8 additionally marks the asyncio APIs stable.

Research recommendation for later parity implementation:

```text
current shipped floor:    peewee>=4.0.2,<5
recommended parity floor: peewee>=4.0.8,<5
```

This document does not itself modify the package dependency.

## Atomic optimistic concurrency

A native conditional mutation is feasible:

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

Required behavior:

```text
updated == 1 -> success
updated == 0 -> stale/race conflict
other count  -> fail closed
```

Conditional delete follows the same identity + version predicate pattern.

Peewee model instances work naturally with the neutral attribute version-provider shape. Integer version-column concurrency is the recommended first target. Snapshot/no-op behavior requires explicit SQLite + asyncpg + aiomysql proof because the provider depends on backend affected-row semantics.

### Atomic decision records

- **PEEWEE-R1:** Peewee can express optimistic compare-and-write as one conditional async UPDATE/DELETE. **PASS**.
- **PEEWEE-R2:** The current `>=4.0.2` lower bound is insufficient for global atomic parity because pre-4.0.7 asyncpg DML rowcounts are not reliable enough.
- **PEEWEE-R3:** The parity implementation should use `peewee>=4.0.8,<5`; 4.0.7 contains the rowcount fix and 4.0.8 is the first upstream-stable asyncio line.
- **PEEWEE-R4:** Prefer integer version-column concurrency first; snapshot/no-op mode requires backend proof or fails closed.
- **PEEWEE-R5:** All optimistic reads/writes remain in the existing `PeeweeUnitOfWork` task/database/`atomic()` boundary.
- **PEEWEE-R6:** Zero-row conditional mutation maps to neutral race/conflict after initial existence/token validation.

## Relationships

Peewee has sufficient documented model metadata and query primitives for neutral Rakit relationship semantics.

Neutral mapping:

- named `ForeignKeyField` → many-to-one;
- named backref → one-to-many;
- unique FK edge → one-to-one;
- `ManyToManyField` / through model → many-to-many;
- explicit intermediary model with two FKs and scalar fields → association object.

Peewee intentionally documents `Model._meta` as model metadata. Existing Rakit code already uses it. New parity behavior may use documented `_meta` fields/helpers, while avoiding undocumented lower-level implementation details where a documented seam exists.

For M2M mutation, Rakit should initially prefer explicit async DML against the through model rather than relying on synchronous-looking relation descriptor convenience methods:

```text
link   -> INSERT through-model row
unlink -> DELETE through-model row
clear  -> policy-authorized DELETE for this parent
```

This keeps transaction ownership, error semantics, and affected-row behavior visible through the adapter's established async execution path.

Peewee async relationship reads must not accidentally trigger unbridged synchronous lazy I/O. Use explicit joined/prefetched/query paths through the async bridge.

Ordering requires an explicit position field. FK `on_delete` / `on_update` never grants Rakit destructive permission.

### Relationship decision records

- **PEEWEE-R7:** Named `ForeignKeyField` plus documented back-reference metadata is sufficient for neutral many-to-one/one-to-many validation. **PASS**.
- **PEEWEE-R8:** Use Peewee's documented `Model._meta` metadata seam; underscore naming alone does not make it an unsupported private API.
- **PEEWEE-R9:** `ONE_TO_ONE` requires proven uniqueness on the FK edge.
- **PEEWEE-R10:** Native M2M may be recognized through its through-model surface; prefer explicit async through-model DML for Rakit mutations.
- **PEEWEE-R11:** Rich association-object behavior uses an explicit intermediary Peewee model with a supported scalar identity.
- **PEEWEE-R12:** Writable ordering requires an explicit position field.
- **PEEWEE-R13:** Peewee FK cascade behavior never grants Rakit destructive permission.
- **PEEWEE-R14:** Relationship reads/writes stay on async-safe bridge/query paths inside the root-UoW task.
- **PEEWEE-R15:** Multiple FK paths, incompatible declarations, composite identities, or unsupported shapes fail closed.
- **PEEWEE-R16:** Native M2M shapes with upstream caveats must be rejected unless explicit through-model binding proves neutral semantics.

## Peewee implementation acceptance matrix

| Area | Required proof |
| --- | --- |
| FK / many-to-one | introspection, read, scoped link, nullable unlink, target validation |
| backref / one-to-many | read, scoped child create/update/unlink where policy permits |
| one-to-one | unique-FK proof, forward/backward read, writable supported direction |
| many-to-many | through discovery, explicit async link/unlink/clear-policy behavior |
| association object | explicit intermediary model, scalar edits, target resolution, delete/unlink policy |
| ordering | deterministic read + reorder through explicit position field |
| async I/O | no accidental unbridged lazy relation query |
| transaction | graph mutations commit/rollback together in `PeeweeUnitOfWork` |
| parent/child concurrency | stale graph writers reject without partial durability |
| atomic update/delete | identity + expected version + mutation in one statement |
| affected rows | SQLite + PostgreSQL/asyncpg + MySQL/aiomysql proven at accepted floor and latest 4.x |
| dependency | proposed `peewee>=4.0.8,<5` passes Python/lowest/latest/artifact matrices |

## Peewee final research verdict

```text
Atomic optimistic concurrency   PASS**
Relationships                  PASS*
Potential capability profile   5/5
Current 4.0.2 floor sufficient NO for global atomic parity
Recommended parity floor       peewee>=4.0.8,<5
Core redesign required         NO
New transaction model required NO
Async bridge discipline        REQUIRED
Fail-closed semantics          REQUIRED
Capability promotion now       NO
```

`*` Relationship PASS means neutral Rakit relationship conformance, not arbitrary Peewee join/query parity.

`**` Atomic PASS assumes the later implementation raises the dependency floor and proves affected-row behavior across the claimed database matrix.

---

# Piccolo ORM

**Research status:** Complete / locked

Provider: `persistence.piccolo`

Rakit currently ships `piccolo>=1.30,<2`. Research inspected the current Rakit adapter, Piccolo 1.30.0 as the supported lower bound, and the maintained 1.x line (1.36.0 at the time of this research).

| Capability | Shipped now | Research verdict |
| --- | --- | --- |
| `persistence.read` | Yes | Existing |
| `persistence.write` | Yes | Existing |
| `transactions.root-uow` | Yes | Existing |
| `persistence.relationships` | No | **PASS with explicit joining-table semantics** |
| `concurrency.atomic-optimistic` | No | **PASS with RETURNING/backend conformance gate** |

**Feasibility conclusion:** Piccolo can plausibly reach a truthful **5/5** Rakit persistence profile on the current `piccolo>=1.30,<2` dependency line. No dependency-floor bump, core redesign, or new transaction model is currently justified.

## Existing Rakit foundation

Relevant seams:

- `packages/rakit-piccolo/src/rakit_piccolo/capabilities.py`
- `packages/rakit-piccolo/src/rakit_piccolo/introspection.py`
- `packages/rakit-piccolo/src/rakit_piccolo/generated.py`
- `packages/rakit-piccolo/src/rakit_piccolo/uow.py`

The current generated executor already uses Piccolo `UPDATE ... RETURNING identity` and `DELETE ... RETURNING identity`, then validates that exactly one row was returned. It merely rejects configured concurrency today and advertises `atomic_concurrency=False`.

`PiccoloUnitOfWork` already owns the root `Engine.transaction()` boundary and rejects entering when an external root transaction already exists. Piccolo's transaction context tracks transaction existence, and ordinary Piccolo queries participate in that transaction. Higher capabilities can therefore reuse the existing UoW.

## Piccolo atomic optimistic concurrency

### Verdict

**PASS with an implementation-time RETURNING/backend conformance gate.**

### Native strategy

Piccolo supports database-side arithmetic in UPDATE expressions and supports `returning(...)` for UPDATE and DELETE at the Rakit-supported 1.30 floor.

A version-column mutation can therefore be expressed as one database statement:

```python
updated = await (
    Model.update(
        {
            Model.name: proposed_name,
            Model.version: Model.version + 1,
        }
    )
    .where(
        Model.id == identity,
        Model.version == expected_version,
    )
    .returning(Model.id)
)
```

Required interpretation:

```text
len(updated) == 1 -> success
len(updated) == 0 -> stale/race conflict
other count       -> fail closed
```

Conditional delete follows the same shape:

```python
deleted = await (
    Model.delete()
    .where(
        Model.id == identity,
        Model.version == expected_version,
    )
    .returning(Model.id)
)
```

This is particularly useful for Rakit because success detection does **not** have to depend on backend driver rowcount semantics. The database returns the identities of rows matched and processed by the conditional mutation.

A preceding scoped read may validate existence and the signed Rakit token; the final write must still include the expected concurrency predicate. A zero-row result after initial validation is the race/stale conflict path.

### Version-provider compatibility

Piccolo `Table` instances expose column values as attributes, so the existing neutral attribute version-provider shape is naturally compatible.

Integer version-column concurrency is the recommended first implementation target and can use `version = version + 1` in the same UPDATE.

Snapshot-style concurrency is architecturally more promising here than with rowcount-dependent providers because success is observed through `RETURNING`. Even so, snapshot/no-op behavior must be proven across the claimed Piccolo engine matrix before it is advertised; do not infer portability solely from PostgreSQL behavior.

### RETURNING runtime gate

Piccolo 1.30 documentation explicitly states that UPDATE/DELETE `returning()` is supported on all supported PostgreSQL versions but requires SQLite 3.35.0 or newer.

This is not a new parity-only dependency: Rakit's **existing** Piccolo generated UPDATE/DELETE path already uses `returning(identity)`. Nevertheless, future 5/5 conformance should make the runtime assumption explicit and fail closed on a SQLite runtime which cannot support the existing required `RETURNING` behavior.

Cockroach uses Piccolo's PostgreSQL-derived engine/transaction implementation, but capability promotion still requires direct Cockroach proof rather than assuming every PostgreSQL query behavior transfers unchanged.

### Atomic decision records

- **PICCOLO-R1:** Piccolo can express optimistic compare-and-write as a single conditional UPDATE/DELETE with `RETURNING`. **PASS**.
- **PICCOLO-R2:** Reuse the current `returning(identity)` result as the authoritative success/stale detector; do not add a driver-rowcount dependency.
- **PICCOLO-R3:** Prefer integer version-column concurrency first, using `version = version + 1` inside the same conditional UPDATE.
- **PICCOLO-R4:** Snapshot concurrency is architecturally feasible but requires explicit engine-matrix proof before advertisement.
- **PICCOLO-R5:** The current `piccolo>=1.30,<2` floor already contains the required UPDATE arithmetic, WHERE, RETURNING, transaction, FK, and M2M primitives; no floor bump is justified by this research.
- **PICCOLO-R6:** SQLite older than 3.35 cannot satisfy the required RETURNING path and must fail closed; this is also an existing generated-write runtime constraint.
- **PICCOLO-R7:** All optimistic concurrency activity remains inside the existing `PiccoloUnitOfWork` root transaction.

## Piccolo relationships

### Verdict

**PASS with explicit joining-table semantics and a Cockroach conformance gate.**

Piccolo exposes enough stable model metadata for neutral Rakit relationship validation. At the 1.30 floor, `TableMeta` contains:

- `foreign_key_columns` for forward FK edges;
- `foreign_key_references` for reverse FK edges;
- `m2m_relationships` for named M2M declarations;
- primary-key and ordinary column metadata.

`ForeignKey` metadata exposes referenced table, target column, nullability, uniqueness, `on_delete`, and `on_update`. Piccolo itself documents and uses `Table._meta` as its metadata/introspection seam, including for external libraries, so `_meta` is acceptable here when Rakit uses stable documented fields rather than arbitrary implementation internals.

### Many-to-one

A named Piccolo `ForeignKey` maps directly to `MANY_TO_ONE`.

Rakit must validate:

- the named native FK exists;
- the resolved referenced table matches the target resource;
- nullable semantics are compatible;
- the declared target column is supported.

Link/unlink should use explicit conditional Piccolo UPDATE inside the root UoW.

### One-to-many

Piccolo records reverse FK edges through `foreign_key_references`. A Rakit `ONE_TO_MANY` declaration should bind to a specific reverse FK edge rather than infer a relationship merely from target-table equality.

Child reads and writes can use explicit table queries with the parent FK predicate inside the same transaction.

### One-to-one

Piccolo does not need a dedicated O2O column type for Rakit semantics. An FK edge may be treated as one-to-one only when uniqueness is proven by native metadata or a compatible explicit unique constraint. A plain FK must never be promoted to O2O by declaration alone.

### Many-to-many

Piccolo M2M is backed by a real joining `Table`. `M2MMeta` exposes the resolved joining table plus primary/secondary FK information, and allows explicit `foreign_key_columns` when the joining table has more than two FKs.

For Rakit, the preferred implementation is to treat that joining table as the physical source of truth and use explicit queries/DML for neutral reads and writes:

```text
link   -> INSERT joining-table row
unlink -> DELETE joining-table row
clear  -> policy-authorized DELETE for this parent
read   -> joining-table query + scoped target resolution
```

Piccolo's native `add_m2m` / `remove_m2m` helpers are transaction-aware and upstream tests prove that M2M add works inside an already active transaction. They are useful evidence, but Rakit does not need to depend on those convenience helpers when explicit joining-table operations provide clearer scope, policy, concurrency, and backend behavior.

### Association object

Piccolo aligns especially well with Rakit's association-object model because the joining table is already an ordinary `Table` and can contain extra scalar columns.

At the 1.30 floor, upstream tests model an M2M joining table with an additional scalar field and verify that `add_m2m(..., extra_column_values=...)` persists it.

A Rakit association can therefore be represented conceptually as:

```python
class Membership(Table):
    user = ForeignKey(User)
    team = ForeignKey(Team)
    role = Varchar()
    position = Integer()
```

Piccolo supplies a scalar serial primary key by default unless the application overrides it, which fits Rakit's current single scalar identity contract. If an application replaces that with an unsupported/composite identity shape, association-resource behavior fails closed.

Association scalar edits and reordering use ordinary Piccolo UPDATE statements on the joining table.

### Cockroach M2M caveat

Piccolo 1.30's own M2M test suite skips some M2M select-helper paths on Cockroach because of an upstream Cockroach decorrelation limitation under asyncpg.

Rakit must not ignore this. It also does not automatically block the neutral relationship capability, because Rakit can avoid the affected M2M subquery shortcut and use explicit joining-table queries instead.

Implementation promotion therefore requires one of two outcomes:

1. prove the explicit joining-table Rakit read/write path on Cockroach; or
2. fail closed / explicitly exclude the unsupported Cockroach shape from the claimed backend matrix.

No silent fallback or untested assumption is acceptable.

### Ordering and destructive behavior

Writable ordering requires an explicit position field on the child or joining association table. Default query ordering alone is not writable relationship semantics.

Piccolo `ForeignKey` `on_delete` / `on_update` configuration remains database/ORM behavior. It never grants destructive Rakit API/UI permission; Rakit's explicit destructive policy remains authoritative.

### Relationship decision records

- **PICCOLO-R8:** Piccolo `Table` metadata is sufficient for neutral FK/reverse-FK/M2M relationship validation. **PASS**.
- **PICCOLO-R9:** Use stable Piccolo `_meta` seams such as `foreign_key_columns`, `foreign_key_references`, `m2m_relationships`, and resolved FK metadata; underscore naming alone does not make the documented metadata contract unusable.
- **PICCOLO-R10:** `ONE_TO_ONE` requires proven uniqueness on the FK edge; a plain FK is never promoted by declaration alone.
- **PICCOLO-R11:** M2M binds to a real joining `Table`; ambiguous or >2-FK joining shapes require explicit native FK selection rather than guessing.
- **PICCOLO-R12:** Association-object behavior uses an explicit Piccolo joining `Table` resource with a supported scalar identity and ordinary scalar fields.
- **PICCOLO-R13:** Prefer explicit joining-table queries/DML for Rakit graph semantics even though native M2M helpers can participate in an existing transaction.
- **PICCOLO-R14:** Writable ordering requires an explicit position field.
- **PICCOLO-R15:** Piccolo `on_delete` / `on_update` behavior never grants Rakit destructive permission.
- **PICCOLO-R16:** The upstream Cockroach M2M select-helper caveat must be proven around through the explicit joining-table path or fail closed; it cannot be ignored.
- **PICCOLO-R17:** Relationship reads/writes and scoped candidate resolution remain inside the existing Piccolo root UoW.
- **PICCOLO-R18:** Unsupported/ambiguous relation shapes and unsupported/composite resource identities fail closed.

## Piccolo implementation acceptance matrix

| Area | Required proof |
| --- | --- |
| FK / many-to-one | introspection, scoped read/link, nullable unlink, target validation |
| reverse FK / one-to-many | reverse-edge validation, read, child create/update/unlink where allowed |
| one-to-one | unique-FK/constraint proof and supported writable direction |
| many-to-many | joining-table discovery, explicit read/link/unlink/clear-policy semantics |
| association object | explicit joining Table, scalar edits, target resolution, delete/unlink policy |
| ordering | deterministic read + reorder through explicit position field |
| transaction | all graph writes commit/rollback together in `PiccoloUnitOfWork` |
| parent/child concurrency | stale graph writers reject without partial durability |
| atomic update | identity + expected version + write + version advancement in one UPDATE + RETURNING |
| atomic delete | identity + expected version in one DELETE + RETURNING |
| SQLite runtime | RETURNING-capable SQLite runtime (>=3.35) |
| PostgreSQL | conditional UPDATE/DELETE + RETURNING and graph paths proven |
| Cockroach | conditional mutation proven; explicit joining-table M2M path proven or fails closed |
| dependency | `piccolo>=1.30,<2` lowest/latest and Python/artifact matrices remain green |
| metadata | stable `_meta` / FK / M2M joining-table seams only; ambiguity fails closed |

## Piccolo final research verdict

```text
Atomic optimistic concurrency   PASS**
Relationships                  PASS*
Potential capability profile   5/5
Current >=1.30 floor sufficient YES
Dependency floor bump          NO
Core redesign required         NO
New transaction model required NO
Explicit joining table         YES for M2M / association semantics
RETURNING-based conflict proof YES
Fail-closed semantics          REQUIRED
Capability promotion now       NO
```

`*` Relationship PASS means neutral Rakit semantics. Cockroach requires explicit joining-table conformance because Piccolo's native M2M select shortcut has an upstream caveat there.

`**` Atomic PASS uses conditional UPDATE/DELETE + RETURNING. Promotion still requires PostgreSQL, supported SQLite runtime, and Cockroach proof for the backend matrix Rakit chooses to advertise.

---

# Deferred provider

## Masonite ORM

**Status:** Deferred research

Masonite remains outside the completed D3 closure gate and outside this parity comparison unless the maintainer explicitly resumes its dedicated feasibility pass.

---

# Cross-provider observations after provider research

All four shipped 3/5 providers researched here are **architecturally capable of a truthful 5/5 profile under the neutral Rakit contracts**, subject to provider-specific implementation/conformance gates.

| Provider | Relationships | Atomic optimistic | Important provider-specific gate |
| --- | --- | --- | --- |
| SQLAlchemy Core | PASS | PASS | explicit binding for ambiguous schema paths; sane rowcount |
| Tortoise | PASS | PASS | affected-row / snapshot backend matrix; explicit association model |
| Peewee async | PASS | PASS | parity floor should move to `peewee>=4.0.8,<5`; async DB matrix |
| Piccolo | PASS | PASS | RETURNING runtime/backend proof; Cockroach explicit M2M path |

The research establishes these common design principles:

1. **Capability equality does not imply implementation equality.** Core uses schema/FK binding; Tortoise uses named relation metadata; Peewee uses named FK/backref/through metadata; Piccolo uses FK/reverse metadata and a real joining `Table`.
2. **Atomic optimistic concurrency is defined by one conditional database mutation, not by a particular ORM API.**
3. **Success detection is adapter-native.** SQLAlchemy Core uses sane rowcount; Tortoise and Peewee use affected-row counts; Piccolo can use `RETURNING(identity)` result length.
4. **Version-column concurrency is the safest common first target.** A dedicated version field is advanced by the same mutation that applies the user change.
5. **Snapshot/no-op concurrency should not be forced into a common mechanism.** Tortoise/Peewee need strong affected-row proof, SQLAlchemy Core needs sane matched-row semantics, and Piccolo's RETURNING path may support it more cleanly. Only neutral behavior should be shared.
6. **Association objects remain explicit resources.** ORM M2M convenience must not erase association identity, scalar fields, ordering, policy, or concurrency.
7. **Writable ordering always requires an explicit position field.** Default ORM ordering is not enough.
8. **Database/ORM cascades never grant destructive Rakit permission.** Structure and destructive policy remain separate.
9. **Ambiguity always fails closed.** A provider can use its native explicit-binding mechanism, but Rakit never chooses a first matching relationship path silently.
10. **No shared core redesign is justified by the provider research.** Existing neutral relationship, concurrency, UoW, identity, and capability contracts are sufficient for the researched implementation shapes.
11. **Compatibility gates are provider-specific and explicit.** Peewee may require a tighter dependency floor; Piccolo has a SQLite runtime and Cockroach M2M proof gate; these are plan decisions, not incidental implementation details.
12. **D3 does not need to be reopened.** This parity effort can be an additive implementation workstream built on top of the completed D3 provider ecosystem.

## Common implementation pressure to carry forward

The eventual implementation plan should begin from neutral invariants, then let each adapter choose its native mechanism:

```text
Neutral optimistic invariant
    scoped existence/token validation
    + one conditional mutation
    + deterministic success/stale observation
    + same root UoW
    + conflict without partial durability

Neutral relationship invariant
    explicit RelationshipDefinition
    + native target/cardinality validation
    + scoped candidate resolution
    + explicit association/ordering metadata where needed
    + same root UoW
    + explicit destructive policy
    + fail-closed ambiguity
```

The research does **not** support creating a universal relationship DSL beyond the existing neutral definitions, a universal query AST for adapter internals, or a shared rowcount abstraction merely to make implementation code look identical.

---

# Relationship to Plan 03

Plan 03 covers Authentication, Authorization, and Security. Existing built-in authentication/session persistence is SQLAlchemy-backed. This parity research should inform future Plan 03 work in two ways:

1. keep auth/security contracts neutral where the behavior is genuinely persistence-neutral; and
2. keep SQLAlchemy-specific storage/session implementation inside its adapter/package boundary rather than generalizing ORM assumptions into Rakit core.

This document does **not** authorize an auth backend rewrite and does not imply that every persistence provider must become an authentication storage provider. Authentication-provider parity must be evaluated separately from persistence capability parity.

---

# Research completion gate

Provider feasibility research is complete. Before this document becomes direct implementation input, the remaining cross-provider planning work is:

- SQLAlchemy Core findings — **Complete / locked**;
- Tortoise findings — **Complete / locked**;
- Peewee findings — **Complete / locked**;
- Piccolo findings — **Complete / locked**;
- cross-provider neutral semantics comparison — **Complete at research level**;
- implementation ordering and workstream boundaries — Pending;
- final shared acceptance/conformance matrix — Pending;
- dependency/runtime compatibility decisions written into the implementation plan — Pending;
- no capability is promoted solely from research evidence.

Recommended next planning step after maintainer approval: turn these findings into an additive persistence capability-parity implementation plan, preserving the project's source-first workflow and provider-by-provider verification.