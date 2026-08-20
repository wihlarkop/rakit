# Phase B Reference Application & DX Hardening Design

## Purpose

Phase B closes the gap between individually complete Rakit subsystems and a coherent real-world developer experience. The deliverable is a realistic `examples/reference_app` built from public Rakit APIs, followed by narrowly-scoped framework fixes that are justified by friction encountered while building that application.

This work does **not** publish a release, create a tag, or change the package version.

## Success criteria

Phase B is complete when:

1. `examples/reference_app` is a self-contained backoffice application that runs against SQLite and local private storage.
2. The example uses public `rakit.*` imports for all Rakit functionality.
3. It exercises SQLAlchemy CRUD, authentication, authorization, users/roles, relationships, uploads, filtering/search/sorting, actions, bulk actions, custom pages, dashboard widgets, and generated REST.
4. Developer friction discovered during implementation is fixed in Rakit itself when the fix is clearly reusable and appropriately scoped.
5. The example has deterministic development bootstrap/seed behavior and clearly marks development-only shortcuts.
6. Regression tests are added only after the source implementation and non-test verification are complete.
7. The final full CI matrix and release-level artifact gates pass.
8. `docs/roadmap.md` records all of Phase B as complete while release remains explicitly deferred.

## Reference application domain

The reference application is **Rakit Commerce Operations**, a compact but realistic operations backoffice.

Application-owned SQLAlchemy models:

- `Customer`
  - id
  - name
  - email
  - status
  - created_at
- `Product`
  - id
  - sku
  - name
  - price_cents
  - inventory_count
  - status
  - image descriptor field
  - created_at
- `Order`
  - id
  - customer_id
  - status
  - total_cents
  - created_at
- `OrderItem`
  - id
  - order_id
  - product_id
  - quantity
  - unit_price_cents

The application also uses Rakit-owned built-in SQLAlchemy auth models for users, roles, permissions, sessions, and idempotency.

## Persistence and runtime

The example uses an on-disk development directory:

```text
.rakit-reference/
  reference.sqlite3
  uploads/
```

SQLite is used through SQLAlchemy's async engine with `aiosqlite`. The application owns the engine and disposes it in lifespan shutdown.

For a zero-friction development demo, startup creates the application and Rakit auth tables from metadata if absent and seeds deterministic sample data. This `create_all` bootstrap is explicitly documented as development-only. Production applications must use migrations.

The reference app must not delete/reset an existing database on every startup. Seeding is idempotent: it inserts baseline rows only when the relevant tables are empty or the deterministic seed key is absent.

## Authentication and authorization

The example uses `SQLAlchemyAuthPlugin`, not an in-memory demo backend.

Two deterministic development accounts are seeded:

- `admin@example.com` / `rakit-demo-password`
  - superuser
- `operator@example.com` / `rakit-demo-password`
  - non-superuser
  - assigned an `operations` role

The framework permission catalogue is synchronized into the built-in permission table during bootstrap. The `operations` role receives a deliberately limited subset of resource permissions so the example exercises real allow-only RBAC rather than only the superuser bypass.

The example exposes safe user/role/permission resource views without exposing `password_hash` or session/idempotency internals.

## B4 DX fix: public SQLAlchemy-auth provisioning surface

Building a persistent authenticated reference app currently requires imports from `rakit_auth_sqlalchemy.models`, `rakit_auth_sqlalchemy.passwords`, and `rakit_auth_sqlalchemy.rbac`. That violates the public-facade rule established in B2.

`rakit.auth.sqlalchemy` will therefore expose the operational building blocks required by application bootstrap and operator tooling:

- `AuthBase` — alias of the built-in auth declarative base.
- `User`.
- `Role`.
- `Permission`.
- `Argon2PasswordHasher`.
- `PermissionSyncResult`.
- `sync_permissions`.
- existing `SQLAlchemyAuthPlugin`.
- existing `SQLAlchemyIdempotencyStore`.

This is intentionally an export/facade correction, not a new authentication subsystem. Existing physical package boundaries remain unchanged.

## Resources

### Customers

- full CRUD.
- list/detail fields.
- status filtering.
- name/email search.
- deterministic sorting.
- generated REST CRUD.

### Products

- full CRUD.
- inventory/status filters.
- SKU/name search.
- local private image upload through a `FileField`/image presentation where the current public form contract supports it.
- generated REST CRUD for non-file scalar fields; file upload stays on the web form path if the generated API does not honestly support multipart storage yet.

### Orders

- CRUD appropriate to the current SQLAlchemy adapter.
- customer relationship.
- order-item relationship.
- status filters/search/sorting.
- generated REST read or CRUD according to the current executor's honest mutation support.
- record action `mark_paid` or equivalent deterministic state transition.
- bulk action `mark_processing` or equivalent.

### Order items

- relationship-supporting resource.
- product relationship.
- order relationship.
- quantity/unit price fields.

### Auth resources

- users: safe fields only.
- roles: safe fields only.
- permissions: read-only operational visibility.

## Actions

Actions should exercise existing public action contracts without adding speculative action infrastructure.

At minimum:

- record action on `Order` that changes a status through the current mutation/service path.
- bulk action on orders that demonstrates a realistic bulk operation and explicit best-effort/all-or-nothing policy.
- a page-level or resource-level operational action if it can be implemented without artificial boilerplate.

Actions must preserve the framework's transaction and authorization semantics. No direct hidden database side channel should bypass Rakit's operation context where an existing public operation service is appropriate.

## Custom page

Add an `/operations` page that summarizes operational guidance and current environment facts useful to a maintainer/operator. It should be server-rendered and use a normal `PageDefinition`/`PageResult` flow.

## Dashboard

Register a `main` dashboard with SQLAlchemy-backed loaders for:

- total customers.
- active products / low inventory.
- pending or processing orders.
- recent orders table.

Widget loaders resolve the application's session factory explicitly and issue deterministic SQLAlchemy queries.

## Storage

Register one private local storage named `product_images` rooted under `.rakit-reference/uploads/products`.

The application must use the neutral public facade:

```python
from rakit.storage.local import LocalStorage, LocalStoragePlugin
```

Uploaded file metadata is stored through the normal Rakit web mutation pipeline. The example documents the private-storage behavior and deliberately avoids pretending that public CDN/presigned delivery exists in the alpha contract.

## Generated REST

At least customers, products, and orders declare a `ResourceApiDefinition` through their `ModelAdmin.api` attribute.

The example demonstrates current generated API behavior rather than future OpenAPI productization. It should make it easy to inspect routes via:

```bash
uv run rakit routes examples.reference_app.main:admin
```

## Application composition

File responsibilities:

```text
examples/reference_app/
  __init__.py      package marker
  models.py        application-owned SQLAlchemy models only
  database.py      engine/session factory and dev bootstrap/seed
  resources.py     ModelAdmin declarations, filters, relationships, actions
  dashboard.py     widget loaders and dashboard registration helper
  main.py          Admin composition, plugins, storage, page, lifespan/ASGI
  README.md        exact run/login/inspection instructions and production caveats
```

The files are intentionally split by responsibility so the example remains understandable and can reveal awkward public interfaces instead of hiding everything in one monolithic example module.

## Public-API rule

All Rakit imports inside `examples/reference_app` must begin with one of:

- `rakit`
- `rakit.core`
- `rakit.sqlalchemy`
- `rakit.auth.sqlalchemy`
- `rakit.storage`
- `rakit.storage.local`

The reference app must not import `rakit_core`, `rakit_web`, `rakit_sqlalchemy`, `rakit_auth_sqlalchemy`, or `rakit_storage_local` directly.

This rule is itself a regression target.

## Non-test verification before regression tests

Before adding tests:

1. import every new reference-app module from a clean workspace environment.
2. compile `admin`.
3. run `rakit check` against the reference app.
4. inspect `rakit routes` output for expected HTML/auth/generated-API routes.
5. initialize the development database and seed twice to confirm idempotency.
6. authenticate both development accounts at the backend level.
7. verify storage root setup and application lifecycle cleanup.
8. perform safe direct SQL queries confirming seed relationships and role grants.

## Regression tests

Tests are added after source/manual verification and should cover:

- public auth facade exports.
- reference app imports only allowed Rakit public namespaces.
- reference app compiles.
- development bootstrap is idempotent.
- seeded admin and operator authenticate successfully.
- operator role has a limited non-empty permission set.
- representative resource/generated-API routes exist.
- representative dashboard loaders return expected result types.
- reference app does not require network access.

Avoid brittle browser snapshot tests in Phase B; browser-level Playwright/axe/visual regression belongs to Phase N.

## Documentation and status

When implementation and verification pass:

- mark B2.7, B3, and B4 complete in `docs/roadmap.md`.
- update the current-position table so the next major workstream is Phase C.
- add the reference app and auth-facade refinement to `CHANGELOG.md` under `Unreleased`.
- do not add a release date.
- do not tag or publish anything.

## Explicit non-goals

- OpenAPI/Swagger/ReDoc productization.
- GraphQL.
- API keys/tokens.
- cloud storage.
- browser E2E automation.
- new adapter ecosystems.
- scaffolding/`rakit init`.
- changing the package version.
- release publication.
