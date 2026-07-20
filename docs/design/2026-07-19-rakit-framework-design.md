# Rakit Framework Design

**Status:** Approved design baseline  
**Date:** 2026-07-19  
**Initial target:** Rakit `0.1`

## 1. Product definition

Rakit is a composable Python framework for building admin panels, internal tools, dynamic dashboards, and APIs over any data source.

Admin CRUD is the initial entry point, but Rakit is not limited to ORM-backed administration. A Rakit application may combine:

- ORM-backed model administration;
- custom read-only or writable resources;
- internal operational pages;
- typed actions;
- JSON endpoints;
- dashboard launchers and widgets;
- application services;
- storage and authentication providers;
- future generated REST and GraphQL APIs.

The framework uses an assembly metaphor: developers **merakit** resources, pages, actions, endpoints, dashboards, adapters, themes, and services.

## 2. Architectural principles

1. **Security first.** Secure behavior is the default, while insecure behavior requires explicit configuration and startup diagnostics.
2. **Framework-agnostic domain core.** Core definitions do not depend on Starlette, FastAPI, SQLAlchemy, or a specific persistence engine.
3. **Explicit composition.** Registration, plugin activation, service ownership, transactions, and extension points are explicit.
4. **One operation model.** CRUD, actions, pages, endpoints, relationships, and future generated APIs share authorization, validation, transaction, event, concurrency, idempotency, and error boundaries.
5. **Capability-aware portability.** Core models common administration concepts but does not pretend every backend supports the same query or transaction semantics.
6. **Progressive enhancement.** Server-rendered HTML remains functional without JavaScript; HTMX improves targeted interactions.
7. **Replaceable batteries.** Official implementations are provided where valuable, but core contracts allow applications to replace them.
8. **Typed public surface.** Public packages are fully typed and ship `py.typed`.

## 3. Runtime and integration architecture

### 3.1 ASGI runtime

Rakit provides a standalone ASGI sub-application implemented internally with Starlette. It may run independently or be mounted into another ASGI application.

Initial integration priorities:

- standalone ASGI;
- FastAPI mounting;
- Starlette mounting.

Later integrations may include Litestar and Sanic. Flask can initially use ASGI/WSGI composition, with deeper native integration considered later.

Rakit remains a standard ASGI application. A server implementation is not the web framework.

### 3.2 Servers

Uvicorn is the first official server implementation. Supported usage should include:

```text
uv run main.py
uv run uvicorn main:app --reload
uv run rakit run main:app
```

Hypercorn and Granian are future server adapters. Server configuration is separate from `RakitConfig`, and unsupported server capabilities must fail explicitly rather than being ignored.

### 3.3 Package workspace

Rakit uses a uv multi-package workspace from the beginning.

Initial package direction:

```text
rakit
rakit-core
rakit-web
rakit-sqlalchemy
rakit-auth-sqlalchemy
rakit-storage
rakit-storage-local
rakit-server-uvicorn
```

Rules:

- strict one-way dependency graph;
- no package cycles;
- synchronized official package versions;
- committed `uv.lock`;
- Python 3.12 minimum;
- CI on Python 3.12, 3.13, and 3.14;
- Ruff for linting, formatting, and imports;
- ty for static typing;
- `py.typed` in public packages.

## 4. Core primitives

The primary public primitives are:

- `Resource`;
- `Page`;
- `Endpoint`;
- `Action`;
- `Dashboard`;
- `Widget`.

Ergonomic public APIs include:

- `ModelAdmin`;
- `ResourceAdmin`;
- `AdminPage`;
- `AdminEndpoint`;
- decorators such as `@admin.page`, `@admin.api.get`, and `@admin.action`.

All class- and function-based APIs compile into common immutable definitions:

- `ResourceDefinition`;
- `PageDefinition`;
- `EndpointDefinition`;
- `ActionDefinition`;
- dashboard and widget definitions.

`ResourceAdmin` is the universal resource abstraction. `ModelAdmin` is an ORM/ODM convenience abstraction that compiles into the same resource model.

Explicit configuration overrides introspection. Introspection overrides core fallback behavior.

## 5. Stable identifiers and routing

Machine identifiers, URL paths, and human labels are distinct contracts.

Example:

```python
class UserAdmin(ModelAdmin):
    model = User
    resource_id = "users"
    path = "/people"
    label = "User Accounts"
```

- `resource_id` is stable and used by permissions, events, logs, templates, and reverse routing.
- `path` may change without changing the internal contract.
- `label` is presentation text and may be customized or translated later.

The same pattern applies to pages, actions, filters, endpoints, dashboards, widgets, plugins, and admin instances.

Identifiers are inferred for quick starts but can be explicitly fixed for production applications and public plugins.

Every route has a stable route name. URLs are generated through a reverse resolver rather than manual string concatenation.

Multiple `Admin` instances may coexist in one host application and have independent route namespaces, themes, navigation, and policies.

Compilation rejects identifier and route collisions.

Renaming aliases and migration tooling are roadmap items. Stable IDs should not be changed casually after production use.

## 6. Data sources and query model

Core models a small backend-neutral administration vocabulary rather than a universal ORM.

A `DataSource` supports capability-aware operations such as:

- list;
- detail;
- create;
- update;
- delete;
- query;
- relationship operations;
- transactions where supported.

Introspection is optional. Explicit schemas and custom data sources are first-class.

The initial `ResourceQuery` supports:

- offset pagination;
- search;
- multi-column sorting;
- simple filters.

Initial filter operators:

```text
eq, neq, lt, lte, gt, gte, contains, in, is_null
```

Simple filters are combined using `AND` in `0.1`. Grouped `AND`/`OR` expressions are deferred.

Filter, search, and sort fields are whitelisted. Sensitive or unreadable fields cannot be accessed through URL query parameters.

Portable hooks and adapter-native hooks coexist. Rakit does not hide backend-specific capabilities when portability would reduce correctness.

## 7. Record identity

`RecordIdentity` is a structured mapping and can represent multiple identity fields.

`IdentityCodec` produces safe URL representations and never uses pickle.

The SQLAlchemy `0.1` guarantee covers single integer, UUID, or string primary keys. Composite identities are represented internally, with complete official UX and adapter support deferred.

## 8. SQLAlchemy and migrations

SQLAlchemy is the first official persistence adapter. PostgreSQL and SQLite are supported through SQLAlchemy.

Rakit is migration-aware, but not a migration engine.

- Rakit does not provide universal database migrations.
- Rakit does not run migrations automatically during startup.
- SQLAlchemy applications use Alembic.
- Plugins that own persistence own their migrations.
- Core has no mandatory database.
- Built-in SQLAlchemy authentication owns its schema and Alembic migrations.

## 9. Initial resource scope

### 9.1 `ModelAdmin`

The initial SQLAlchemy-backed `ModelAdmin` target includes:

- list;
- detail;
- create;
- update;
- delete;
- pagination;
- search;
- sorting;
- filtering;
- introspected forms;
- Jinja template overrides;
- complete relationship editing.

### 9.2 `ResourceAdmin`

The initial custom resource target is read-only list and detail over an arbitrary data source. Writable custom resources remain architecturally supported and may expand after the initial release.

### 9.3 `AdminPage`

Custom pages support GET and POST, typed input, Jinja rendering, HTMX fragments, and service calls.

### 9.4 `AdminEndpoint`

Custom JSON endpoints support GET and POST, explicit input sources, Pydantic input/output schemas, authentication, authorization, transactions, timeout, cancellation, error normalization, CSRF, and idempotency for session-authenticated POST operations.

Generated resource REST and GraphQL APIs are separate roadmap systems.

## 10. Sorting

Sorting is a typed, multi-column system.

A sort item contains:

- field;
- direction: ascending or descending;
- null placement: auto, first, or last.

Resolution order:

1. request sorting;
2. resource default ordering;
3. adapter-inferred ordering;
4. identity ascending.

Rakit appends identity as a stable tie-breaker unless an advanced override explicitly replaces this behavior. Composite identity uses all identity components.

The UI supports multi-column sorting with a bookmarkable normalized URL.

Sorting is permission-aware and whitelist-based. Relationship and computed-field sorting require explicit mappings or expressions. To-many sorting requires an explicit aggregate or adapter-native implementation.

Null placement is capability-aware. Locale-aware, natural, and ICU sorting are roadmap items.

## 11. Pagination and count policies

Rakit `0.1` uses offset pagination.

User-facing pagination uses `page` and `per_page`, while data sources receive normalized offset and limit values.

Page sizes are configurable with safe defaults and a maximum limit.

Three count policies are included:

### `EXACT`

Runs an accurate count query. This is the default for straightforward SQLAlchemy resources.

### `DEFERRED`

Renders data first and loads total count through HTMX.

### `DISABLED`

Does not run a count query. The adapter fetches `limit + 1` records to determine whether a next page exists.

Count must use the same authorization and visibility scope as the list query. It must not reveal inaccessible records.

Relationship joins must not cause incorrect duplicate counts. Adapters use distinct identity counting or safe derived queries, and reject cases they cannot infer safely.

Custom count statements and count-policy hooks are supported.

Stable sorting is applied before pagination. Cursor, keyset, snapshot, continuation-token, and estimated-count strategies are roadmap items.

## 12. Fields, schemas, forms, and validation

Pydantic v2 is the official schema and validation engine.

A `SchemaAdapter` boundary permits future schema engines such as msgspec. Public validation errors are normalized into Rakit error types.

Rakit provides a lightweight form engine over Pydantic and Jinja, not WTForms.

The form engine owns:

- HTML input parsing;
- CSRF integration;
- field-error mapping;
- layout;
- visibility;
- read-only behavior;
- widgets;
- form state.

Unknown submitted fields are rejected by default to prevent mass assignment.

Initial widget types:

- text;
- textarea;
- password;
- email;
- number;
- checkbox;
- select;
- date;
- datetime;
- hidden;
- read-only;
- local file upload.

Form layouts include:

- sections;
- rows and columns;
- tabs;
- collapsible groups;
- fields;
- relationship panels;
- custom blocks.

Create, update, and detail layouts may differ.

Conditional visibility and read-only rules are structured and server-safe. HTMX may provide dependent options and lazy sections.

## 13. Field security and presentation

Sensitive fields are hidden by default from:

- list;
- detail;
- create;
- update;
- search;
- filtering;
- sorting;
- export;
- audit payloads.

Password hashes are never displayed. Password changes use dedicated actions.

Field definitions distinguish persisted/model fields from computed display fields.

Computed fields may use sync, async, batch, or query-expression resolution. Batch resolvers avoid N+1 behavior.

Raw HTML is rejected by default. Only explicit trusted HTML or custom Jinja templates may render unescaped content.

List, detail, create, and update field sets are independently configurable.

## 14. Relationships

Complete relationship editing is a `0.1` goal:

- many-to-one;
- one-to-one;
- one-to-many;
- many-to-many;
- self-reference;
- association tables;
- association objects;
- nullable and ordered relationships;
- composite relationships where the adapter supports them.

A backend-neutral `RelationshipDefinition` describes the relationship.

Edit modes:

```text
LINK, INLINE, NESTED, READ_ONLY, HIDDEN
```

To-one relationships use select or HTMX autocomplete. To-many and one-to-many relationships support link/unlink, inline editing, ordering, validation, pagination, and dedicated pages as appropriate.

Association-object fields are editable.

Relationship changes compile into `RelationshipMutationPlan` and participate in a single resource mutation plan and operation-scoped transaction.

Permissions are granular. Cascades and destructive effects require previews and confirmation.

Visible relationships use explicit loading strategies to avoid N+1 queries.

Nested editing defaults to a maximum depth of one. Cycles and self-references are detected. Larger depths require explicit configuration and warnings.

A scoped base query applies consistently to list, detail, edit, delete, actions, relationship lookup, and future export to prevent authorization leaks.

## 15. Filters and search

Initial filters include:

- exact;
- text;
- boolean;
- single and multiple choice;
- number range;
- date and datetime range;
- null;
- relationship;
- custom portable filters;
- adapter-native filters.

Options may be dynamic, permission-aware, and service-backed.

Search initially supports:

- exact;
- prefix;
- contains;
- multiple fields;
- explicitly configured relationship fields;
- normalization;
- portable and adapter-native hooks;
- bookmarkable HTMX behavior.

Global search is not an initial feature.

Advanced full-text, fuzzy, lexical, semantic, vector, hybrid, and external search providers are roadmap items.

## 16. Create and update pipelines

Write pipelines are explicit and typed:

```text
raw input
→ Pydantic parse
→ normalize
→ business validation
→ prepare mutation plan
→ authorize
→ pre-event
→ execute
→ flush
→ before-commit
→ commit
→ post-event
→ result
```

Create and update have separate normalize, validate, prepare, and execute hooks.

Update receives:

- current record;
- submitted changes;
- relationship mutation;
- concurrency metadata.

Execution may be replaced by an application domain service.

Hooks must not commit unless the transaction policy is explicitly manual. Post-commit side effects use the event system.

## 17. Unified actions

Page, resource, record, and bulk actions share one `ActionDefinition`.

Actions support:

- typed Pydantic input;
- GET form, preview, or confirmation;
- POST execution;
- full-page fallback;
- permission requirements;
- visibility states: available, disabled, or hidden;
- rechecking on POST;
- mutation-plan execution;
- custom domain-service execution;
- transactions;
- concurrency;
- idempotency;
- events;
- structured results.

Action availability is not authorization. Record actions load records through the scoped resource query.

Built-in CRUD uses the same execution foundation.

## 18. Bulk actions

Bulk actions are an initial feature.

Selections may be:

- explicit record identities;
- a validated current query with exclusions.

Policies:

- `ATOMIC` by default;
- `BEST_EFFORT` explicitly, using savepoints where supported.

Bulk operations include permission checks, impact previews, strong confirmation, re-counting, mutation plans, and lifecycle events.

Recommended initial safety defaults:

- confirmation above 25 records;
- synchronous maximum of 1,000 records, configurable;
- larger operations rejected unless explicitly raised or delegated to an external job system.

Atomic conflicts roll back the full operation. Best-effort mode reports per-item outcomes.

## 19. Optimistic concurrency

Rakit `0.1` does not silently overwrite concurrent changes.

Modes:

```text
AUTO, REQUIRED, DISABLED
```

Provider priority:

1. explicit version provider;
2. native ORM version metadata;
3. `updated_at` or revision field;
4. safe snapshot fingerprint.

SQLAlchemy `version_id_col` is preferred.

Signed concurrency tokens bind resource, identity, version, time, and snapshot information.

Concurrency applies to:

- update;
- delete;
- relationships;
- record actions;
- bulk operations.

Conflicts return HTTP 409 and a structured conflict model. The UI preserves input, shows base/current/proposed values, identifies field and relationship conflicts, and may reapply non-conflicting changes after validation.

Force overwrite requires a dedicated permission, strong confirmation, and security event.

## 20. Delete policies

Deletion is represented by a `DeletePolicy` contract.

The only official `0.1` implementation is `HardDeletePolicy`.

Rakit does not infer soft delete from a `deleted_at` field.

The delete pipeline creates a `DeletionPlan`, analyzes relationships and cascades, validates authorization and concurrency, obtains confirmation, executes in a transaction, and emits events.

Custom delete policies may be supplied in `0.1`.

Soft delete, archive, restore, purge, retention, legal hold, and scheduled cleanup are roadmap items.

## 21. Authentication, users, and RBAC

Core contracts include:

- `AuthBackend`;
- `IdentityProvider` or `UserProvider`;
- `AuthorizationProvider` or `PermissionPolicy`;
- `SessionStore`;
- `Principal`.

`rakit-auth-sqlalchemy` provides optional built-in:

- `User`;
- `Role`;
- `Permission`;
- `Session`;
- login/logout;
- user/role/permission management UI;
- Alembic migrations.

The built-in model is named `User` and may serve as the application's main user model.

The user model direction includes:

- ID;
- email;
- optional username;
- password hash;
- display name;
- active and superuser flags;
- verification and login metadata;
- timestamps.

Email is the default login identifier. Username and combined email-or-username modes are configurable. Username does not contain `@` by default.

Registration is disabled by default. Initial creation flows are administrator creation and `createsuperuser`. Public, invite, and approval registration are roadmap items.

Admin access uses an explicit permission such as `{admin_id}.access`. Allowing all authenticated users requires an explicit policy.

### 21.1 Permission catalogue

Stable permission keys derive from stable machine IDs.

Initial automatically generated permissions include:

- resource CRUD;
- page view;
- action execution;
- endpoint invocation.

Field and relationship permissions are supported but generated only when configured, preventing uncontrolled catalogue growth.

Authorization returns a structured decision, not only a boolean.

Operation permission and record visibility are separate boundaries.

Built-in RBAC uses:

- default deny;
- allow-only role grants;
- configurable superuser bypass.

Superuser permission bypass does not bypass validation, concurrency, security logging, or hidden secret-field policy.

Explicit deny, role inheritance, hierarchical roles, direct grants, temporary grants, and precedence inspection are roadmap items.

Permission definitions are compiled and frozen. Synchronization adds and updates definitions but does not silently delete old permissions; obsolete definitions become orphaned or deprecated.

## 22. Sessions and password security

Admin browser sessions use opaque random cookie tokens with server-side session storage.

The database stores token hashes and session metadata, not raw tokens.

Cookie defaults in production:

- HttpOnly;
- Secure;
- SameSite=Lax;
- scoped to the admin mount path where practical.

Sessions support:

- rotation;
- logout/revocation;
- idle expiry;
- absolute expiry.

All session-authenticated mutations use CSRF protection.

Password hashing uses `argon2-cffi` directly with Argon2id through a replaceable `PasswordHasher` protocol. Password verification and rehashing run away from the event loop, with bounded concurrency where needed.

JWT and PASETO are future API-authentication options, not browser-session replacements in `0.1`.

## 23. Security baseline

Security middleware is a core `rakit-web` feature.

Initial protections include:

- trusted hosts;
- explicit trusted proxy configuration;
- secure cookies;
- CSRF;
- origin validation;
- request and upload size limits;
- security headers;
- Content Security Policy;
- login rate limiting;
- safe redirects;
- sensitive response `no-store`;
- signed destructive confirmations;
- production startup validation;
- structured security events.

Proxy headers are never trusted automatically.

The default CSP uses local assets and disallows framing. Plugins extend CSP declaratively rather than disabling it globally.

Admin pages are not embeddable in iframes by default.

Redirects are internal by default. External redirects require an explicit safe type and policy.

Production validation detects unsafe secrets, wildcard hosts, insecure cookie configuration, overbroad proxies, public exposure of private files, disabled CSP, development-only session/idempotency stores, and other dangerous settings.

## 24. Cryptographic key management

Key management is part of `0.1`.

A persistent production root secret or key ring is required. Secrets use a redacting `SecretValue` type.

Rakit derives purpose-separated keys for:

- session-related cryptography;
- CSRF;
- destructive confirmation;
- optimistic concurrency;
- file access;
- future reset and API tokens.

Purpose derivation also includes `admin_id` and token version.

A key ring supports:

- one active key;
- previous verification keys;
- stable key IDs;
- controlled emergency invalidation.

Tokens carry:

- purpose;
- version;
- key ID;
- issued time;
- expiry;
- purpose-specific claims.

Session cookies remain opaque and server-side.

One-time token replay protection uses a `TokenReplayStore` and stores token hashes only.

Rakit uses mature cryptographic libraries and standard primitives. It does not implement custom cryptography.

Cloud secret-manager integrations are roadmap items. Applications may supply secrets from any provider through the composition root in `0.1`.

## 25. CSRF, idempotency, and replay protection

All POST mutations receive a server-validated submission token.

Tokens bind:

- admin;
- principal/session;
- operation and target;
- record identity where relevant;
- mutation fingerprint;
- issue time;
- expiry;
- nonce.

A pluggable `IdempotencyStore` tracks:

```text
AVAILABLE
IN_PROGRESS
COMPLETED
FAILED_RETRYABLE
FAILED_FINAL
EXPIRED
```

Duplicate behavior:

- an in-progress duplicate returns a structured conflict;
- a completed duplicate replays a safe operation receipt;
- the same token with a different fingerprint is rejected.

Protection applies to:

- create;
- update;
- delete;
- relationship mutation;
- record action;
- bulk action;
- custom page POST;
- custom endpoint POST;
- file attachment/replacement.

The built-in SQLAlchemy auth package provides a shared database-backed store. Memory storage is development/test only.

Idempotency is not advertised as exactly-once execution. Database constraints, business keys, and domain-level idempotency remain necessary.

## 26. Local file storage

File storage uses a backend-neutral `FileStorage` contract.

An official local filesystem implementation is included initially. External implementations may be supplied by applications through the same contract.

Files are represented by a portable `StoredFile` descriptor containing:

- storage ID;
- object key;
- original name;
- content type;
- size;
- checksum.

Browser filenames are metadata only and are never trusted as filesystem paths.

Local storage uses generated object keys, path-traversal protection, temporary writes, and safe replacement behavior.

Private access is the default. Private downloads use authenticated routes, signed/opaque references, and current resource/record/field permission checks.

Validation includes:

- request and field size limits;
- MIME and extension allowlists;
- filename limits;
- zero-byte policy;
- checksum generation;
- permission checks.

MIME values from browsers are not trusted as a complete security guarantee.

Database and storage are not one atomic transaction. The initial implementation uses best-effort compensation and records cleanup failures.

Replacing a file deletes the old object only after successful database commit.

File deletion behavior is explicit:

```text
KEEP, DELETE, CUSTOM
```

Multiple named storages are supported.

Official S3-compatible, R2, GCS, Azure, direct upload, resumable upload, thumbnail, scanning, and durable cleanup integrations are roadmap items.

## 27. Templates, CSS, HTMX, and UI

Jinja2 is the default templating system.

Template override precedence:

1. resource-specific user override;
2. generic user override;
3. theme/plugin template;
4. built-in template.

Documented template names, blocks, macros, and context objects are public compatibility surfaces.

Tailwind CSS v4 is compiled and bundled in the wheel. Normal users do not need Node.js or a production CDN.

Design tokens and CSS variables support branding.

HTMX and minimal vanilla JavaScript provide progressive enhancement. HTMX is bundled locally.

The built-in theme supports:

- light;
- dark;
- system.

System is the default. Theme preference uses local storage and a safe early-loading script.

The main navigation is a modern sidebar with:

- groups;
- resources;
- pages;
- icons;
- active state;
- mobile behavior;
- permission filtering;
- badges;
- ordering;
- external links.

Navigation is inferred with explicit overrides. Fallback groups include Resources, Pages, and Security.

Hidden navigation is never treated as authorization.

## 28. HTMX pages and action results

Custom pages support GET and POST.

A page may have typed input and call services, external APIs, or scrapers owned by the application.

Full-page and fragment rendering use the same context. HTMX requests render the appropriate fragment; normal requests retain full-page fallback.

POST uses CSRF and idempotency. GET filters may push normalized URLs to browser history.

A structured `ActionResult` supports:

- fragment render;
- redirect;
- target refresh;
- success;
- rejection;
- validation failure;
- advanced response escape hatch.

Runtime translates results into HTMX headers, full-page redirects, toast notifications, or session flash messages.

Semantic target IDs are preferred over arbitrary CSS selectors.

## 29. Dashboard and widgets

Every admin may have an automatic dashboard containing launcher cards and widgets.

Launcher cards are derived from navigation or explicitly configured and remain permission-aware.

Dashboard and widgets have stable IDs.

Initial widget types:

- stat;
- text;
- list;
- table;
- custom template.

Layouts are declarative and responsive rather than pixel-positioned.

Loading modes:

- eager;
- lazy through HTMX.

Widget execution is read-only by default and uses operation scope, DI, timeout, cancellation, and permission checks.

Concurrent widget loading is bounded. Failure in one widget does not break the full dashboard.

Manual refresh is included. Auto-refresh, SSE, WebSocket updates, charts, per-user layouts, drag-and-drop builders, and widget caching are roadmap items.

## 30. Accessibility

Accessibility is a quality gate for built-in `0.1` components.

The target is WCAG-AA-equivalent principles without claiming formal certification.

Requirements include:

- semantic HTML;
- keyboard-operable controls;
- label/input relationships;
- accessible validation summary and field issues;
- HTMX focus management;
- accessible toast and flash messages;
- dialog focus trapping and restoration;
- semantic sortable tables and `aria-sort`;
- non-color status indicators;
- reduced-motion support;
- zoom-safe responsive layout;
- skip links, landmarks, headings, and meaningful page titles;
- accessible loading and error states.

Custom templates and widgets remain the developer's responsibility, but Rakit provides accessible macros and guidance.

Automated browser accessibility testing with Playwright and axe-core is planned for v1.

## 31. Dependency injection and service lifecycle

Rakit provides a typed explicit DI container, not a global service locator.

Scopes:

```text
APPLICATION
REQUEST
OPERATION
TRANSIENT
```

Hierarchy:

```text
application → request → operation
```

Operation scope may exist without HTTP for CLI, jobs, and tests.

Application services and scoped resources may use async context-manager lifecycle and `AsyncExitStack`.

Ownership is explicit. Rakit closes only services marked as owned.

Provider/factory injection is typed and configured at the composition root.

Handlers may use:

```python
context.services.require(ServiceType, name="optional-name")
```

Automatic handler-parameter injection may be considered later.

Compilation detects circular dependencies and captive dependencies. Longer-lived services receive factories rather than shorter-lived instances.

SQLAlchemy `Session` and `AsyncSession`, and `UnitOfWork`, are operation-scoped rather than request-scoped.

## 32. Database and library customization

Core does not define a universal database configuration.

Each adapter owns typed configuration.

Supported patterns:

1. convenience configuration where the plugin creates and owns a client/engine;
2. bring-your-own engine/client/factory with `owned=False`;
3. fully custom operation-scoped providers.

Multiple named data sources are supported. Resources select a data source explicitly or use a compatible unambiguous default. Ambiguity is a compilation error.

Sync libraries execute through a bounded thread pool. Async libraries execute directly.

Library-specific semantics remain visible.

## 33. Transactions

Write operations use an operation-scoped transaction.

Default behavior:

- commit only after success;
- rollback on exception or failure result;
- read operations do not commit;
- hooks do not commit unless transaction mode is manual.

Policies:

```text
AUTO
READ_ONLY
DISABLED
MANUAL
```

Suboperations inherit the current unit of work by default. Savepoints are explicit and capability-aware.

`before_commit` may veto a transaction. Post-commit events cannot undo it.

One automatic operation may read from multiple data sources but writes to only one. Multi-data-source automatic writes fail fast in `0.1`.

Distributed transactions, two-phase commit, outbox/inbox, sagas, compensating actions, and recovery are roadmap topics.

## 34. Events

Rakit `0.1` includes a typed in-process transaction-aware event system.

Event categories include:

- framework lifecycle;
- request;
- operation;
- transaction;
- resource;
- page;
- action;
- authentication;
- session;
- authorization;
- error;
- custom domain events.

Events use immutable envelopes containing:

- event ID;
- name;
- version;
- timestamp;
- typed payload;
- correlation and causation IDs;
- request and operation metadata;
- safe principal metadata.

`EventBus` is application-scoped. Publishers and dispatchers are operation-scoped.

Domain events are deferred by default and delivered after successful commit or successful non-transaction operation. Rollback discards deferred events.

Pre-events are serial, deterministic, and may reject an operation. Post-events observe outcomes and do not retroactively change successful results.

Default failure policies:

- pre/before-commit: propagate;
- post-commit: log and continue;
- startup: propagate;
- shutdown: log and continue.

Nested publication uses a queue rather than recursive dispatch, with depth/count limits and cycle diagnostics.

The initial system is not durable, exactly-once, or cross-worker. Brokers, outbox, retries, dead-letter queues, webhooks, OpenTelemetry, replay, and inspection are roadmap items.

## 35. Timeouts and cooperative cancellation

Every operation receives a deadline and cooperative cancellation context.

Timeouts may be configured globally and per operation type, resource, page, action, endpoint, or widget.

Cancellation may originate from:

- deadline expiry;
- graceful shutdown;
- parent cancellation;
- application cancellation;
- reliable client disconnect detection.

Cancellation is cooperative and transaction-aware.

Safe checkpoints exist before mutation, before commit, between bulk items, and after long external calls.

A commit in progress is not forcefully interrupted.

Timeouts normalize to a Rakit error and HTTP 504 for web operations.

Sync work uses a bounded thread pool. Rakit does not claim that cancelling a coroutine forcefully stops an underlying synchronous library.

Adapters declare cancellation, statement-timeout, rollback, or interrupt capabilities.

User-triggered cancellation, resumable operations, background-job cancellation, and distributed cancellation are roadmap items.

## 36. Error handling

All backend exceptions normalize to `RakitError`.

Errors carry:

- stable code;
- HTTP status;
- safe message;
- structured details;
- internal cause for logging only.

Categories include:

- configuration;
- validation;
- authentication;
- authorization;
- resource;
- datasource;
- page;
- action;
- endpoint;
- external service;
- template;
- timeout;
- internal.

The same domain error can render as:

- full HTML;
- HTMX fragment;
- custom endpoint JSON;
- future REST error;
- future GraphQL error extension.

Validation issues attach to fields. Toasts provide only summaries.

Unexpected exceptions receive a request ID and full internal structured logging, but no production traceback in responses.

Detailed debug pages are available only from trusted local hosts. No interactive Python console is exposed.

Startup configuration errors fail fast.

## 37. Structured logging

Structlog is the official logging system.

Rakit emits native structured events. Standard-library logging is bridged for Uvicorn, SQLAlchemy, and other libraries.

Development defaults:

- readable console renderer;
- DEBUG level.

Production defaults:

- JSON renderer;
- INFO level.

Rakit does not configure logging at import time or hijack the root logger.

Context uses `contextvars` plus explicit bound loggers across async/thread boundaries.

Sensitive values are redacted. Request bodies are not logged by default.

Operational logs and future persistent audit logs are separate systems.

Metrics, Prometheus, and OpenTelemetry are roadmap items.

## 38. Health, readiness, and lifecycle

Rakit exposes lightweight health and readiness endpoints under the admin mount:

```text
/_system/health
/_system/ready
```

Health indicates process liveness and avoids expensive dependency calls.

Readiness indicates:

- compilation complete;
- plugins started;
- required services available;
- critical data sources available;
- required schema revisions current;
- application not draining or stopping.

Public responses are minimal and do not reveal infrastructure details.

Runtime states:

```text
CREATED
COMPILING
STARTING
READY
DRAINING
STOPPING
STOPPED
FAILED
```

Dependency checks may be critical or optional, with timeouts, short caching, and bounded concurrency.

During graceful shutdown:

1. readiness becomes unavailable;
2. runtime enters draining;
3. active operations receive a grace period;
4. cancellation propagates near the deadline;
5. transactions finish or roll back safely;
6. scoped resources close;
7. owned services and plugins close in reverse order.

Lifecycle events and structured logs describe transitions and failures.

## 39. Caching policy

Rakit `0.1` does not provide automatic application-data caching.

Permitted internal caching:

- immutable compiled definitions;
- content-hashed static assets;
- short-lived health-check results;
- operation-scoped memoization.

Admin pages and sensitive responses use `Cache-Control: no-store`.

Rakit does not automatically cache:

- resource lists;
- record details;
- forms;
- authorization decisions across operations;
- counts;
- relationship lookups;
- dashboard data;
- private files.

Permissions are rechecked during mutation and protected downloads.

Applications and custom data sources may own their caching strategy.

A general cache protocol, Redis integration, event-driven invalidation, widget caching, stale-while-revalidate, and REST ETags are roadmap items.

## 40. Custom endpoints and future APIs

`AdminEndpoint` is a custom application endpoint, not a generated resource REST system.

Initial endpoint features:

- class and decorator APIs;
- GET and POST;
- explicit query, JSON, or form input;
- Pydantic input/output schemas;
- JSON default response;
- structured result types;
- authentication and permission by default;
- explicit public access;
- CSRF and idempotency for session POST;
- transaction policies;
- timeout and cancellation;
- normalized JSON errors;
- safe file/streaming escape hatches;
- stable ID and route;
- security and collision compilation checks.

GET is read-only by default. POST uses automatic transactions by default.

Streaming must not keep an implicit database transaction open after bytes start flowing.

Generated REST and GraphQL will use the same `ResourceService`, authorization, query, mutation, event, transaction, concurrency, and idempotency foundations.

## 41. CLI

Initial commands:

```text
rakit check
rakit createsuperuser
rakit permissions sync
rakit routes
```

Every command imports the same application composition root as the web runtime.

`rakit check` compiles and validates plugin, DI, route, permission, template, relationship, field, query, security, and package compatibility configuration.

`createsuperuser` uses the configured user provider and password hasher and never logs secrets.

`permissions sync` adds or updates the compiled catalogue and marks obsolete entries without deleting them automatically.

`routes` displays method, path, stable route name, owner, and primitive.

Commands use non-zero exit codes for failure and are suitable for CI.

Project scaffolding, migration running, shell tools, plugin discovery, storage cleanup, audit maintenance, and code generation are roadmap items.

## 42. Testing strategy

Initial official testing layers:

1. unit tests;
2. capability-aware adapter contract tests;
3. integration tests;
4. executable example smoke tests.

Tools:

- pytest;
- pytest-anyio;
- HTTPX and Starlette testing utilities;
- coverage.py.

Contract suites validate CRUD, identities, filters, sorting, pagination, relationships, transactions, concurrency, cancellation, and error translation according to declared capabilities.

Integration tests cover auth, sessions, CSRF, CRUD, relationships, actions, bulk operations, concurrency conflicts, local file upload, HTMX response contracts, and FastAPI mounting.

Official examples must import, compile, start, expose health/readiness, and render their main page in CI.

Playwright, browser E2E, visual regression, cross-browser coverage, and axe-core automation are targeted for v1.

Stable `data-rakit-*` semantic hooks are prepared in `0.1` without promising every internal DOM structure as public API.

## 43. Versioning and compatibility

Rakit uses Semantic Versioning.

Official workspace packages release in lockstep.

API stability labels:

- stable;
- provisional;
- experimental;
- internal.

Documented imports, override hooks, protocols, configuration fields, event names/versions, permission key formats, route names, template paths/blocks/context, CLI commands, error codes, and built-in migration identifiers may be public compatibility surfaces.

During `0.x`, normal public deprecations should remain available for two minor releases where practical.

Example:

```text
0.3 deprecated
0.4 still available
0.5 eligible for removal
```

After `1.0`, breaking public changes require a major release.

Security fixes may accelerate removal or change unsafe defaults when necessary, with transparent release notes and migration guidance.

Python 3.12 remains the baseline until an announced breaking release changes it.

Official packages validate lockstep version compatibility at runtime.

Plugins declare both a compatible Rakit version range and plugin API version.

Event payload breaking changes increment the event version.

Published Alembic migrations are forward-only and are not edited after release.

Documented template contracts are stable; internal DOM nesting and Tailwind classes are not.

Every release uses a structured changelog. Breaking changes receive migration documents.

## 44. Public imports

The umbrella `rakit` package is an ergonomic facade:

```python
from rakit import (
    Admin,
    ModelAdmin,
    ResourceAdmin,
    AdminPage,
    AdminEndpoint,
    ActionResult,
)
```

Advanced contracts use explicit namespaces:

```python
from rakit.core import ResourceQuery, RecordIdentity
from rakit.sqlalchemy import SQLAlchemyPlugin
from rakit.auth.sqlalchemy import SQLAlchemyAuthPlugin
from rakit.storage.local import LocalStoragePlugin
from rakit.server.uvicorn import UvicornServer
```

Importing `rakit` does not load all optional integrations.

Missing optional dependencies raise a Rakit-specific error with an installation command.

Proposed extras:

```text
rakit[sqlalchemy]
rakit[auth-sqlalchemy]
rakit[files]
rakit[settings]
rakit[standard]
```

`standard` provides the recommended official stack but excludes development tools.

Documented exports and `__all__` are public. Deep underscore-prefixed modules are internal.

Registration and plugin activation remain explicit.

## 45. Documentation and examples

Documentation is part of the product.

Target structure:

```text
docs/
├── getting-started/
├── guides/
├── concepts/
├── reference/
├── extending/
├── migrations/
├── design/
├── plans/
└── roadmap.md
```

Learning layers:

1. quick start;
2. practical task guides;
3. architectural concepts;
4. complete reference;
5. extension-author guides.

Initial example direction:

```text
examples/minimal
examples/fastapi-sqlalchemy
examples/builtin-auth
examples/relationships
examples/internal-tools
examples/custom-datasource
examples/dashboard
```

Examples are executable and tested in CI.

The repository should contain:

- focused README;
- design specification;
- roadmap without date promises;
- `SECURITY.md`;
- `CONTRIBUTING.md`;
- `CODE_OF_CONDUCT.md`;
- license;
- changelog.

Task-by-task implementation plans are local, maintainer-only working
documents that drive development. They are not committed to the repository,
are not published documentation, and are not a public API or compatibility
commitment — the design specification and the shipped public API remain the
source of truth.

Large irreversible decisions may receive ADRs under `docs/design/decisions/`.

The documentation generator can be selected during implementation planning. MkDocs Material is a likely option but is not an architectural contract.

## 46. Explicitly deferred systems

The following are not initial features:

- generated REST resource API;
- GraphQL;
- OpenAPI and interactive API docs;
- background job engine;
- persistent audit log;
- import/export;
- official external storage adapters;
- general application cache;
- metrics, Prometheus, and OpenTelemetry;
- advanced search providers;
- internationalization/localization;
- multi-tenancy;
- browser E2E with Playwright;
- chart widgets;
- live dashboard updates;
- distributed transactions.

The architecture preserves extension boundaries where already justified but avoids adding placeholder abstractions everywhere before real use cases exist.

## 47. Non-goals

Rakit is not intended to be:

- a universal ORM;
- a universal migration engine;
- a production migration auto-runner;
- a scraping engine;
- a background-job engine;
- a custom cryptography library;
- a global magic service locator;
- an auto-discovery framework that activates installed packages implicitly;
- a system that hides backend-specific limitations.

## 48. Final approved baseline

The approved initial baseline is a security-first, typed, composable Python framework with:

- framework-agnostic domain definitions;
- Starlette-based ASGI web runtime;
- SQLAlchemy administration;
- complete relationship editing;
- typed forms and mutation plans;
- explicit DI and transactions;
- transaction-aware events;
- secure sessions and RBAC;
- optimistic concurrency and idempotency;
- local private file storage;
- HTMX/Jinja/Tailwind UI;
- dashboards and widgets;
- custom JSON endpoints;
- structured logs;
- health/readiness and graceful lifecycle;
- strong documentation and testing expectations.

This design is the source of truth for implementation planning. Any later implementation plan must preserve the locked decisions or explicitly document a proposed design change for review.
