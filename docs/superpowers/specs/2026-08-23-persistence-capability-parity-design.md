# Persistence Capability Parity Design

**Status:** Approved / locked for implementation planning

**Date:** 2026-08-23

**Branch:** `research/persistence-capability-parity`

**Research input:** `docs/superpowers/research/2026-08-23-persistence-capability-parity.md`

## Context

Phase D3 is already complete for the shipped persistence ecosystem. SQLAlchemy ORM advertises the full five-capability profile, while SQLAlchemy Core, Tortoise ORM, Peewee async, and Piccolo ORM currently advertise read, write, and root-UoW only.

Provider-by-provider research concluded that all four 3/5 providers can plausibly reach a truthful 5/5 profile without introducing a universal persistence DSL, fake ORM layer, new transaction architecture, or backend-specific concerns in `rakit-core`.

This work is therefore an **additive persistence capability-parity track** built on top of completed D3. It does not reopen D3, does not change SQLAlchemy ORM's role as the default/reference persistence provider, and does not authorize release, tagging, publication, or Plan 03 authentication-provider parity.

The two capabilities to add where implementation proof succeeds are:

- `persistence.relationships`
- `concurrency.atomic-optimistic`

The design intentionally separates **shared neutral semantics** from **provider-native implementation mechanisms**.

## Goals

1. Raise the four shipped 3/5 providers to 5/5 only when the existing Rakit capability contracts are behaviorally proven.
2. Preserve native backend models, metadata, query APIs, and transaction behavior.
3. Reuse the existing root UoW for every new mutation path.
4. Reuse the existing neutral relationship and concurrency contracts in core rather than widening them speculatively.
5. Strengthen capability conformance so capability promotion follows proof, not implementation intent.
6. Keep each provider independently reviewable, reversible, and mergeable.
7. Keep provider-specific compatibility constraints explicit in implementation and CI.
8. Leave SQLAlchemy-specific authentication/session storage inside its existing package boundary when Plan 03 resumes later.

## Non-goals

- reopening or renumbering completed D3;
- replacing SQLAlchemy ORM as the default/reference provider;
- implementing Masonite ORM;
- composite resource identities;
- multi-database routing;
- migration-tool abstraction;
- universal ORM/query/relationship DSL;
- shared backend rowcount abstraction;
- forcing snapshot concurrency where backend semantics are not proven;
- requiring every persistence provider to become an authentication storage provider;
- release, tag, TestPyPI, or PyPI publication.

## Architectural principle

Capability equality means **observable Rakit semantics are equal**. It does not mean the adapters use equal code or equal upstream primitives.

The neutral optimistic invariant is:

```text
scoped existence / token validation
    + expected-state predicate
    + one conditional database mutation
    + deterministic success / stale observation
    + same root UoW
    + no partial durability on conflict
```

The neutral relationship invariant is:

```text
RelationshipDefinition
    + native target / cardinality validation
    + scoped candidate resolution
    + explicit association / ordering metadata when required
    + same root UoW
    + explicit destructive policy
    + fail-closed ambiguity
```

Provider implementation remains native:

```text
SQLAlchemy Core -> SQL expressions + schema metadata + sane rowcount
Tortoise        -> named ORM relations + filtered QuerySet mutations
Peewee          -> FK/backref/through metadata + async DML + affected rows
Piccolo         -> FK/reverse/M2M Table metadata + RETURNING-based DML
```

No shared implementation helper is created merely to make these mechanisms look alike.

## Existing core seams are sufficient

The work reuses existing neutral contracts:

- `ConcurrencyVersionProvider`
  - `version_for(record)`
  - `predicate_values_for(record)`
  - `next_values_for(record)`
- `RelationshipDefinition`
- `RelationshipMetadata`
- immutable relationship mutation plans / receipts;
- `transactions.root-uow` operation ownership;
- canonical `RESOURCE_CONFLICT` and not-found behavior;
- capability-specific conformance harness protocols in `rakit_core.testing.capability_conformance`.

SQLAlchemy ORM is the **reference behavior**, not a reference implementation. Its current concurrency, relationship-introspection, relationship-mutation, and graph-mutation suites are evidence for observable semantics only. Other adapters must not copy mapper/session assumptions into their own implementations or into core.

## Delivery strategy

The locked strategy is **provider-first**, not capability-first and not a big-bang parity branch.

Each provider completes both missing capabilities, proves them, and promotes its capability profile before the next provider begins.

Locked order:

```text
P0 Shared acceptance contract
P1 SQLAlchemy Core
P2 Tortoise ORM
P3 Piccolo ORM
P4 Peewee Async ORM
P5 Cross-provider closure
```

### Why this order

**SQLAlchemy Core first**

- already shares the mature SQLAlchemy package and transaction stack;
- strongest place to pressure-test mapping-aware concurrency and explicit physical relationship binding;
- lowest dependency-management risk;
- reveals whether any core-contract pressure exists before independent ORMs are changed.

**Tortoise second**

- relationship-native and async-first;
- validates that the Core design did not accidentally become schema-table-specific;
- explicit association model boundary is well understood from research.

**Piccolo third**

- uses a distinct RETURNING-based conflict detector;
- tests whether conformance truly describes behavior rather than rowcount mechanics;
- current dependency floor is sufficient, so compatibility churn remains low.

**Peewee last**

- only researched provider requiring a proposed dependency-floor change for global atomic parity;
- async bridge and backend rowcount matrix add the highest compatibility risk;
- postponing it separates semantic stabilization from dependency-range tightening.

## Per-provider source-first sequence

Within P1-P4 the implementation order is locked:

```text
1. atomic optimistic source implementation
2. non-test / source-level verification
3. relationship introspection + source implementation
4. non-test / source-level graph verification
5. permanent capability-specific regression / conformance tests
6. lowest / latest / backend compatibility gates
7. capability profile promotion
8. exact-head CI and review
9. squash merge
```

Permanent tests are added after the source behavior works, matching the project's established source-first workflow.

A provider may remain below 5/5 if implementation evidence contradicts research. Capability promotion is never required merely because another provider reached parity.

## P0 — Shared acceptance contract

P0 is documentation and conformance planning only. It must not add a universal execution layer.

Responsibilities:

- lock the shared behavior matrix in this design;
- confirm existing core relationship/concurrency contracts are sufficient;
- identify reusable conformance assertions only where the assertion is genuinely backend-neutral;
- preserve existing capability identifiers and version `v1` contracts;
- establish the promotion rule: **implementation first, proof second, capability advertisement last**.

The existing conformance hooks remain authoritative:

- `assert_relationship_semantics()`
- `assert_atomic_optimistic_semantics()`

They may internally gain more precise reusable assertions/fixtures when implementation proves that doing so removes duplication without encoding backend mechanics. Do not design a new testing framework.

## Shared relationship conformance matrix

Every provider advertising `persistence.relationships` must prove the applicable neutral behaviors below.

| Area | Required proof |
| --- | --- |
| Native metadata | declared relationship resolves to compatible native structure |
| Kind/cardinality | native kind and to-one/to-many semantics match `RelationshipDefinition` |
| Target | native target matches the declared Rakit target resource |
| Nullable semantics | nullable link/clear behavior matches declaration |
| Many-to-one | read, scoped set/link, nullable clear where allowed |
| One-to-many | read, scoped child create/update/unlink where allowed |
| One-to-one | singularity is proven by native uniqueness; plain FK is insufficient |
| Many-to-many | read, link/add, duplicate behavior, unlink/remove, clear according to policy |
| Association object | explicit association resource, supported scalar identity, scalar edits, target resolution |
| Ordering | deterministic read + reorder using an explicit position field |
| Candidate scope | invisible/unauthorized targets cannot be resolved or linked |
| Authorization | mutation uses compiled Rakit permission requirements |
| Destructive policy | DB/ORM cascade never grants Rakit destructive permission |
| Ambiguity | zero/multiple incompatible paths fail closed; no first-match guessing |
| Root UoW | all graph writes commit or roll back together |
| Parent concurrency | stale parent rejects graph write without partial durability |
| Child/association concurrency | stale child/edge rejects without partial durability |
| Error translation | backend exceptions do not leak as the public contract |
| Identity | only currently supported scalar Rakit resource identities are accepted |

Not every provider must expose every upstream relationship convenience. Conformance is to the neutral Rakit relationship surface only.

## Shared atomic-optimistic conformance matrix

Every provider advertising `concurrency.atomic-optimistic` must prove:

| Area | Required proof |
| --- | --- |
| Initial absence | scoped missing resource maps to neutral not-found behavior |
| Token binding | wrong resource/identity/version token maps to `RESOURCE_CONFLICT` |
| Conditional update | identity + expected state + user change occur in one conditional mutation |
| Version advancement | version-column strategy advances in the same mutation |
| Stale update | conditional mutation observes zero/no returned row and maps to conflict |
| Conditional delete | identity + expected state occur in one conditional delete |
| Stale delete | stale delete fails without deleting current state |
| Root UoW | optimistic mutation participates in existing root operation transaction |
| Rollback | subsequent failure rolls back the successful conditional mutation |
| No partial durability | stale graph/child mutations cannot leave prior graph steps committed |
| Deterministic success detector | adapter uses a proven native success mechanism |
| Unsupported detector | uncertain rowcount/RETURNING/runtime behavior fails closed |
| Version strategy | integer version-column path is the first portable target |
| Snapshot/no-op | only advertised where backend/runtime semantics are separately proven |
| Errors | stale state exposes neutral conflict semantics, not backend driver errors |

The capability does not require the same success detector across providers.

## Provider-native success detection

| Provider | Atomic success/stale detector |
| --- | --- |
| SQLAlchemy Core | sane UPDATE/DELETE rowcount |
| Tortoise | affected-row count from filtered queryset mutation |
| Piccolo | length of `RETURNING(identity)` result |
| Peewee | affected-row count from supported async DML line |

The design explicitly rejects a new shared rowcount abstraction. The conformance layer observes success/conflict behavior; adapters own how they obtain it.

## P1 — SQLAlchemy Core 3/5 -> 5/5

### Atomic optimistic

- add mapping-aware concurrency field access for Core row mappings;
- compile identity + provider predicate values into one UPDATE/DELETE;
- apply `next_values_for` in that mutation;
- require sane rowcount behavior and fail closed otherwise;
- do not rely on RETURNING as the concurrency decision if rowcount is the chosen contract;
- preserve the existing `AsyncConnection` / `SQLAlchemyCoreUnitOfWork` boundary.

### Relationships

- bind `RelationshipDefinition` to `Table`/FK/constraint metadata;
- unique compatible FK path may be inferred;
- zero path -> configuration error;
- multiple compatible paths -> explicit adapter-local physical binding required;
- implement FK, reverse FK, O2O uniqueness, M2M bridge, association resource, and ordering through Core SQL expressions;
- do not manufacture ORM mapped classes;
- do not infer Rakit destructive permission from SQLAlchemy schema cascade facts.

### Promotion gate

Promote Core to 5/5 only after source behavior, relationship graph rollback, concurrency conflict, ambiguity, and supported dialect/runtime proofs are green.

## P2 — Tortoise ORM 3/5 -> 5/5

### Atomic optimistic

- first target integer version-column strategy;
- use filtered `QuerySet.using_db(root_connection).update(...)` / delete;
- expected version participates in the mutation predicate;
- version advances in the same mutation, preferably database-side with `F`;
- affected-row behavior is proven for the claimed database matrix;
- snapshot/no-op mode remains disabled/fail-closed until independently proven.

### Relationships

- prefer public `Model.describe()` for new relationship introspection;
- named FK/backward FK/O2O/M2M relations bind explicitly by field/relation name;
- candidate resolution always uses the root UoW connection;
- native M2M helpers may be used only when root connection ownership is explicit and proven;
- association-object semantics require an explicit application-owned Tortoise model, not native table-oriented M2M `through` metadata;
- ordering requires an explicit position field;
- `on_delete` never grants Rakit destructive permission.

## P3 — Piccolo ORM 3/5 -> 5/5

### Atomic optimistic

- preserve the existing `UPDATE/DELETE ... RETURNING(identity)` execution style;
- add expected version/state predicates to the same mutation;
- `len(returned) == 1` means success; zero means stale/race; other counts fail closed;
- use integer version-column advancement first;
- explicitly require SQLite runtime support for RETURNING (SQLite >= 3.35), which is already an existing Piccolo write-path requirement;
- prove PostgreSQL and the selected Cockroach path rather than assuming PostgreSQL equivalence.

### Relationships

- use stable Piccolo table metadata for forward FK, reverse FK, and M2M relations;
- bind M2M to the resolved joining `Table`;
- prefer explicit joining-table reads/DML for neutral Rakit behavior;
- use joining tables as explicit association resources when they contain supported scalar identity and fields;
- ordering requires an explicit position field;
- upstream Cockroach M2M subquery caveat must be proven around using the explicit joining-table path or the affected shape/backend fails closed.

## P4 — Peewee Async ORM 3/5 -> 5/5

### Dependency decision

Parity implementation proposes tightening the optional Peewee line from:

```text
peewee>=4.0.2,<5
```

to:

```text
peewee>=4.0.8,<5
```

This change is part of the parity implementation decision, not an incidental dependency cleanup.

Reasons:

- 4.0.7 fixes asyncpg UPDATE/DELETE rowcount behavior required for stale-write proof;
- 4.0.8 is the first release declaring the asyncio API stable and exposes the maintained query-level async surface;
- a global provider capability must not silently mean different guarantees by database backend merely to retain 4.0.2.

### Atomic optimistic

- use one conditional Peewee UPDATE/DELETE executed through the supported async database/query path;
- integer version-column advancement in the same mutation is the first target;
- stale state is observed via affected rows;
- prove SQLite, PostgreSQL/asyncpg, and MySQL/aiomysql behavior at lowest accepted and latest 4.x;
- snapshot/no-op remains fail-closed until all claimed drivers prove compatible semantics.

### Relationships

- use documented `Model._meta`, `ForeignKeyField`, backrefs, uniqueness, and through/intermediary models;
- one-to-one requires proven unique FK semantics;
- prefer explicit async DML against through models for M2M mutation;
- rich association objects use explicit intermediary models with supported scalar identity;
- avoid accidental synchronous lazy relationship I/O outside the async bridge;
- use explicit joined/prefetched/async-query paths within the root UoW task;
- cascade metadata never grants destructive permission.

## P5 — Cross-provider closure

P5 begins only after P1-P4 have individually merged or have an explicitly documented honest lower capability ceiling.

Closure responsibilities:

1. run the canonical capability matrix for all shipped persistence providers;
2. update `docs/guides/persistence-adapters.md` and compatibility documentation;
3. update capability discovery output and permanent matrix expectations;
4. run lowest-direct and latest-allowed dependency jobs;
5. run Python 3.12, 3.13, and 3.14 coverage required by the project matrix;
6. run relevant provider backend/runtime jobs, including the explicit Peewee and Piccolo gates;
7. run simultaneous persistence extras/artifact smoke;
8. verify SQLAlchemy ORM reference behavior has no regression;
9. update this workstream's roadmap/research status without reopening D3;
10. run exact-head final CI and review before squash merge.

No release action is part of P5.

## Capability-promotion policy

Capability declarations are the final implementation step, not the first.

For each provider:

```text
research PASS
    != shipped capability

source behavior works
    != shipped capability

local tests green
    != shipped capability

required conformance + compatibility matrix green
    -> capability may be advertised
```

If a backend/runtime gate is conditional, the provider must either:

- prove the behavior for the entire advertised matrix; or
- explicitly narrow/fail closed on unsupported runtime/backend shapes.

Do not advertise a global capability whose truth depends on an undocumented backend accident.

## Shared-code extraction policy

The parity work should default to provider-local code.

A helper may move into `rakit-core` or `rakit-core.testing` only when all conditions hold:

1. at least two provider implementations have demonstrated materially identical neutral behavior;
2. the helper contains no backend types, query builders, rowcount rules, transaction implementation, or ORM metadata;
3. extraction reduces duplication without widening a public capability contract;
4. the helper can be explained entirely in Rakit-neutral terms;
5. existing SQLAlchemy ORM behavior remains unchanged.

This prevents speculative abstractions from being created before provider implementations reveal genuine commonality.

## Error and fail-closed policy

Common rules:

- initial scoped absence -> neutral not-found;
- stale/invalid concurrency state -> `RESOURCE_CONFLICT` / HTTP 409;
- incompatible relationship declaration -> configuration/compile failure;
- ambiguous native relationship path -> fail closed;
- unsupported resource identity -> fail closed;
- unsafe/unproven runtime success detector -> fail closed;
- backend cascade configuration never grants destructive authorization;
- no adapter may silently fall back from atomic compare-and-write to read-check-unconditional-write.

## CI and verification policy

The implementation follows the project's established source-first workflow:

1. source feature implementation;
2. static/non-test verification and manual/plain-Python smoke where useful;
3. real provider/runtime smoke;
4. permanent regression and conformance coverage;
5. lint/format/type checks;
6. dependency lowest/latest and backend/runtime matrix;
7. capability-profile assertions;
8. full CI/artifact verification;
9. exact-head final CI;
10. review, then squash merge.

Provider-specific CI additions must be proportionate to the capability guarantee being advertised. Do not create broad expensive database matrices unrelated to a claimed behavior.

## Branch and PR decomposition

Recommended implementation decomposition:

- one integration branch for the parity workstream;
- one independently reviewable provider PR/sub-branch for P1-P4;
- one closure PR for P5;
- squash merge each provider PR;
- rebase/refresh subsequent provider work from canonical `main` after each merge where practical.

The current research branch remains documentation/research input. Runtime implementation should begin from the canonical `main` state after the implementation plan is approved rather than treating the research branch as a long-lived runtime integration branch.

## Relationship to Plan 03

This work precedes the user's intended return to Plan 03, but does not alter Plan 03 scope.

The parity track helps Plan 03 by proving which persistence behaviors are truly neutral. When authentication/security work resumes:

- neutral auth/security contracts may depend on neutral Rakit persistence semantics where appropriate;
- SQLAlchemy-backed auth/session implementations remain SQLAlchemy package concerns;
- no conclusion here requires Tortoise, Peewee, Piccolo, or Core to become auth storage providers;
- authentication-provider parity, if ever desired, requires a separate design/research pass.

## Acceptance criteria

This design is satisfied when:

1. P1-P4 are implemented provider-first in the locked order unless implementation evidence explicitly justifies stopping/reordering.
2. Every new atomic mutation uses one native conditional database mutation and the existing root UoW.
3. Every relationship capability validates native structure and obeys Rakit scope, authorization, ordering, association, and destructive-policy semantics.
4. Ambiguous or unsupported shapes fail closed.
5. No universal persistence DSL, rowcount layer, or fake ORM is introduced.
6. Shared conformance tests describe behavior, not backend mechanics.
7. SQLAlchemy ORM remains unchanged as default/reference behavior.
8. Peewee parity uses an explicitly approved and verified dependency floor suitable for global atomic semantics.
9. Piccolo RETURNING and Cockroach M2M constraints are explicitly tested or fail closed.
10. Capability declarations are updated only after permanent conformance and compatibility proof.
11. D3 remains Complete; parity is recorded as additive work rather than rewriting completed history.
12. No release/tag/publication occurs without separate maintainer approval.

## Locked decisions

- **PARITY-D1:** Provider-first implementation is the chosen delivery strategy.
- **PARITY-D2:** Locked provider order is SQLAlchemy Core -> Tortoise -> Piccolo -> Peewee -> closure.
- **PARITY-D3:** Within each provider, atomic optimistic source work precedes relationship source work, then permanent conformance, then capability promotion.
- **PARITY-D4:** SQLAlchemy ORM is reference behavior, not a code template.
- **PARITY-D5:** Existing Rakit relationship/concurrency/UoW contracts are sufficient; no shared core redesign is planned.
- **PARITY-D6:** Shared conformance describes neutral observable semantics; success detection remains provider-native.
- **PARITY-D7:** Version-column concurrency is the common first implementation target; snapshot/no-op support is optional and evidence-gated.
- **PARITY-D8:** Association objects remain explicit resources; ORM M2M shortcuts never erase association scalar, identity, ordering, policy, or concurrency semantics.
- **PARITY-D9:** Writable ordering always requires an explicit position field.
- **PARITY-D10:** Database/ORM cascades never grant Rakit destructive permission.
- **PARITY-D11:** Ambiguity and unsupported native shapes fail closed.
- **PARITY-D12:** Peewee parity proposes `peewee>=4.0.8,<5` and must verify that compatibility decision explicitly.
- **PARITY-D13:** Piccolo parity uses RETURNING-based success detection and carries explicit SQLite/Cockroach gates.
- **PARITY-D14:** D3 remains Complete; this is an additive workstream.
- **PARITY-D15:** Plan 03 auth-provider parity is out of scope.
- **PARITY-D16:** No release, tag, or package publication is part of this workstream.
