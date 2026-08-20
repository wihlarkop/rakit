# Rakit Roadmap

This document is the canonical public roadmap for Rakit.

The roadmap describes product direction and engineering priorities rather than release dates. Items may move as implementation experience reveals better abstractions or sharper boundaries.

Rakit is still under active pre-release development. The current package version target is `0.1.0a1`, but publication is intentionally deferred until the maintainer considers the framework ready.

## Status legend

- **Complete** — implemented and merged to `main`.
- **Next** — next major workstream expected to receive active implementation.
- **Planned** — accepted direction, but not necessarily fully designed yet.
- **Research** — exploratory work that may change shape substantially.
- **Not currently planned** — intentionally outside the product focus.

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
| Phase C developer experience and lifecycle ergonomics | **Next** |
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

No package publication is implied by completion of Plan 07.

## Phase A — UI/UX maturity

Phase A upgraded Rakit from a functional administration surface into a more cohesive product UI while preserving SSR and progressive enhancement.

### UI-01 — Showcase baseline

**Status: Complete**

- representative UI showcase.
- shared visual baseline for subsequent UI work.

### UI-02 — Responsive shell and navigation

**Status: Complete**

- responsive application shell.
- navigation behavior across screen sizes.
- sidebar behavior and persistence contracts.

### UI-03 — Design foundation, icons, and theme

**Status: Complete**

- design tokens and visual foundation.
- icon system.
- light, dark, and system themes.
- bundled Tailwind build.

### UI-04 — Core components

**Status: Complete**

- reusable UI primitives.
- dialogs, feedback states, controls, and component-level presentation contracts.

### UI-05 — Resource experience

**Status: Complete**

- mature resource list/detail/form experiences.
- filter presentation.
- query UI.
- pagination presentation.
- resource actions and state feedback.

### UI-06 — Advanced operations

**Status: Complete**

- advanced actions.
- bulk operations.
- relationships and uploads.
- authentication/system surfaces.
- custom pages and feedback states.

### UI-07 — Responsive/accessibility hardening and advanced widgets

**Status: Complete**

- keyboard and focus contracts.
- motion and contrast contracts.
- responsive hardening.
- advanced widget foundations.

### UI-08 — Final Phase A polish

**Status: Complete**

- final visual and interaction polish across the Phase A surface.
- Phase A acceptance and integration cleanup.

## Phase B — Alpha hardening and real-world validation

Phase B validates that the framework works as a coherent product rather than only as a collection of individually complete subsystems. Phase B is complete; public release remains a separate maintainer decision and is still deferred.

### B1 — Alpha readiness audit

**Status: Complete**

- reconstructed alpha acceptance criteria.
- audited the current framework against the original pre-release definition of done.
- identified remaining hardening work without triggering a release.

### B2 — Alpha/core hardening

**Status: Complete**

B2 hardened package boundaries, artifact correctness, generated assets, and public semantics.

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

The two superseded roadmap-only branches were retired after B2 absorbed their useful intent:

- `chore/httpstatus-roadmap-todo`.
- `chore/rakit-table-prefix-roadmap-todo`.

No stale implementation was merged or rebased; the work was reimplemented from current `main`.

### B3 — Realistic reference application

**Status: Complete**

`examples/reference_app` now provides a realistic commerce/backoffice application composed through public Rakit APIs. It exercises:

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
- an isolated subprocess smoke test that creates a fresh database, compiles the app, seeds auth/domain data, and proves readiness.

The example deliberately keeps application models, driver choice, migrations/bootstrap policy, and domain transitions outside Rakit core.

### B4 — API and DX refinement from the reference application

**Status: Complete**

The reference application exposed a small set of concrete public-API friction points, which were fixed without introducing a broad speculative abstraction layer:

- `rakit.auth.sqlalchemy` now exposes the operational auth primitives needed to bootstrap the built-in schema, users, roles, permissions, password hashing, permission synchronization, and durable idempotency.
- `Admin.register_write(...)` enables ordinary resource write forms without forcing applications to construct transport-level `WriteResourceBinding` objects or duplicate CSRF/auth/template plumbing.
- lifecycle startup callbacks now provide a fail-fast initialization seam before the runtime enters `READY`.
- the root `rakit` facade exposes the domain-action composition contracts needed to declare typed actions without importing internal modules.
- reference-app documentation now makes persistence, transaction, storage-descriptor, and application/framework ownership boundaries explicit.

These changes preserve explicit authorization, transaction ownership, adapter boundaries, and fail-closed behavior. No release, tag, version bump, or package publication is implied by Phase B completion.

## Phase C — Developer experience and lifecycle ergonomics

**Status: Next**

### C1 — Friendly CRUD and lifecycle APIs

- simplify common registration and lifecycle flows.
- reduce unnecessary boilerplate.
- retain explicit behavior for authorization, transactions, and capabilities.
- improve extension ergonomics without hiding important framework semantics.

### C2 — Project initialization and scaffolding

Design a Vite-like interactive `rakit init` flow.

Potential choices include:

- project name and layout.
- standalone Rakit vs integration into an existing application.
- web integration.
- persistence adapter.
- server adapter.
- authentication.
- storage.
- generated examples and starter resources.

The initializer should support both creating a new project and adding Rakit to an existing project where practical.

### C3 — Installation and extras UX

Continue simplifying optional capability installation.

Examples:

```bash
uv add "rakit[standard]"
uv add "rakit[uvicorn]"
uv add "rakit[granian]"
uv add "rakit[sqlalchemy]"
```

Goals:

- predictable extra names.
- clear missing-dependency errors.
- no implicit adapter activation.
- no unnecessary heavy dependencies in the base install.

### C4 — Capability discovery

Expand diagnostics such as `rakit check` and capability inspection.

Potential output should make it obvious which adapters are installed and which capabilities are available.

Examples of capability groups:

- servers.
- persistence.
- schema.
- storage.
- authentication.
- generated API transports.

## Phase D — Adapter ecosystem

**Status: Planned**

Rakit should prove that its capability architecture works beyond the first implementation in each category.

The goal is not to support every library immediately. The preferred strategy is to add one well-chosen second adapter at a time and use the resulting pressure to improve contracts.

Potential web integrations:

- FastAPI.
- Starlette.
- Litestar.
- Sanic.
- Flask.

Potential persistence integrations:

- SQLAlchemy ORM/Core.
- Tortoise ORM.
- Peewee.
- Masonite ORM or other compatible ecosystems where the capability model fits honestly.

Potential schema integrations:

- Pydantic.
- msgspec.
- dataclass-based adapters.

Likely early candidates for proving a second implementation include Litestar, Tortoise ORM, or msgspec.

Adapter work must preserve an important rule: unsupported capabilities fail explicitly rather than being silently approximated.

## Phase E — Generated APIs v1

**Status: Planned; foundation already exists**

Generated REST is not starting from zero. Rakit already contains substantial generated API foundations, including compilation contracts, read and mutation runtimes, SQLAlchemy execution, filters, pagination contracts, authorization integration, concurrency handling, idempotency, and structured HTTP errors.

### E1 — Complete and polish generated REST

- complete public REST surface.
- consistent resource route conventions.
- clarify supported mutation semantics.
- strengthen public documentation and examples.

### E2 — HTTP mutation semantics

- POST semantics.
- PATCH semantics.
- DELETE semantics.
- evaluate PUT semantics where a true replacement operation is meaningful.

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

### E7 — GraphQL foundation

GraphQL should follow a mature REST surface rather than precede it.

Potential scope:

- generated types.
- queries.
- mutations.
- relationships.
- pagination.

### E8 — GraphQL batching

- DataLoader-style batching.
- relationship query efficiency.

### E9 — GraphQL authorization

- field authorization.
- mutation authorization.
- relationship authorization.

### E10 — GraphQL safety

- complexity limits.
- depth limits.
- query cost controls.

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
- multipart uploads.
- resumable uploads.
- upload progress.
- image thumbnails.
- virus-scanning integrations.
- durable orphan cleanup.
- cross-storage migration tooling.

## Phase G — Background operations

**Status: Planned**

Introduce a neutral background execution contract only after concrete use cases are validated.

Potential abstraction:

```python
class JobBackend:
    ...
```

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
- audit UI.
- export.
- retention controls.
- hash-chain integrity where justified.
- safe restore workflows.

### Metrics and tracing

- metrics registry.
- Prometheus endpoint.
- OpenTelemetry tracing.
- OpenTelemetry metrics.
- Grafana examples.
- correlation across requests, jobs, and integrations.

## Phase I — Import and export

**Status: Planned**

- CSV.
- Excel.
- JSON.
- column/field mapping.
- dry-run validation.
- relationship resolution.
- atomic import mode.
- best-effort import mode.
- reusable templates.
- permission enforcement.
- background execution.
- progress reporting.
- resumability.
- idempotency.

## Phase J — Search and querying v2

**Status: Planned; basic querying already exists**

Current foundations include filters, search, sorting, and page/offset/cursor pagination contracts.

### Query composition

- grouped `AND`/`OR` filter expressions.
- reusable query definitions.
- richer filter operators where backend capabilities support them honestly.

### Search

- global search.
- full-text search.
- PostgreSQL FTS.
- `pg_trgm`.
- BM25 providers.
- TF-IDF providers where useful.
- fuzzy search.
- phonetic search.
- trigram/edit-distance search.
- Elasticsearch.
- OpenSearch.
- Meilisearch.
- Typesense.
- Algolia.
- MongoDB Atlas Search where an adapter boundary makes sense.
- SQLite FTS.
- semantic/vector search.
- reranking.
- hybrid lexical/vector search.
- natural-language query interpretation as an optional layer rather than a replacement for deterministic query semantics.

### Search UX

- facets.
- highlighting.
- synonyms.
- language-aware analysis.
- locale-aware sorting.
- natural sorting.
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

Pagination also has a separate research track described later in this roadmap.

## Phase K — Authorization v2

**Status: Planned**

Current built-in authorization is deliberately conservative and allow-only.

Potential v2 capabilities:

- explicit deny.
- role inheritance.
- hierarchical roles.
- direct user grants.
- direct user denies.
- well-defined precedence rules.
- permission inspector.
- temporary/time-bound grants.
- conditional permissions.
- policy simulation.
- invite flows.
- approval-based registration flows.
- password reset/account recovery.
- JWT authentication.
- PASETO authentication.

More expressive authorization must remain inspectable and deterministic.

## Phase L — Durable events and integrations

**Status: Planned; typed in-process event foundations already exist**

- transactional outbox.
- inbox/deduplication patterns.
- retries.
- dead-letter handling.
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

Potential abstraction:

```python
class CacheBackend:
    ...
```

Potential capabilities:

- in-memory cache.
- Redis.
- permission-aware canonical cache keys.
- tag-based invalidation.
- event-driven invalidation.
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
- SSE-backed widgets.
- WebSocket-backed widgets.
- saved dashboards.
- per-user layouts.
- drag-and-drop dashboard builder.
- command palette.
- keyboard shortcuts.
- richer operational/status widgets.

## Phase P — Scraping integrations

**Status: Planned as integrations only**

Rakit is not intended to become a scraping engine. It may provide an administration and orchestration surface for external scraping systems.

Potential integrations:

- Scrapy.
- Playwright-based jobs.
- external HTTP/browser providers.
- run management pages.
- result inspection.
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
- tenant-aware authorization.
- tenant-aware query isolation.
- tenant switcher.
- shared-schema tenancy.
- schema-per-tenant.
- database-per-tenant.
- tenant-aware storage.
- tenant-aware jobs.
- provisioning and suspension.
- quotas and reporting.
- dedicated tenant-isolation contract tests.

Multi-tenancy is not currently a framework guarantee. Applications can build isolation using custom queries, authorization, services, and data sources, but Rakit should not claim a tenant-aware guarantee until the entire capability surface is designed and tested accordingly.

### Distributed consistency

- two-phase commit where genuinely supported.
- saga coordination.
- compensating actions.
- recovery and reconciliation.
- cross-datasource operation history.

### Internationalization and localization

- translation catalogues.
- locale negotiation.
- per-user language.
- translated validation.
- plugin translation bundles.
- RTL layout.
- timezone-aware rendering.
- locale-aware date/number/decimal/currency formatting.
- regional input parsing.
- localized collation.

### Advanced history and versioning

- record version history.
- field-level change history.
- relationship history.
- comparison views.
- restore workflows.
- legal hold.
- retention policies.

## Architecture principles that guide roadmap decisions

### Capability-first, not implementation-first

Framework-neutral contracts should live below concrete integrations. Implementations such as Uvicorn, Granian, SQLAlchemy, or local storage should remain replaceable adapters rather than becoming assumptions inside `rakit-core`.

### Small distributions, ergonomic facade

Physical packages remain independently installable where the dependency boundary justifies it, while the `rakit` facade provides ergonomic public imports.

Typical naming direction:

```text
Distribution:           rakit-<capability>-<implementation>
Implementation package: rakit_<capability>_<implementation>
Public facade:          rakit.<capability>.<implementation>
```

Existing historical public surfaces should not be renamed without concrete ecosystem pressure and a migration plan.

### Fail closed

Rakit should not silently emulate a capability that a selected backend cannot correctly provide.

Unsupported capabilities should produce precise diagnostics.

### Progressive enhancement

SSR remains the baseline web delivery model. HTMX and browser JavaScript should enhance the experience rather than make basic administration behavior depend on a large client-side application runtime.

### Deterministic business semantics

Authorization, persistence, transactions, validation, and other correctness-sensitive behavior should remain explicit and deterministic.

### Public API pressure should come from real applications

New abstractions should preferably be justified by the reference application or concrete adapter/product needs rather than by hypothetical future flexibility.

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

The current preferred execution sequence is:

1. **B2.7** — retire superseded stale branches.
2. **B3** — build the realistic `examples/reference_app` using public APIs only.
3. **B4** — repair API and DX friction found by the reference application.
4. **C** — improve lifecycle ergonomics, project initialization, installation UX, and capability discovery.
5. **D** — prove the adapter architecture with a carefully selected second implementation in one capability category.
6. **E** — mature generated REST into a documented API product, including OpenAPI and machine authentication.
7. Continue through the remaining workstreams according to user value, architectural pressure, and implementation evidence.

A public release is deliberately not inserted into this sequence as an automatic milestone. Release readiness remains a separate maintainer decision.

## Roadmap management

Roadmap entries should remain categorized as **Complete**, **Next**, **Planned**, **Research**, or **Not currently planned**.

Changes to this roadmap should prefer evidence from implementation, reference applications, adapter work, production constraints, and user experience over speculative completeness.

The roadmap should not promise release dates until implementation maturity and maintainer intent support them.
