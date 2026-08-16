# Rakit Post-Plan-05 Adapter Capability and Generated CRUD API Foundation Plan

**Status:** Approved bridge-roadmap baseline derived from the Rakit 2 design discussion  
**Date:** 2026-08-16  
**Placement:** After original Plan 05 and before original Plan 06  
**Numbering policy:** Keep the original July Plan 00–07 documents unchanged. This document uses **Plan 05A / 05B / 05C** as bridge labels so the existing Plan 06 and Plan 07 do not need to be renumbered retroactively.

> **For future agentic implementation:** convert each bridge slice into its own detailed implementation plan before coding. Do not implement all three slices as one giant change.

## Goal

Make Rakit genuinely capability-based and framework-agnostic before generated CRUD APIs become a first-class product surface.

The bridge has three ordered outcomes:

1. **Plan 05A — Adapter Architecture & Capability Contracts**
2. **Plan 05B — Generated CRUD API Foundation**
3. **Plan 05C — First Generated REST Implementation**

Only after those reviewed slices should development return to the original Plan 06 (dashboard/storage/accessibility) and Plan 07 (hardening/docs/release), unless maintainers explicitly reprioritize.

## Why this bridge exists

The July design already locks several principles:

- core definitions are framework-agnostic;
- one operation model is shared by CRUD, actions, pages, endpoints, relationships, and future generated APIs;
- portability is capability-aware rather than based on pretending all backends behave the same;
- Pydantic and SQLAlchemy are initial official implementations, not permanent universal abstractions;
- generated REST and GraphQL must reuse ResourceService, authorization, query, mutation, event, transaction, concurrency, and idempotency foundations.

The Rakit 2 discussion makes the next step more explicit:

- web frameworks should eventually have native adapters where useful;
- validation/schema engines should be replaceable;
- persistence libraries should advertise truthful capabilities;
- unsupported capability combinations must fail during compilation instead of silently degrading;
- generated CRUD API must be a surface over Rakit’s existing operation/resource foundations, not a separate CRUD engine;
- installation should later support composable extras such as `rakit[fastapi,sqlalchemy]`;
- project initialization may later offer a Vite-like interactive setup for new and existing projects.

## Non-negotiable architecture

```text
                         RAKIT CORE
 ┌──────────────────────────────────────────────────────────────┐
 │ Stable definitions / ResourceQuery / Fields / Relationships │
 │ OperationPlan / OperationContext                            │
 │ Authorization / UoW / Events / Concurrency / Idempotency   │
 │ Deadlines / Cancellation / Normalized Errors                │
 └──────────────────────────────────────────────────────────────┘
             │                    │                    │
      capability seam      capability seam      capability seam
             │                    │                    │
      Web Runtime           Schema/Validation      Persistence
       Adapters                Adapters              Adapters
             │                    │                    │
      Starlette first       Pydantic first       SQLAlchemy first
      FastAPI later         msgspec later        SQLAlchemy Core later
      Litestar later        dataclass later      Tortoise later
      Sanic later                                Peewee later
      Flask later                                others later
             │
             ▼
 ┌──────────────────────────────────────────────────────────────┐
 │ Product surfaces                                            │
 │ Admin UI / relationships / actions / pages / endpoints      │
 │ Generated REST API                                          │
 │ Future GraphQL                                              │
 └──────────────────────────────────────────────────────────────┘
```

The arrows point inward: product surfaces depend on Rakit contracts; Rakit core never imports a concrete web framework/ORM/schema engine.

---

# Plan 05A — Adapter Architecture & Capability Contracts

## Goal

Introduce one truthful, typed capability negotiation system that the compiler can use to determine whether an installed combination can satisfy the guarantees requested by compiled Rakit definitions.

This is an architectural migration of the current official stack, not a mass implementation of every future adapter.

## Scope

Plan 05A must make the existing official Starlette + Pydantic + SQLAlchemy stack implement the new contracts while preserving existing behavior and public APIs.

It does **not** implement FastAPI/Litestar/Sanic/Flask/Tortoise/Peewee/msgspec support yet.

Those become straightforward adapter projects after the contract exists.

## Capability principles

Capabilities are semantic guarantees, not brand names.

Bad:

```python
if adapter.name == "sqlalchemy":
    enable_best_effort_bulk()
```

Good:

```python
if persistence.capabilities.savepoints:
    enable_best_effort_bulk()
else:
    fail_compile(...)
```

A capability declaration must be immutable, typed, inspectable, and safe to include in `rakit check` diagnostics.

No silent fallback is allowed when a requested guarantee is absent.

## Adapter families

### A. Web runtime adapter

The web contract should describe what the runtime can actually guarantee, such as:

- route registration;
- stable route names;
- mount/root-path awareness;
- request metadata access;
- cookie/header/form/JSON parsing primitives;
- response translation;
- streaming response support;
- ASGI lifespan integration;
- client-disconnect/cancellation signal support where reliable;
- framework-native dependency bridge where intentionally supported;
- OpenAPI contribution capability only when a later generated-API plan needs it.

Starlette is the first implementation.

FastAPI should later be able to provide native integration without changing Rakit core definitions.

### B. Schema / validation adapter

The schema contract should expose the semantics Rakit needs, not Pydantic-specific APIs:

- validate Python/input mapping;
- serialize output;
- describe declared field names;
- detect required/nullable fields;
- reject/identify unknown fields;
- normalize validation issues into Rakit’s stable issue model;
- optionally expose schema metadata needed by generated APIs.

Pydantic v2 is the reference implementation.

Future implementations may include msgspec and dataclass-oriented adapters.

Do not erase backend-specific features; expose optional capabilities when semantics differ.

### C. Persistence / data adapter

Build on the existing `DataSource` and operation/UoW work rather than inventing a universal ORM.

Capability vocabulary should be rich enough to describe proven guarantees such as:

- read/list/detail;
- create/update/delete;
- filtering/search/sorting;
- exact/deferred/disabled counts;
- offset pagination;
- transactions;
- read-only transactions;
- savepoints;
- operation-owned UoW participation;
- optimistic concurrency;
- atomic concurrency predicate updates;
- relationship inspection;
- relationship mutation kinds;
- association tables;
- association objects;
- ordered relationships;
- bulk atomic execution;
- best-effort bulk/savepoint support;
- statement timeout/cancellation where applicable;
- streaming/lazy data safety if ever exposed.

SQLAlchemy ORM is the first full implementation.

SQLAlchemy Core should be treated as a separate adapter profile if its semantics differ materially.

Tortoise, Peewee, Masonite ORM, and others are future implementations, not conditionals embedded in core.

## Task sequence for Plan 05A

### 05A.1 — Audit concrete coupling

Produce an inventory of places where Rakit core/web currently checks or assumes concrete Pydantic/Starlette/SQLAlchemy behavior.

Classify every finding as:

- intentional official implementation detail;
- capability that belongs in a contract;
- public API compatibility surface;
- internal coupling that should be migrated.

Do not refactor unrelated code.

### 05A.2 — Define capability vocabulary

Create backend-neutral frozen capability contracts in core.

Avoid a single giant `Capabilities` bag.

Prefer focused profiles, for example:

```text
WebRuntimeCapabilities
SchemaCapabilities
DataSourceCapabilities / PersistenceCapabilities
TransactionCapabilities
RelationshipCapabilities
```

Reuse/extend existing `DataSourceCapabilities` when that preserves compatibility.

Capability composition must be explicit.

### 05A.3 — Add schema adapter seam

Create a small core protocol and a Pydantic reference implementation.

Migrate only the Rakit-owned validation/serialization call sites needed to prove the boundary.

Existing user-facing Pydantic support remains first-class and backward compatible.

Do not add msgspec merely to prove extensibility; use a tiny fake adapter contract test instead.

### 05A.4 — Add web runtime seam

Extract the semantic runtime contract from the current Starlette implementation.

Keep Starlette as the official first adapter.

The migration must not cause `rakit-core` to import Starlette.

Do not implement native FastAPI yet.

A fake runtime adapter should be sufficient to prove compiler/runtime separation in contract tests.

### 05A.5 — Strengthen persistence capability reporting

Make SQLAlchemy report the exact guarantees it currently provides.

Replace backend-name or attribute-guessing checks with capability checks where the semantics are already stable.

Critical compile-time examples:

- BEST_EFFORT bulk requires savepoints;
- strong concurrency requires atomic UoW concurrency;
- relationship edit mode requires the corresponding relationship capability;
- generated write API later requires create/update/delete + transaction guarantees.

### 05A.6 — Capability negotiation in compiler

Compilation must calculate required capabilities from declarations and compare them with installed adapter capabilities.

Failures must contain:

- requested feature/primitive;
- required capability;
- selected adapter/provider;
- safe reason;
- actionable installation/configuration hint where possible.

Example:

```text
config.capability_missing
Resource "orders" action "bulk_archive" requires SAVEPOINTS for
BEST_EFFORT execution, but persistence adapter "tortoise" does not
declare that capability.
```

No runtime surprise for a combination the compiler could reject.

### 05A.7 — `rakit check` diagnostics

`rakit check` should report enough adapter/capability information for a user to understand the compiled combination without dumping secrets or internal objects.

Potential output:

```text
Web runtime: starlette
Schema: pydantic-v2
Persistence[primary]: sqlalchemy-orm

Required capabilities: satisfied
```

Detailed machine-readable diagnostics can be added later; keep the initial CLI readable.

### 05A.8 — Reusable adapter contract tests

Add capability-aware contract suites before third-party adapters are encouraged.

The suite should test that an adapter that claims capability X actually meets X’s behavioral contract.

A fake adapter that lies about a capability must fail the suite.

This becomes the foundation for later FastAPI, msgspec, Tortoise, Peewee, and other adapter packages.

## Plan 05A completion gate

Plan 05A is complete when:

- the current official stack passes the entire pre-existing suite;
- no public behavior regresses;
- capability requirements are compiler-visible;
- unsupported combinations fail closed;
- Starlette/Pydantic/SQLAlchemy are first implementations, not hard-coded identities in core semantics;
- fake adapters can prove the web/schema/persistence seams without importing official implementations;
- `rakit check` can identify selected adapters and missing capabilities;
- package layering remains acyclic;
- full Ruff/ty/pytest/build gates pass.

---

# Plan 05B — Generated CRUD API Foundation

## Goal

Create a transport-neutral generated resource API model that compiles from existing Rakit resources and reuses existing query/write/authorization/operation foundations.

Plan 05B is **not** the first HTTP REST implementation yet.

It defines the contracts that Plan 05C will translate to HTTP.

## Core rule

Generated API CRUD is not a second CRUD engine.

```text
Generated API request
        │
        ▼
compiled Resource API definition
        │
        ├── ResourceQuery / ResourceService for reads
        └── existing mutation/operation pipeline for writes
                  │
                  ├── authorization
                  ├── UoW/transaction
                  ├── events
                  ├── concurrency
                  ├── idempotency
                  ├── deadline/cancellation
                  └── normalized errors
```

`AdminEndpoint` remains a custom application endpoint and must not be repurposed as generated resource REST.

## Proposed foundation contracts

Exact naming should be finalized during the 05B design review, but the model should cover concepts equivalent to:

```text
GeneratedApiDefinition
ResourceApiDefinition
ResourceApiOperation
ResourceApiQueryContract
ResourceApiInputContract
ResourceApiOutputContract
ResourceApiResult
```

Operations are compiler-derived from resource capabilities and explicit developer policy.

A resource that cannot satisfy a requested write guarantee must fail compilation.

## 05B task sequence

### 05B.1 — Define explicit API exposure policy

A resource must not become remotely writable merely because it is registered in Admin UI.

Generated API exposure is explicit.

Example direction:

```python
class UserAdmin(ModelAdmin):
    api = ResourceApi(
        list=True,
        detail=True,
        create=True,
        update=True,
        delete=False,
    )
```

The exact public syntax is provisional until the design review.

### 05B.2 — Compile resource API operations

For each exposed operation, derive:

- stable operation ID;
- stable route identity independent of one web framework;
- required permission;
- schema input/output role;
- query contract;
- mutation/transaction contract;
- concurrency/idempotency requirements;
- capability requirements.

### 05B.3 — Reuse `ResourceQuery` for collection reads

Generated list API must reuse:

- filter whitelist;
- search whitelist;
- sort whitelist;
- stable identity tie-breaker;
- pagination;
- count policy;
- scoped base query / visibility.

Do not create an API-only query parser with different semantics.

HTTP parameter syntax belongs in Plan 05C’s web adapter, not core.

### 05B.4 — Reuse canonical detail/scoped identity behavior

Generated detail must use `RecordIdentity`/`IdentityCodec` semantics and the same scoped resource service.

No unscoped ORM lookup.

### 05B.5 — Reuse write operation foundation

Generated create/update/delete translate into the same durable operation foundations already used by the admin write pipeline.

A generated API adapter may have different HTTP representation, but it must not get a separate commit/rollback/event path.

### 05B.6 — Authorization model

Generated resource API permissions derive from stable resource IDs and operations.

Operation permission and record visibility remain separate boundaries.

Explicit API authentication mechanisms beyond browser session auth (API keys, bearer tokens, JWT/PASETO) remain a later auth-provider concern.

Do not hard-code machine auth into CRUD compilation.

### 05B.7 — Concurrency and idempotency contract

The foundation must expose enough semantic metadata for an HTTP adapter to implement:

- conflict detection;
- safe retry/idempotency;
- conditional mutation semantics later.

Do not prematurely lock HTTP `ETag`/`If-Match` wire format into core if it belongs to the REST adapter.

### 05B.8 — Transport-neutral result/error model

Generated API uses Rakit’s normalized errors and typed results.

HTTP status mapping is a web-adapter responsibility.

GraphQL can later reuse the same operation foundation without pretending GraphQL is REST.

### 05B.9 — Capability gate

Compilation must reject exposing operations the selected adapters cannot guarantee.

Examples:

```text
create requested but persistence create=False
delete requested but delete=False
strong concurrency requested but atomic_concurrency=False
query operator requested but filter capability missing
```

No generated stub route that fails only when called.

## Plan 05B completion gate

Plan 05B is complete when:

- a resource can compile a transport-neutral generated CRUD definition;
- reads reuse ResourceService/ResourceQuery;
- writes reuse the canonical operation/mutation foundation;
- permissions are stable and explicit;
- capability gaps fail at compile time;
- no Starlette/FastAPI imports exist in generated API core contracts;
- no OpenAPI/Swagger is required to prove the foundation;
- fake adapters can compile supported operations and reject unsupported ones.

---

# Plan 05C — First Generated REST Implementation

## Goal

Translate Plan 05B’s generated resource API model into the first official HTTP REST surface using the existing official stack.

This slice proves the architecture before multiple native web adapters are added.

## Reference stack

Initial reference implementation:

```text
Web runtime: Starlette adapter
Schema: Pydantic v2 adapter
Persistence: SQLAlchemy ORM adapter
```

The core generated API model must not mention those names.

## Initial REST surface

The exact method semantics require their own design review before implementation, but the expected resource surface is:

```text
GET     /api/<resource>
GET     /api/<resource>/<identity>
POST    /api/<resource>
PATCH   /api/<resource>/<identity>
DELETE  /api/<resource>/<identity>
```

PUT may be added only after replacement semantics are explicitly defined.

Route prefix is configurable and collision-checked.

## REST responsibilities

Plan 05C owns:

- HTTP query parameter translation → `ResourceQuery`;
- request body parsing through the selected schema adapter;
- response serialization through the schema adapter;
- JSON error envelope/status mapping;
- authentication integration;
- permission enforcement;
- idempotency transport;
- concurrency/conditional request transport;
- safe pagination metadata;
- content-type behavior;
- cache policy;
- stable route names.

It still does **not** own persistence logic.

## OpenAPI sequencing

Do not make generated CRUD correctness depend on OpenAPI.

After method/input/output semantics stabilize:

1. expose a framework-neutral API description from compiled definitions;
2. let capable web adapters publish OpenAPI;
3. FastAPI may later integrate natively with its schema machinery;
4. Swagger/ReDoc access remains authenticated/configurable per roadmap.

This avoids coupling CRUD execution to one documentation generator.

## Native adapter expansion after 05C

After the reference generated API works and contract suites are stable, add adapters one at a time.

Suggested validation order, not a commitment:

```text
FastAPI
Litestar
Sanic
Flask integration/native bridge
```

Persistence candidates can similarly be added independently:

```text
SQLAlchemy Core
Tortoise ORM
Peewee
Masonite ORM
```

Schema candidates:

```text
msgspec
dataclass-oriented adapter
```

Each adapter implements only truthful capabilities.

A user can replace one adapter without changing unrelated Rakit declarations where their requested capability set remains satisfied.

---

# Packaging and DX direction

The capability architecture should make composable installation possible later:

```bash
uv add "rakit[fastapi,sqlalchemy]"
```

or:

```bash
pip install "rakit[fastapi,sqlalchemy]"
```

Do not add extras until corresponding official packages/integrations genuinely exist.

A later scaffolding/DX plan may add:

```bash
rakit init
```

with Vite-like interaction for:

- new project;
- add Rakit to existing project;
- choose web framework;
- choose persistence adapter;
- choose validation engine;
- choose auth/storage options;
- produce only explicit installed plugin configuration.

The CLI must never silently activate arbitrary installed plugins.

This scaffolding work is **not** part of Plan 05A/05B unless required to prove an adapter contract.

---

# Relationship to original July plans

The original documents remain historical implementation plans.

Execution order after this roadmap revision:

```text
Plan 00  Foundation / Workspace                         DONE
Plan 01  Runtime / Compiler / Lifecycle                 DONE
Plan 02  Read-only Resources / UI                       DONE
Plan 03  Authentication / Authorization / Security      DONE
Plan 04  Forms / Write Pipeline                         DONE
Plan 05  Relationships / Actions / Pages / Endpoints    IN PROGRESS
  └─ Task 7 Typed Custom Endpoints                      NEXT/CURRENT
  └─ Plan 05 completion integration gate                AFTER TASK 7

Plan 05A Adapter Architecture & Capability Contracts    NEXT BRIDGE
Plan 05B Generated CRUD API Foundation                  AFTER 05A
Plan 05C First Generated REST Implementation            AFTER 05B

Original Plan 06 Dashboard / Storage / Accessibility    AFTER BRIDGE
Original Plan 07 Hardening / Docs / Alpha Release       AFTER PLAN 06
```

This ordering can be revisited after Plan 05A if the bridge reveals that 05C should ship after the alpha instead. The architecture work and 05B foundation remain valuable either way.

---

# Global guardrails for all bridge plans

- No universal ORM.
- No universal migration language.
- No silent capability fallback.
- No adapter activation merely because a package is installed.
- No global service locator.
- No second transaction engine for generated APIs.
- No second authorization model for generated APIs.
- No second event pipeline for generated APIs.
- No second concurrency/idempotency implementation for generated APIs.
- No Pydantic types leaking into framework-neutral core contracts where the schema adapter should own them.
- No Starlette/FastAPI types in `rakit-core`.
- No SQLAlchemy types in `rakit-core`.
- Backend-specific features remain visible instead of being inaccurately normalized.
- Existing public imports remain compatible unless an explicit reviewed migration is approved.
- Security-affecting defaults require positive and negative tests.

## Bridge completion definition

The bridge as a whole is successful when:

1. a Rakit application can truthfully describe its web/schema/persistence capability combination;
2. the compiler rejects unsupported feature combinations early;
3. the current Starlette/Pydantic/SQLAlchemy stack retains all existing behavior;
4. generated CRUD definitions can compile without importing a web framework;
5. generated REST executes through the same ResourceService/OperationPlan/UoW/security foundation as Admin UI operations;
6. adding a later FastAPI, msgspec, Tortoise, or Peewee adapter does not require rewriting generated CRUD core semantics;
7. contract tests can detect adapters that falsely claim capabilities;
8. the original Plan 06/07 can continue on top of the stronger architecture.
