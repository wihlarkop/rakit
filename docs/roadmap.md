# Rakit Roadmap

This roadmap describes direction rather than release dates. Items may move as implementation experience reveals better boundaries.

## Initial `0.1` scope

### Runtime and packaging

- uv multi-package workspace.
- Python 3.12–3.14 CI.
- `rakit`, `rakit-core`, `rakit-web`, SQLAlchemy, auth, storage, and Uvicorn packages.
- Standalone and mountable Starlette ASGI runtime.
- Uvicorn first-class server adapter.
- Typed public APIs and `py.typed`.
- Ruff and ty project quality gates.

### Administration and internal tools

- SQLAlchemy `ModelAdmin` CRUD.
- Read-only custom `ResourceAdmin`.
- Full relationship editing.
- Filters, resource search, multi-column sorting, and offset pagination.
- Exact, deferred, and disabled count policies.
- Custom pages, actions, bulk actions, and JSON endpoints.
- Dashboard launchers and basic widgets.
- Jinja overrides, bundled Tailwind, and HTMX progressive enhancement.
- Light, dark, and system themes.

### Correctness and security

- Pydantic v2 validation and form engine.
- Operation-scoped DI and unit of work.
- Explicit transaction policies.
- Transaction-aware typed events.
- Optimistic concurrency.
- Server-side duplicate-submission protection.
- Secure server-side sessions, CSRF, and origin checks.
- Allow-only built-in RBAC.
- Purpose-separated cryptographic key ring and rotation.
- Trusted hosts/proxies, CSP, security headers, safe redirects, and production checks.
- Local private file storage and upload validation.
- Accessibility quality gate.
- Deadlines and cooperative cancellation.
- Structured logging.
- Health, readiness, and graceful shutdown.

### Developer experience

- `rakit check`.
- `rakit createsuperuser`.
- `rakit permissions sync`.
- `rakit routes`.
- Unit, contract, integration, and example smoke tests.
- README, design docs, security guide, extension guides, and executable examples.

## Planned after the initial release

These items have clear value and are expected to receive dedicated design work.

### Generated APIs

- Generated resource REST API.
- PUT, PATCH, and DELETE semantics.
- OpenAPI generation.
- Authenticated Swagger UI or ReDoc.
- API keys and token-based machine authentication.
- ETag, `If-Match`, and conditional requests.
- Generated GraphQL types, queries, mutations, and relationships.
- GraphQL DataLoader/batching.
- GraphQL field authorization.
- GraphQL complexity and depth limits.
- Cursor pagination.
- GraphQL subscriptions after durable event infrastructure exists.

### Storage

- S3-compatible storage.
- Cloudflare R2.
- MinIO.
- Google Cloud Storage.
- Azure Blob Storage.
- Presigned URLs.
- Direct-to-storage upload.
- Multipart and resumable upload.
- Upload progress.
- Image thumbnails.
- Virus-scanning integrations.
- Durable orphan cleanup.
- Cross-storage migration.

### Background operations

- `JobBackend` contract.
- Taskiq, Dramatiq, Celery, ARQ, RQ, and Temporal integrations.
- Progress and cancellation.
- Retry and scheduling.
- Job history UI.
- HTMX/SSE status updates.
- Resumable and idempotent jobs.

### Audit and operations

- Optional persistent audit package.
- Append-only audit records.
- Before/after snapshots and diffs.
- Redaction policy.
- Audit UI and export.
- Retention controls.
- Hash-chain integrity.
- Restore workflows where safe.
- Metrics registry.
- Prometheus endpoint.
- OpenTelemetry tracing and metrics.
- Grafana examples.

### Import and export

- CSV, Excel, and JSON.
- Column mapping.
- Dry-run validation.
- Relationship resolution.
- Atomic and best-effort policies.
- Templates.
- Permissions.
- Background execution.
- Progress and resumability.
- Idempotency.

### UI and accessibility v1

- Playwright end-to-end tests.
- Cross-browser testing.
- Visual regression.
- axe-core automation.
- Keyboard-flow regression.
- Formalized `data-rakit-*` browser integration contract.
- Chart widgets with accessible table fallback.
- Auto-refresh and visibility-aware polling.
- SSE and WebSocket widgets.
- Saved and per-user dashboard layouts.
- Drag-and-drop dashboard builder.
- Command palette and keyboard shortcuts.
- Automated theme contrast checks.
- Advanced data-grid accessibility.

### Search and querying

- Grouped `AND`/`OR` filter expressions.
- Global search.
- Full-text search.
- PostgreSQL FTS and `pg_trgm`.
- BM25 and TF-IDF providers.
- Fuzzy, phonetic, trigram, and edit-distance search.
- Elasticsearch and OpenSearch.
- Meilisearch, Typesense, Algolia, MongoDB Atlas Search, and SQLite FTS.
- Vector and semantic search.
- Reranking and hybrid search.
- Natural-language query interpretation.
- Facets, highlighting, synonyms, and language-aware analysis.
- Locale-aware, natural, and ICU sorting.
- Estimated counts.
- Cursor, keyset, snapshot, and continuation-token pagination.

### Authorization

- Explicit deny.
- Role inheritance.
- Hierarchical roles.
- Direct user grants and denies.
- Permission precedence inspector.
- Temporary and time-bound grants.
- Conditional permissions.
- Policy simulation.
- Invite and approval registration flows.
- Password reset and account recovery.
- JWT and PASETO API authentication.

### Events and integration

- Durable outbox/inbox.
- Retry and dead-letter queues.
- Kafka.
- RabbitMQ.
- NATS.
- Redis Streams.
- Google Pub/Sub.
- Webhooks.
- Event replay and inspection.
- Distributed correlation and tracing.
- External subscriber compatibility tooling.

### Caching

- `CacheBackend` protocol after validated use cases.
- Memory and Redis implementations.
- Permission-aware canonical keys.
- Tag-based invalidation.
- Event-driven invalidation.
- Widget caching.
- Stale-while-revalidate.
- Diagnostics.
- Distributed coordination.

### Scraping integrations

Rakit remains a control panel rather than a scraping engine.

Potential integrations:

- Scrapy;
- Playwright;
- HTTP/browser providers;
- scraping run management pages;
- result inspection;
- scheduling through an external job backend.

## Exploration

These areas are intentionally not assigned to a specific version.

### Multi-tenancy

- Tenant context and resolver.
- Membership models.
- Tenant-aware authorization and query isolation.
- Tenant switcher.
- Shared-schema tenancy.
- Schema-per-tenant.
- Database-per-tenant.
- Tenant-aware storage and jobs.
- Provisioning, suspension, quotas, and reporting.
- Dedicated tenant-isolation contract tests.

Multi-tenancy is not targeted for `0.1` or v1. Applications may implement their own isolation through custom queries, authorization, services, and data sources, but Rakit does not initially claim a tenant-aware guarantee.

### Distributed consistency

- Two-phase commit where supported.
- Saga coordination.
- Compensating actions.
- Recovery and reconciliation.
- Cross-datasource operation history.

### Internationalization and localization

- Translation catalogues.
- Locale negotiation.
- Per-user language.
- Translated validation and plugin bundles.
- RTL layout.
- Timezone-aware rendering.
- Locale-aware date, number, decimal, and currency formatting.
- Regional input parsing.
- Localized collation.

### Advanced history

- Record version history.
- Field-level change history.
- Relationship history.
- Comparison and restore.
- Legal hold and retention policies.

## Not currently planned

- A universal ORM.
- A universal migration language.
- Automatic production migrations at startup.
- A built-in scraping engine.
- A built-in distributed queue.
- Custom cryptographic algorithms.
- Implicit plugin activation.
- Global service-locator access.
- Silent fallback when a backend lacks a requested capability.
- Automatic data caching without explicit application policy.
- Hiding backend-specific behavior behind an inaccurate universal abstraction.

## Roadmap management

Roadmap entries should be categorized as:

- **Planned:** valuable direction with a reasonably clear boundary.
- **Exploration:** valuable but not sufficiently designed or validated.
- **Not currently planned:** intentionally outside the product focus.

The roadmap should not promise release dates until implementation capacity and validated scope support them.
