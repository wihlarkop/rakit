# Rakit Roadmap

This document is the canonical public roadmap for Rakit.

The roadmap describes product direction and engineering priorities rather than release dates. Items may move when implementation experience reveals better abstractions or sharper boundaries.

Rakit remains under active pre-release development. The current package version target is `0.1.0a1`, but publication is intentionally deferred until the maintainer explicitly decides that the framework is ready.

## Status legend

- **Complete** — implementation and verification are complete; for integration work this status becomes canonical when the owning PR lands on `main`.
- **Next** — next major workstream expected to receive active implementation.
- **Planned** — accepted direction, but not necessarily fully designed yet.
- **Research** — exploratory work that may change shape substantially.
- **Not currently planned** — intentionally outside the current product focus.

## Current position

| Area | Status |
| --- | --- |
| Plans 00–07 foundation | **Complete** |
| Phase A UI/UX, UI-01–UI-08 | **Complete** |
| Phase B1 alpha readiness audit | **Complete** |
| Phase B2 alpha/core hardening | **Complete** |
| Phase B2.7 stale-branch retirement | **Complete** |
| Phase B3 realistic reference application | **Complete** |
| Phase B4 API/DX refinement from reference application | **Complete** |
| **Phase B overall** | **Complete** |
| Phase C1 friendly CRUD and lifecycle APIs | **Complete** |
| Phase C2 project initialization and scaffolding | **Complete** |
| Phase C3 installation and extras UX | **Complete** |
| Phase C4 capability discovery | **Complete** |
| **Phase C overall** | **Complete** |
| Phase D1 adapter contract hardening | **Complete** |
| Phase D2 schema adapter ecosystem | **Complete** |
| Phase D3 persistence adapter ecosystem | **Next** |
| Phase D adapter ecosystem | **Next** |
| Phase E generated APIs v1 | **Planned; foundation exists** |
| Public release | **Deferred until explicit maintainer approval** |

## Completed foundation

### Plan 00 — Foundation workspace

- uv multi-package workspace.
- Python 3.12+ baseline.
- package boundaries and dependency direction.
- typed package foundations and `py.typed`.
- repository quality tooling.

### Plan 01 — Runtime, compiler, and lifecycle

- framework-neutral runtime contracts.
- compilation and registration foundations.
- dependency injection.
- application lifecycle and shutdown behavior.
- operation semantics.

### Plan 02 — Read-only resources and web UI

- `ResourceAdmin` and resource registration.
- read-only resource pages.
- Starlette-based standalone and mountable ASGI runtime.
- bundled templates, assets, and HTMX progressive enhancement.

### Plan 03 — Authentication, authorization, and security

- secure server-side sessions.
- built-in SQLAlchemy authentication.
- allow-only RBAC.
- CSRF and origin validation.
- trusted host/proxy handling.
- CSP and security headers.
- production safety checks.
- purpose-separated cryptographic key management.

### Plan 04 — Forms and write pipeline

- Pydantic v2 validation integration.
- form engine.
- create/update/delete flows.
- explicit transaction policies.
- optimistic concurrency.
- duplicate-submission protection.
- typed transactional events.

### Plan 05 — Relationships, actions, pages, and endpoints

- relationship introspection and mutation.
- custom actions.
- bulk actions.
- custom pages.
- custom JSON endpoints.
- operation-scoped authorization and transaction behavior.

### Plan 06 — Dashboard, storage, and accessibility

- dashboard foundations.
- basic widgets.
- storage contracts.
- local private file storage.
- upload validation.
- accessibility foundations.
- structured logging.
- health/readiness handling.

### Plan 07 — Hardening, examples, docs, packaging, and governance

- Python 3.12 / 3.13 / 3.14 CI matrix.
- lowest-direct and latest dependency compatibility matrices.
- strict Ruff formatting/linting and `ty` type checking.
- repository-wide pytest coverage gate.
- strict MkDocs build.
- wheel and sdist validation for official distributions.
- clean-installed artifact smoke testing outside the repository checkout.
- compatibility and governance documentation.
- tag-gated release workflow.

Completion of Plan 07 does not imply package publication.

## Phase A — UI/UX maturity

**Status: Complete**

Phase A upgraded Rakit from a functional administration surface into a cohesive product UI while preserving SSR and progressive enhancement.

### UI-01 — Showcase baseline

- representative UI showcase.
- shared visual baseline for subsequent UI work.

### UI-02 — Responsive shell and navigation

- responsive application shell.
- navigation behavior across screen sizes.
- sidebar behavior and persistence contracts.

### UI-03 — Design foundation, icons, and theme

- design tokens and visual foundation.
- icon system.
- light, dark, and system themes.
- bundled Tailwind build.

### UI-04 — Core components

- reusable UI primitives.
- dialogs, feedback states, controls, and component-level presentation contracts.

### UI-05 — Resource experience

- mature resource list/detail/form experiences.
- filter presentation.
- query UI.
- pagination presentation.
- resource actions and state feedback.

### UI-06 — Advanced operations

- advanced actions.
- bulk operations.
- relationships and uploads.
- authentication/system surfaces.
- custom pages and feedback states.

### UI-07 — Responsive/accessibility hardening and advanced widgets

- keyboard and focus contracts.
- motion and contrast contracts.
- responsive hardening.
- advanced widget foundations.

### UI-08 — Final Phase A polish

- final visual and interaction polish.
- Phase A acceptance and integration cleanup.

## Phase B — Alpha hardening and real-world validation

**Status: Complete**

Phase B validated that Rakit works as a coherent framework rather than only as individually complete subsystems. Public release remains a separate maintainer decision and is still deferred.

### B1 — Alpha readiness audit

**Status: Complete**

- reconstructed alpha acceptance criteria.
- audited the framework against the original pre-release definition of done.
- identified remaining hardening work without triggering a release.

### B2 — Alpha/core hardening

**Status: Complete**

Completed work includes:

- public facade normalization while preserving physical distribution boundaries.
- `rakit.server.granian` facade.
- neutral `rakit.storage` facade.
- `rakit.storage.local` facade.
- preferred server extras `rakit[uvicorn]` and `rakit[granian]`.
- explicit facade dependency ownership.
- runtime web asset completeness checks.
- generated Tailwind CSS reproducibility gate.
- clean-installed optional Granian smoke coverage.
- semantic stdlib `HTTPStatus` usage for HTTP-facing status codes without changing wire behavior.
- documented and regression-tested `rakit_` namespace invariant for Rakit-owned persistence.
- dedicated Rakit-owned Alembic version-table naming.
- refreshed architecture, install, migration, and `Unreleased` documentation.

### B2.7 — Retire superseded stale branches

**Status: Complete**

The superseded roadmap-only branches were retired after B2 absorbed their useful intent:

- `chore/httpstatus-roadmap-todo`.
- `chore/rakit-table-prefix-roadmap-todo`.

No stale implementation was merged or rebased.

### B3 — Realistic reference application

**Status: Complete**

`examples/reference_app` is a realistic commerce/backoffice application composed through public Rakit APIs. It exercises:

- application-owned async SQLAlchemy persistence on SQLite.
- built-in SQLAlchemy authentication, sessions, users, roles, and allow-only RBAC.
- customers, products, orders, and order-item domain models.
- optimistic CRUD forms for mutable resources.
- private image upload/storage using the local storage adapter and portable `StoredFile` descriptors.
- resource filters, search, sorting, and generated REST reads.
- relationship metadata.
- record and bulk actions with explicit application-owned transaction boundaries.
- an application-owned custom page.
- eager and lazy dashboard widgets plus launchers.
- startup bootstrap, database readiness, and shutdown cleanup.
- isolated subprocess smoke coverage that creates a fresh database, compiles the app, seeds auth/domain data, and proves readiness.

The example deliberately keeps application models, driver choice, migrations/bootstrap policy, and domain transitions outside Rakit core.

### B4 — API and DX refinement from the reference application

**Status: Complete**

The reference application exposed concrete public-API friction. Phase B fixed those points without introducing a speculative abstraction layer:

- `rakit.auth.sqlalchemy` exposes operational auth primitives needed to bootstrap schema, users, roles, permissions, password hashing, permission synchronization, and durable idempotency.
- `Admin.register_write(...)` enables ordinary write forms without forcing applications to construct transport-level `WriteResourceBinding` objects or duplicate CSRF/auth/template plumbing.
- lifecycle startup callbacks provide a fail-fast initialization seam before the runtime enters `READY`.
- the root `rakit` facade exposes domain-action composition contracts needed for typed actions without internal imports.
- reference-app documentation makes persistence, transaction, storage-descriptor, and application/framework ownership boundaries explicit.

### Phase B completion gate

Phase B was closed only after the realistic reference application passed the same repository-wide quality gates as the framework.

The reference app also exposed a real SQLAlchemy async bootstrap bug: a pending role could be autoflushed before relationship assignment, which then caused an implicit async lazy-load and `MissingGreenlet`. The bootstrap flow now resolves permissions first and creates a new role with populated relationships before it is added to the session; existing roles continue to use explicit eager loading.

Final Phase B verification includes:

- Python 3.12, 3.13, and 3.14 matrices.
- Ruff formatting and linting.
- `ty` type checking.
- full pytest suite: **1913 passed**.
- lowest-direct dependency compatibility.
- latest allowed dependency compatibility.
- coverage gate.
- strict MkDocs build.
- clean-installed artifact checks.
- official distribution artifact dry-run.
- generated web/CSS reproducibility.

No release, tag, version bump, TestPyPI upload, or PyPI publication is implied by Phase B completion.

## Phase C — Developer experience and lifecycle ergonomics

**Status: Complete**

### C1 — Friendly CRUD and lifecycle APIs

**Status: Complete**

C1 used the realistic reference application to remove repeated composition work without making resource writes implicit or adapter-specific:

- `ResourceWriteDefinition` lets a `ModelAdmin` opt into ordinary CRUD next to its read/query policy while keeping explicit form and writable-field allowlists.
- model adapters may expose a neutral `ResourceWriteServiceProvider`; SQLAlchemy supplies the first implementation and derives model identity without moving ORM concerns into `rakit-core`.
- `Admin.register(...)` materializes declared writes through the selected adapter and reuses the existing secure `Admin.register_write(...)` pipeline rather than creating a second mutation transport.
- read-only resources remain read-only by default, and missing/incomplete write-provider capability fails closed before mutation bindings are installed.
- existing manual `Admin.register_write(...)` and `Admin.register_write_resource(...)` paths remain available for advanced composition.
- `Admin.on_startup(...)`, `Admin.on_shutdown(...)`, and `Admin.add_health_check(...)` provide a thin lifecycle facade while preserving existing startup, readiness, health-cache, and LIFO shutdown semantics.
- `examples/reference_app` now uses declarative writes for Product and Order plus the public lifecycle facade, removing duplicate mutation-service/token wiring while preserving explicit concurrency, permissions, forms, and storage behavior.

C1 closed only after Ruff formatting/linting, `ty`, pytest on Python 3.12/3.13/3.14, lowest-direct/latest dependency matrices, coverage, strict MkDocs, artifact validation, and generated web-asset reproducibility all passed on the integration head.

### C2 — Project initialization and scaffolding

**Status: Complete**

C2 adds a Vite-like but fail-closed `rakit init` workflow to the existing CLI:

- interactive project/template/server/install prompts plus deterministic flags for automation, including `--yes`, `--dry-run`, `--install/--no-install`, `--existing`, and `--package`.
- `standard` and `minimal` starter profiles with explicit Uvicorn or Granian selection.
- new-project generation with canonical `src/` layout, `pyproject.toml`, README, `.python-version`, and safe starter-owned runtime files.
- the standard starter composes SQLAlchemy persistence, SQLAlchemy auth/idempotency, local storage, declarative `ResourceWriteDefinition` CRUD, health checks, shutdown lifecycle, explicit development bootstrap, and process-environment secrets through current public APIs.
- the minimal starter remains intentionally lightweight and read-only.
- existing-project mode detects conventional `src/` or flat package layouts, creates an isolated additive Rakit module, never rewrites host entrypoints or arbitrary host source, and emits FastAPI/Starlette mount guidance when those hosts are detected.
- C2 v1 uses `uv` deliberately; dependency installation is preflighted before writes, while a dependency command failure after successful scaffold creation keeps the generated files and prints a retry path.
- dry-run performs no filesystem mutation or dependency subprocess.
- identical reruns are accepted, while changed generated files, unmanaged new-project content, symlink targets, ambiguous package placement, and other unsafe collisions fail closed before mutation.
- focused regression suites cover detection, planning, apply behavior, CLI behavior, and generated-project bootstrap/check flows.

C2 was verified source-first with a manual runner matrix covering dry-run, missing-`uv` preflight, standard/minimal generation, rerun/collision behavior, generated bootstrap, `rakit check`, permission synchronization, interactive prompts, additive FastAPI integration, and ambiguous-package handling. Regression verification then passed Ruff formatting/linting, `ty`, pytest on Python 3.12/3.13/3.14, lowest-direct/latest dependency matrices, coverage, strict MkDocs, artifact validation, and generated web-asset reproducibility.

### C3 — Installation and extras UX

**Status: Complete**

C3 makes optional capability installation explicit, deterministic, and consistent across
package metadata, runtime diagnostics, release verification, and `rakit init`:

- the public facade exposes exactly six canonical extras: `uvicorn`, `granian`,
  `sqlalchemy`, `auth-sqlalchemy`, `storage-local`, and `standard`.
- `standard` is intentionally server-neutral and database-driver-neutral; applications
  select Uvicorn or Granian and their database driver explicitly.
- the unpublished `server-uvicorn` alias was removed rather than carried as compatibility
  surface before the first public release.
- one typed internal install vocabulary produces deterministic Rakit requirement strings,
  `uv add` argv, and shell-facing guidance without duplicating raw extra names across the
  framework.
- missing top-level optional implementation packages now report the capability that is
  unavailable plus the exact `uv add` command needed to install it.
- transitive `ModuleNotFoundError` failures remain untouched so dependency bugs are not
  disguised as missing optional capabilities.
- C2 scaffold dependency selection uses the same vocabulary: minimal starters select only
  their server extra, while standard starters select `rakit[standard,<server>]` and keep
  `aiosqlite` as a separate application-owned dependency.
- clean-installed release verification now exercises `rakit[standard,uvicorn]` explicitly
  and continues to verify Granian independently.

C3 was verified source-first. A temporary non-pytest source smoke first proved canonical
metadata, install vocabulary, all scaffold combinations, optional diagnostics, transitive
failure preservation, and removal of the unpublished alias. Regression verification then
passed Ruff formatting/linting, `ty`, full pytest on Python 3.12/3.13/3.14, lowest-direct
and latest dependency matrices, coverage, strict MkDocs, artifact validation, artifact
dry-run, and generated web-asset reproducibility.

### C4 — Capability discovery

**Status: Complete**

C4 established first-party capability discovery as a stable diagnostic surface:

- canonical capability identifiers and provider metadata;
- installed integration inventory through `rakit.integrations` entry points;
- configured-versus-installed integration reporting;
- `rakit capabilities` human and JSON output;
- aggregate `rakit check` capability diagnostics;
- server, schema, persistence, authentication, and storage metadata;
- fail-closed duplicate integration identifiers and actionable configuration diagnostics.

C4 closed with canonical CI and became the discovery foundation used by Phase D adapter work.

## Phase D — Adapter ecosystem

**Status: Next**

Phase D proves that Rakit's capability architecture works across multiple concrete implementations. New adapters are added deliberately and must advertise only behavior they can prove against canonical contracts.

### D1 — Adapter Contract Hardening

**Status: Complete**

- versioned canonical capability contracts;
- hard prerequisite validation and fail-closed conformance;
- deterministic maintainer conformance matrix;
- behavioral proof coverage for first-party SQLAlchemy, Pydantic, and Starlette integrations;
- C4 compatibility gate for capability discovery metadata.

### D2 — Schema Adapter Ecosystem

**Status: Complete**

- extracted Pydantic ownership from `rakit-web` into `rakit-schema-pydantic`;
- added `rakit-schema-msgspec` as a peer first-party schema integration;
- retained Pydantic as the deterministic default experience without concrete schema coupling in `rakit-core` or `rakit-web`;
- added explicit runtime schema selection and actionable invalid-selection diagnostics;
- proved both Pydantic and msgspec against all four `schema.*@1` contracts;
- locked presence-aware partial-update semantics where missing differs from explicit `None`;
- added package/discovery metadata, install UX, artifact verification, and cross-adapter regression coverage.

### D3 — Persistence Adapter Ecosystem

**Status: Active**

D3 expands persistence from one reference ORM into a multi-adapter ecosystem while keeping `rakit-core` and `rakit-web` backend-neutral. SQLAlchemy ORM remains the default provider; every additional adapter advertises only capabilities proven against the canonical contracts.

#### D3.0 — Persistence Integration Contract & Adapter Subject Generalization

**Status: Complete**

- backend-neutral adapter subjects, including native non-class persistence objects;
- resource-owned, multi-provider operation UoW registration and deterministic selection;
- fail-closed ambiguity instead of install-order selection;
- shared persistence conformance seams that remain backend-neutral.

#### D3.1 — SQLAlchemy ORM Hardening + SQLAlchemy Core/Table

**Status: Complete**

Add native SQLAlchemy `Table` support in `rakit-sqlalchemy` through the distinct `persistence.sqlalchemy-core` provider while preserving the existing ORM provider.

#### D3.2 — Tortoise ORM

**Status: Active**

Complete the first-party Tortoise adapter, then add writes, root-UoW behavior, and higher capabilities only where public Tortoise APIs satisfy the canonical contracts cleanly.

#### D3.3 — Peewee 4 Async ORM

**Status: Planned**

Add a first-party `persistence.peewee` adapter using Peewee 4's official async execution layer and advertise only verified behavior.

#### D3.4 — Piccolo ORM

**Status: Planned**

Add a first-party `persistence.piccolo` adapter with conservative capability advertisement and public-API-only transaction/query integration.

#### D3.5 — Masonite ORM Feasibility / Adapter

**Status: Planned**

Evaluate the maintained Masonite ORM line against Rakit's async and root-UoW contracts. Ship `persistence.masonite` only if the feasibility gate passes without semantic distortion.

#### D3.6 — Persistence Integration DX, Compatibility Matrix & Closure

**Status: Planned**

Publish install/discovery guidance and the verified capability matrix, close D3 packaging/artifact consistency, then hand Phase D to D4.0 Web Integration Contract.

### D4 — Web Framework Integrations

**Status: Planned**

#### D4.0 — Web Integration Contract

Define the framework-integration boundary and acceptance matrix before adding more host frameworks.

#### D4.1 — Litestar

Add first-class Litestar integration against the D4.0 contract.

#### D4.2 — FastAPI

Promote FastAPI mounting/composition from guidance into a first-class integration where that adds real value beyond Starlette compatibility.

#### D4.3 — Starlette

Harden and document Starlette as the canonical ASGI/reference integration under the shared web contract.

#### D4.4 — Flask

Explore and implement an honest Flask integration without pretending WSGI and ASGI semantics are identical.

#### D4.5 — Sanic

Add Sanic integration if the D4 contract maps cleanly to its runtime model.

#### D4.6 — Integration DX & Compatibility Matrix

Unify install guidance, discovery, conformance, examples, and supported-version policy across first-party web integrations.

### D5 — Adapter Authoring DX / SDK

**Status: Planned**

Turn the internal conformance machinery proven by D1-D4 into a supported authoring experience for third-party adapter maintainers, without exposing unstable internals prematurely.

### D6 — Additional First-party Adapters

**Status: Planned**

Add further schema, persistence, storage, authentication, or transport adapters only where ecosystem demand and the capability model justify first-party ownership.

## Phase E — Generated APIs v1

**Status: Planned; foundation already exists**

Generated REST already contains substantial foundations: compilation contracts, read and mutation runtimes, SQLAlchemy execution, filters, pagination contracts, authorization integration, concurrency handling, idempotency, and structured HTTP errors.

### E1 — Complete and polish generated REST

- complete public REST surface.
- consistent resource route conventions.
- clarify supported mutation semantics.
- strengthen public documentation and examples.

### E2 — HTTP mutation semantics

- POST semantics.
- PATCH semantics.
- DELETE semantics.
- evaluate PUT only where true replacement semantics are meaningful.

### E3 — OpenAPI generation

- generated schemas.
- operation metadata.
- query/filter documentation.
- error contracts.
- authentication descriptions.

### E4 — API documentation UI

- Swagger UI.
- ReDoc or equivalent documentation surface.
- safe production defaults.

### E5 — Machine authentication

- API keys.
- token-based authentication.
- explicit scopes/permissions.
- rotation and revocation policies.

### E6 — Conditional requests and concurrency

- ETag behavior.
- `If-Match`.
- conditional reads/writes where appropriate.
- consistent optimistic concurrency contracts.

### E7–E10 — GraphQL after REST maturity

GraphQL should follow a mature REST surface rather than precede it.

Potential scope:

- generated types, queries, and mutations.
- relationships and pagination.
- DataLoader-style batching.
- field/mutation/relationship authorization.
- complexity, depth, and query-cost controls.

Subscriptions should wait until durable event infrastructure exists.

## Phase F — Storage ecosystem

**Status: Planned; local storage already exists**

Current foundation:

- `FileStorage` contract.
- local private storage implementation.
- upload validation.

Planned providers and capabilities:

- S3-compatible storage.
- Cloudflare R2.
- MinIO.
- Google Cloud Storage.
- Azure Blob Storage.
- presigned URLs.
- direct-to-storage uploads.
- multipart and resumable uploads.
- upload progress.
- image thumbnails.
- virus-scanning integrations.
- durable orphan cleanup.
- cross-storage migration tooling.

## Phase G — Background operations

**Status: Planned**

Introduce a neutral background execution contract only after concrete use cases are validated.

Potential adapters:

- Taskiq.
- Dramatiq.
- Celery.
- ARQ.
- RQ.
- Temporal.

Potential capabilities:

- progress.
- cancellation.
- retry.
- scheduling.
- job history.
- resumability.
- idempotency.
- HTMX/SSE status updates.
- administration UI for operational visibility.

## Phase H — Audit and observability

**Status: Planned**

### Persistent audit

- optional persistent audit package.
- append-only audit records.
- before/after snapshots and diffs.
- field-level redaction policy.
- audit UI and export.
- retention controls.
- hash-chain integrity where justified.
- safe restore workflows.

### Metrics and tracing

- metrics registry.
- Prometheus endpoint.
- OpenTelemetry tracing and metrics.
- Grafana examples.
- correlation across requests, jobs, and integrations.

## Phase I — Import and export

**Status: Planned**

- CSV, Excel, and JSON.
- column/field mapping.
- dry-run validation.
- relationship resolution.
- atomic and best-effort modes.
- reusable templates.
- permission enforcement.
- background execution.
- progress, resumability, and idempotency.

## Phase J — Search and querying v2

**Status: Planned; basic querying already exists**

Current foundations include filters, search, sorting, and page/offset/cursor pagination contracts.

### Query composition

- grouped `AND`/`OR` filter expressions.
- reusable query definitions.
- richer filter operators where backend capabilities support them honestly.

### Search

- global search.
- PostgreSQL FTS and `pg_trgm`.
- BM25 and other lexical providers where useful.
- fuzzy, phonetic, trigram, and edit-distance search.
- Elasticsearch / OpenSearch.
- Meilisearch / Typesense / Algolia.
- MongoDB Atlas Search where an adapter boundary makes sense.
- SQLite FTS.
- semantic/vector search.
- reranking and hybrid lexical/vector search.
- optional natural-language query interpretation layered over deterministic query semantics.

### Search UX

- facets.
- highlighting.
- synonyms.
- language-aware analysis.
- locale-aware and natural sorting.
- ICU-based collation where supported.
- estimated counts.

### Pagination

- page pagination.
- limit/offset pagination.
- cursor pagination.
- keyset pagination.
- snapshot pagination.
- continuation tokens.
- hybrid strategies.

Pagination also has a separate research track later in this roadmap.

## Phase K — Authorization v2

**Status: Planned**

Current built-in authorization remains deliberately conservative and allow-only.

Potential v2 capabilities:

- explicit deny.
- role inheritance and hierarchical roles.
- direct user grants and denies.
- deterministic precedence rules.
- permission inspector and policy simulation.
- temporary/time-bound grants.
- conditional permissions.
- invite and approval flows.
- password reset/account recovery.
- JWT or PASETO authentication.

More expressive authorization must remain inspectable and deterministic.

## Phase L — Durable events and integrations

**Status: Planned; typed in-process event foundations already exist**

- transactional outbox.
- inbox/deduplication patterns.
- retries and dead-letter handling.
- Kafka.
- RabbitMQ.
- NATS.
- Redis Streams.
- Google Pub/Sub.
- webhooks.
- replay and inspection tooling.
- external subscriber compatibility guidance.
- distributed correlation and tracing.

## Phase M — Caching

**Status: Planned only after validated use cases**

Rakit intentionally does not perform automatic application-data caching today.

Potential capabilities:

- explicit `CacheBackend` contract.
- in-memory cache.
- Redis.
- permission-aware canonical cache keys.
- tag/event-driven invalidation.
- widget caching.
- stale-while-revalidate.
- diagnostics.
- distributed coordination where necessary.

Caching must remain explicit application policy rather than hidden framework behavior.

## Phase N — UI testing and accessibility automation

**Status: Planned**

Phase A established strong static and contract-level UI foundations. Phase N adds browser-level verification.

- Playwright end-to-end tests.
- cross-browser verification.
- visual regression testing.
- axe-core accessibility automation.
- keyboard-flow regression.
- formal `data-rakit-*` browser integration contract.
- automated theme contrast verification.
- advanced data-grid accessibility testing.

## Phase O — Advanced dashboard and widgets

**Status: Planned; dashboard/widget foundation already exists**

- chart widgets with accessible table fallbacks.
- visibility-aware polling.
- SSE-backed and WebSocket-backed widgets.
- saved dashboards.
- per-user layouts.
- drag-and-drop dashboard builder.
- command palette and keyboard shortcuts.
- richer operational/status widgets.

## Phase P — Scraping integrations

**Status: Planned as integrations only**

Rakit is not intended to become a scraping engine. It may provide an administration and orchestration surface for external scraping systems.

Potential integrations:

- Scrapy.
- Playwright-based jobs.
- external HTTP/browser providers.
- run management and result inspection.
- retry controls.
- scheduling through an external `JobBackend`.
- operational monitoring.

## Research track — Pagination

**Status: Research**

Rakit already exposes page, limit/offset, and cursor pagination concepts. A separate research track explores whether pagination can be improved beyond common industry patterns rather than merely adding another syntax for the same trade-offs.

Areas of investigation include:

- offset cost and stability under mutation.
- keyset ordering guarantees.
- cursor opacity and portability.
- snapshot consistency.
- continuation-token design.
- distributed data-source pagination.
- pagination across changing datasets.
- exact vs approximate counts.
- latency-aware pagination.
- hybrid page/cursor UX.
- resumable navigation.
- new pagination algorithms or abstractions where research demonstrates a real advantage.

Research results are not automatically committed to the framework API. Any new strategy must demonstrate clear semantics and honest backend capability requirements.

## Exploration

These areas are intentionally not assigned to a specific version.

### Multi-tenancy

- tenant context and resolver.
- membership models.
- tenant-aware authorization and query isolation.
- tenant switcher.
- shared-schema, schema-per-tenant, and database-per-tenant strategies.
- tenant-aware storage and jobs.
- provisioning, suspension, quotas, and reporting.
- dedicated tenant-isolation contract tests.

Multi-tenancy is not currently a framework guarantee.

### Distributed consistency

- two-phase commit where genuinely supported.
- saga coordination.
- compensating actions.
- recovery and reconciliation.
- cross-datasource operation history.

### Internationalization and localization

- translation catalogues.
- locale negotiation and per-user language.
- translated validation and plugin bundles.
- RTL layout.
- timezone-aware rendering.
- locale-aware date/number/decimal/currency formatting.
- regional input parsing.
- localized collation.

### Advanced history and versioning

- record and field-level history.
- relationship history.
- comparison views.
- restore workflows.
- legal hold and retention policies.

## Architecture principles that guide roadmap decisions

### Capability-first, not implementation-first

Framework-neutral contracts should live below concrete integrations. Uvicorn, Granian, SQLAlchemy, local storage, and future adapters remain replaceable implementations rather than assumptions inside `rakit-core`.

### Small distributions, ergonomic facade

Physical packages remain independently installable where dependency boundaries justify it, while the `rakit` facade provides ergonomic public imports.

Typical naming direction:

```text
Distribution:            rakit-<capability>-<implementation>
Implementation package:  rakit_<capability>_<implementation>
Public facade:           rakit.<capability>.<implementation>
```

Existing historical public surfaces should not be renamed without concrete ecosystem pressure and a migration plan.

### Fail closed

Rakit should not silently emulate a capability that a selected backend cannot correctly provide. Unsupported capabilities should produce precise diagnostics.

### Progressive enhancement

SSR remains the baseline web delivery model. HTMX and browser JavaScript enhance the experience rather than making basic administration behavior depend on a large client-side application runtime.

### Deterministic business semantics

Authorization, persistence, transactions, validation, and other correctness-sensitive behavior remain explicit and deterministic.

### Public API pressure should come from real applications

New abstractions should preferably be justified by the reference application or concrete adapter/product needs rather than hypothetical future flexibility.

## Not currently planned

The following are intentionally outside Rakit's current product direction:

- a universal ORM.
- a universal migration language.
- automatic production migrations during application startup.
- a built-in scraping engine.
- a built-in distributed queue implementation.
- custom cryptographic algorithms.
- implicit plugin activation.
- global service-locator access.
- silent fallback when a backend lacks a requested capability.
- automatic application-data caching without explicit policy.
- hiding backend-specific behavior behind an inaccurate universal abstraction.
- forcing all adapters into `rakit-core`.
- turning the repository into a physically nested monolith merely to mirror public import paths.

## Near-term execution order

With Phase B, C1, and C2 complete, the preferred sequence is now:

1. **C3** — normalize installation/extras UX.
2. **C4** — strengthen capability discovery and diagnostics.
3. **D** — prove the capability architecture with a carefully selected second adapter.
4. **E** — mature generated REST into a documented API product with OpenAPI and machine authentication.
5. Continue through F–P according to user value, architectural pressure, and implementation evidence.

The pagination research track can continue in parallel where it does not block committed product work.

A public release is deliberately not inserted into this sequence as an automatic milestone. Release readiness remains a separate maintainer decision.

## Roadmap management

Roadmap entries should remain categorized as **Complete**, **Next**, **Planned**, **Research**, or **Not currently planned**.

Changes should prefer evidence from implementation, reference applications, adapter work, production constraints, and user experience over speculative completeness.

The roadmap should not promise release dates until implementation maturity and maintainer intent support them.
